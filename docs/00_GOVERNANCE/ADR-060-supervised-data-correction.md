# ADR-060 — Corecția de date supervizată e o operație distinctă de orice owner curent

**Status**: Approved — 2026-08-22
**Decide**: cum se corectează o valoare deja persistată, demonstrat greșită, când niciun owner existent (ADR-036) o poate repara.
**Relație cu ADR-036**: nu îl contrazice — îl completează. ADR-036 guvernează *cine scrie o valoare nouă*; acest ADR guvernează *cine repară o valoare veche, dovedit greșită*, când owner-ul declarat e structural incapabil.
**Relație cu ADR-059**: aceeași disciplină de „marchează, nu contopește" aplicată acum scrierii, nu doar identității.

---

## Context

Trei goluri descoperite independent, în aceeași sesiune (2026-08-22), pe măsură ce reconcilierea identității (ADR-025 Faza 3+4, ADR-059) a scos la iveală probleme aflate anterior sub pragul de vizibilitate:

1. **Scoruri corupte, dovedite** — `sync/sources/football_data.py::_parse_match()` citea `score.fullTime` fără să verifice `score.duration`. Pentru un meci decis la penalty-uri, `fullTime` include loviturile de departajare — scorul real e în `score.regularTime`. Bug reparat la sursă; auditul exhaustiv (`scripts/audit_penalty_shootout_rows.py`, toate cele 24 de perechi liga/sezon `fd_*`, 7.534 rânduri verificate contra API, 0 negăsite) a găsit **6 rânduri corupte, exact cele 6 meciuri decise la penalty-uri din API** — corespondență perfectă, nicio discrepanță neexplicată. 3 din 6 au și eticheta `actual_result` greșită (un rezultat de egalitate înregistrat ca victorie), toate cu `used_for_training = true`.
2. **ELO deja persistat pe lanțuri fragmentate** — măsurat (`scripts/measure_elo_divergence.py`, run `32558948226`): 1.1% din valorile ELO pre-meci diferă cu ≥50 puncte față de un replay corect.
3. **Vocabular incomplet (D2+D3)** — nume care ar trebui să fie aceeași identitate, dar fie nu colizionează încă (D2, 616 rânduri, 106 lanțuri rupte), fie vocabularul nu le unește deloc (D3, descoperit acum: 61 perechi de nume cu dovadă factuală de duplicat, verificat fără nicio potrivire fuzzy — vezi `scripts/detect_identity_alias_candidates.py`).

Toate trei au aceeași cauză structurală: **`_upsert_match_canonical_locked` (RPC de producție) și `run_backfill()` sunt NULL-only prin design** (ADR-059, secțiunea „Argumentul de corectitudine"; v4.1 gating). Corect pentru scrierea normală — previne exact clasa de bug documentată acolo (o valoare rea care blochează definitiv owner-ul legitim). Dar înseamnă că **sistemul nu are, azi, niciun mecanism sancționat pentru „această valoare e demonstrat greșită, corecteaz-o"**. Fiecare din cele trei goluri a fost pe cale să primească propriul fix ad-hoc, izolat — exact tiparul pe care Discovery Rule (`CLAUDE.md`) cere să fie oprit și prezentat explicit înainte de a continua.

### De ce nu e o extindere a ADR-036

ADR-036 răspunde la întrebarea „cine scrie o coloană când valoarea vine din fluxul normal". Corecția răspunde la o întrebare diferită: „ce faci cu o valoare deja scrisă corect din punct de vedere al contractului de scriere, dar demonstrat greșită ca fapt". Owner-ul declarat (`sync_results` pentru `actual_*`, `run_backfill` pentru ELO) rămâne owner — corecția nu-i ia locul, nu-i schimbă contractul de scriere normal, nu creează un al doilea scriitor concurent pentru fluxul zilnic. Corecția e o operație **rară, supervizată, cu blast radius cunoscut dinainte**, nu un nou pas în pipeline.

## Decizie

**Corecția de date e o operație separată, cu contract propriu, aplicabilă doar când sunt îndeplinite simultan toate condițiile de mai jos.**

### Condiții de eligibilitate (toate obligatorii)

1. **Dovadă verificată contra sursei, nu presupunere.** Valoarea corectă vine dintr-un audit care compară explicit persistat vs. adevărul unei surse externe (API, recalcul determinist) — niciodată dintr-o inferență sau o „pare corect". Vezi `scripts/audit_penalty_shootout_rows.py` ca precedent: fiecare din cele 6 corecții e verificabilă independent, cu id-ul rândului, valoarea veche și valoarea nouă, ambele citate.
2. **Corpus închis, cunoscut dinainte de scriere.** Nu „corectează tot ce pare greșit" — o listă explicită, finită, de id-uri, generată de auditul read-only și inspectată de om înainte de execuție. Un corpus deschis (]"orice rând viitor care arată așa") nu e corecție, e un nou owner permanent — asta ar cere ADR propriu, nu acesta.
3. **Suprafață de scriere minimă.** Corecția scrie *exact* coloanele demonstrat greșite, nimic altceva. Nu reface ceilalți pași ai pipeline-ului normal (recalibrare, retrigger de backfill) ca efect secundar — vezi „Ce NU declanșează" mai jos.
4. **SQL exact arătat, aprobare explicită, separată de aprobarea etapei** (`supabase-safety`, North Star #6). Corectarea nu e „urgentă" — o zi în plus pentru revizuire umană explicită e mereu mai ieftină decât o scriere greșită în producție.
5. **Idempotență verificabilă.** Reluarea corecției (accidentală sau deliberată) nu trebuie să producă o stare diferită. WHERE-ul include valoarea veche așteptată — dacă rândul nu mai are acea valoare (deja corectat, sau schimbat de altceva), UPDATE-ul nu atinge nimic, nu suprascrie orbește.

### Ce NU declanșează

- **Nicio recalibrare** (`_recalibrate_for_result`, ponderi per ligă). O corecție de scor nu e un rezultat nou observat despre care sistemul „învață" — e o reparație a unei observații deja greșit înregistrate. Declanșarea recalibrării ar bundle-ui tacit o schimbare de model într-un fix de date, exact ce interzice explicit „Filosofia proiectului" din `CLAUDE.md` („bug fix-urile nu introduc schimbări de model").
- **Niciun reset necondiționat de `backfill_done`/ELO/features.** Un rând corectat poate avea nevoie de recalcul downstream (ELO calculat pe scorul greșit, de exemplu) — dar acela e un pas separat, propriu, cu propriul blast radius calculat și arătat explicit, niciodată un efect automat al UPDATE-ului de corecție.

### Relația cu cele trei goluri deschise

Acest ADR autorizează contractul, nu execuția fiecărui caz — fiecare rămâne gatat separat, cu propriul corpus verificat și propriul SQL arătat:

| Gol | Corpus | Coloane corectate | Stare |
|---|---|---|---|
| Scoruri penalty-shootout | 6 rânduri, id-uri fixe (`3623, 3625, 3634, 3809, 3814, 114439`) | `actual_home_goals`, `actual_away_goals`, `actual_result` | Executat sub acest ADR — vezi jurnalul de execuție de mai jos |
| Vocabular D3 (extindere vocabular) | 58 perechi → 53 identități, `scripts/detect_identity_alias_candidates.py` | `mappings.py` (`TEAM_ALIASES`) | Executat — vezi Jurnalul de execuție, Faza 2a |
| Redenumire D2+D3 (rânduri deja scrise) | 2.477 rânduri, 168 nume distincte | `home_team`, `away_team` în `match_history` | Executat — vezi Jurnalul de execuție, Faza 2b |
| Rebuild feature-uri (ELO + 16 alte coloane calculate de `run_backfill()`) | 51.046 rânduri (`superseded_by IS NULL AND actual_result IS NOT NULL`) | cele 20 `BACKFILL_COLUMNS` (nu doar ELO — vezi Jurnalul de execuție, Faza 3, pentru descoperirea amplorii reale) | **Executat, verificat complet — 100,0% divergență-zero pe întregul corpus (vezi Jurnalul de execuție, Faza 3)** |

Ordinea (scoruri → vocabular → ELO) nu e arbitrară: rebuild-ul ELO citește `actual_home_goals`/`actual_away_goals` (deci trebuie să ruleze după corecția scorurilor) și grupează pe `home_team`/`away_team` (deci trebuie să ruleze după unificarea vocabularului, altfel recalculează corect peste lanțuri încă fragmentate — exact observația din măsurătoarea ELO).

## Consecințe

- Corecția devine un tip de operație recunoscut explicit, nu o excepție ad-hoc negociată separat de fiecare dată. Următorul caz similar (dacă apare) verifică aceleași 5 condiții, nu inventează un proces nou.
- Rândurile corectate nu-și pierd trasabilitatea: script-ul de corecție e păstrat în repo (nu șters ca un POC), cu sursa verificării citată (run ID Actions al auditului). Oricine poate reface verificarea independent.
- Rebuild-ul ELO și redenumirea D2/D3 rămân, deliberat, în afara scopului acestei execuții — condiția „corpus cunoscut dinainte" înseamnă că fiecare are propriul corpus verificat separat, prezentat separat, aprobat separat.
- Nu se creează niciun mecanism nou, permanent, de scriere pe `actual_*`/ELO/nume — corecția rămâne, prin condiția 2, o operație cu corpus închis, nu un al doilea owner concurent cu `sync_results`/`run_backfill`.

## Jurnal de execuție — Faza 1 (scoruri penalty-shootout)

Executat 2026-08-22, imediat după aprobarea acestui ADR.

**Dovadă** (condiția 1): `scripts/audit_penalty_shootout_rows.py`, GitHub Actions run `32560333453` — 7.534 rânduri `fd_*` verificate contra `football-data.org`, 0 negăsite, 6 nepotriviri, toate cele 6 corespunzând exact celor 6 meciuri raportate de API ca `PENALTY_SHOOTOUT`.

**Corpus** (condiția 2), fixat înainte de scriere:

| id | fixture_id | meci | persistat | corect |
|---|---|---|---|---|
| 3623 | `fd_451665` | Arsenal – Porto, 2024-03-12 | 5-2 (H) | 1-0 (H) |
| 3625 | `fd_451668` | Atlético Madrid – Inter Milan, 2024-03-13 | 5-3 (H) | 2-1 (H) |
| 3634 | `fd_451679` | Manchester City – Real Madrid, 2024-04-17 | 4-5 (A) | 1-1 (D) |
| 3809 | `fd_524100` | Liverpool – Paris Saint-Germain, 2025-03-11 | 1-5 (A) | 0-1 (A) |
| 3814 | `fd_524102` | Atlético Madrid – Real Madrid, 2025-03-12 | 3-4 (A) | 1-0 (H) |
| 114439 | `fd_552096` | Paris Saint-Germain – Arsenal, 2026-05-30 | 5-4 (H) | 1-1 (D) |

**Suprafață** (condiția 3): exact `actual_home_goals`, `actual_away_goals`, `actual_result` — nicio altă coloană. Nicio recalibrare declanșată. Niciun reset de `backfill_done`/ELO — recalculul downstream (ELO afectat de scorul greșit pe aceste 6 rânduri) rămâne parte a rebuild-ului ELO planificat, nu un efect automat al acestei corecții.

**Aprobare** (condiția 4): SQL exact arătat proprietarului produsului, aprobat explicit („aprob") separat de aprobarea etapei generale.

**Idempotență** (condiția 5): `scripts/correct_penalty_shootout_scores.py` — fiecare `UPDATE` are `WHERE id = ... AND actual_home_goals = <valoarea_veche> AND actual_away_goals = <valoarea_veche>`. O rulare repetată nu produce efect, fiindcă WHERE-ul nu mai găsește valoarea veche.

**Efect secundar observat, nu presupus**: corectarea rândului `fd_524100` (Liverpool–PSG) a făcut ca acesta să coincidă exact (scor + rezultat) cu rândul geamăn `openfootball_...` — singurul grup HARD CONFLICT rămas nereconciliat după ADR-025 Faza 4. Verificat separat, prin mecanismul deja aprobat (`scripts/run_identity_reconciliation_dryrun.py`): grupul a devenit reconciliabil (1 grup, 1 reconciliat, 0 hard conflict). Executat prin `run_identity_reconciliation_full.py` (mecanism ADR-059, nu o extindere a acestui ADR) — rândul `openfootball` (rank sursă 6) marcat `superseded_by` rândul `fd_` (rank sursă 2), rândul canonic neatins. Confirmat independent în bază.

## Jurnal de execuție — Faza 2a (extindere vocabular D3)

Executat 2026-08-22, imediat după Faza 1.

**Dovadă**: `scripts/detect_identity_alias_candidates.py`, GitHub Actions run `32561462931` — 54.393 rânduri live analizate, 61 perechi cu dovadă pozitivă, 3 respinse de veto (au meciuri directe reale: `FCSB`/`Sepsi OSK`, `CFR Cluj`/`Chindia Targoviste`, `Din. Bucuresti`/`Farul Constanța`), 58 rămase.

**Corpus**: cele 58 de perechi grupate prin union-find (offline, determinist) în **53 identități distincte** — 4 clustere de 3 nume (`Braga`/`Sp Braga`/`Sporting Braga`, `Estoril`/`GD Estoril`/`GD Estoril Praia`, `NEC`/`NEC Nijmegen`/`Nijmegen`, `Guimaraes`/`Vitória Guimarães`/`Vitória SC`), restul perechi simple. 6 din 53 aterizează pe o cheie canonică deja existentă în `mappings.py` (`Benfica`, `Braga`, `Marseille`, `Nijmegen`, `Sporting CP`, `Twente`) — extinse cu aliasuri noi, nu recreate. Restul de 47 sunt chei canonice noi.

**Verificare suplimentară, dincolo de veto** (condiția 1, dovadă verificată): cazul cu cel mai mare risc de fuziune falsă — `Ajaccio`, fiindcă Corsica are istoric două cluburi (AC Ajaccio și Gazélec Ajaccio) — verificat direct în bază: toate cele 38 de rânduri `AC Ajaccio` (openfootball, sezonul 2022-2023) au un rând-geamăn exact pe (zi, ligă, scor) în cele 157 de rânduri `Ajaccio` (kaggle, 2000-2025), acoperire 38/38, nicio rămășiță neexplicată. O singură adăugare manuală, în afara dovezii automate: `Goztepe` (4 rânduri, Flashscore, meciuri **viitoare**, deci fără dovadă pozitivă posibilă — nu există încă un meci trecut de comparat) — verificat direct: aceeași ligă (Super Lig) ca `Goztep`/`Göztepe`, variantă fără diacritică a aceluiași nume.

**Suprafață**: exclusiv `mappings.py` (`TEAM_ALIASES`, 53 de intrări — 6 extinderi + 47 chei noi). **Nu atinge nicio coloană din `match_history`** — vocabularul extins schimbă doar comportamentul viitor al `normalize_team_name()`; rândurile deja scrise cu numele vechi rămân neschimbate până la Faza 2b (redenumire).

**Verificare**: `tests/test_adr060_d3_vocabulary_extension.py` (5 teste) — toate cele 53 de clustere unifică corect, cele 3 perechi vetoate rămân distincte, niciun alias nou nu e deja folosit pentru alt canonic, clusterele de 3 nume sunt complet tranzitive. Suita completă `pytest tests/`: verde.

## Jurnal de execuție — Faza 2c (reconciliere de masă, declanșată de extinderea vocabularului)

Executat 2026-08-22, imediat după Faza 2a. **Nu era planificată** — a fost o descoperire în timpul pregătirii Fazei 2b (redenumire), tratată conform Discovery Rule.

**Ce s-a întâmplat**: rulând planul de redenumire (Faza 2b) pe date reale, `analyze_d2_vocabulary_drift.py` a raportat **peste 2.700 de coliziuni** pe cheia indexului unic — mult peste amploarea D2 originală (616 rânduri). Investigație: extinderea vocabularului din Faza 2a (`AZ`↔`AZ Alkmaar`, `FC Utrecht`↔`Utrecht`, `Almere City`↔`Almere City FC` etc., majoritatea cluburi din Eredivisie/Primeira Liga/Super Lig) a unificat perechi de nume care coexistau deja, nedetectate, ca serii **complet paralele** de-a lungul mai multor sezoane — nu fragmente izolate, ci sezoane întregi înregistrate de două ori sub două nume diferite.

**Verificare, nu presupunere**: rulat `run_identity_reconciliation_dryrun.py` (mecanismul deja aprobat ADR-059, nu o unealtă nouă) — **2.760 grupuri duplicate, 2.759 reconciliabile, 1 HARD CONFLICT nou, 2.827 rânduri de marcat**. Mecanismul de siguranță deja construit în serviciu (`HARD_CONFLICT_COLUMNS`: `actual_result`/`actual_home_goals`/`actual_away_goals` trebuie să coincidă pe tot grupul) a validat singur 2.759 din 2.760 de grupuri — dacă scorurile ar fi diferit, ar fi fost excluse automat, nu forțate.

**HARD CONFLICT investigat, nu ignorat**: `nijmegen||vitesse||2023-10-01` — verificat direct: `id=78154` (kaggle) are 1-3, `id=127878` (fd) are 1-2. Discrepanță reală de scor între surse, fără un bug cunoscut care s-o explice (spre deosebire de Liverpool–PSG). Corect exclus automat, rămâne deschis pentru investigare separată — **nu s-a inventat o corecție** fără dovadă verificată contra unei surse externe (condiția 1, ADR-060).

**Execuție**: `run_identity_reconciliation_full.py` (același script, aceeași suprafață — doar `superseded_by`/`at`/`reason`, doar rândul necanonic) — **2.827/2.827 rânduri marcate, 0 erori de scriere**. Verificat independent, direct în bază: totalul `match_history` neschimbat (58.300), live 54.393→51.565 (-2.827, exact), superseded 3.908→6.735 (+2.827, exact), 0 rânduri canonice greșit marcate, 0 orfani FK.

**Relația cu ADR-059**: acesta e exact scenariul avertizat în secțiunea „Gol rămas deschis" a acelui ADR — „orice extindere viitoare de vocabular reintroduce fragmentarea, tăcut" — dar materializat la o scară mult mai mare decât precedentele (F3/TSDB, câteva meciuri) și cu semn opus: acolo fragmentarea *ascundea* dubluri deja periculoase; aici extinderea vocabularului le-a *dezvăluit*, iar mecanismul deja construit (nu unul nou) le-a rezolvat corect.

**Consecință pentru procesul viitor**: orice extindere de vocabular (Faza 2a, sau orice alias nou adăugat vreodată în `mappings.py`) trebuie urmată OBLIGATORIU de un dry-run de reconciliere înainte de orice redenumire — nu opțional, nu „probabil nu e nevoie". Ordinea corectă, confirmată empiric: **extinde vocabularul → reconciliază duplicate → abia apoi redenumește supraviețuitorii**.

## Jurnal de execuție — Faza 2b (redenumire la forma canonică)

Executat 2026-08-22, imediat după Faza 2c.

**Dovadă** (condiția 1): `scripts/rename_teams_to_canonical.py::plan_renames()` reutilizează `classify()` din `scripts/analyze_d2_vocabulary_drift.py` — ACELAȘI cod care a produs numărătorile prezentate înainte de aprobare, nu o reimplementare paralelă. Sursa adevărului pentru „canonic" e exclusiv `mappings.normalize_team_name()`, deja aprobată în Faza 2a.

**Corpus** (condiția 2): calculat determinist din starea live la momentul rulării — 168 nume distincte, 2.479 rânduri candidate, din care 2 excluse automat (coliziunea deja cunoscută `nijmegen||vitesse||2023-10-01`), rămân **2.477 de redenumit**. Verificat de două ori, la interval de câteva minute (dry-run → EXECUTE), cu rezultate identice (168/2.477/2 stabile).

**Suprafață** (condiția 3): exclusiv `home_team`/`away_team`, pe rândul care are nevoie de schimbare. Nicio coloană ELO/feature/predicție atinsă — rebuild-ul rămâne Faza 3, separată.

**Aprobare** (condiția 4): dry-run arătat explicit (exemple + numărători complete) înainte de `--execute`.

**Idempotență** (condiția 5): fiecare `UPDATE` verifică `home_team`/`away_team` VECHI în WHERE — o rulare repetată nu găsește nimic de schimbat pe rândurile deja redenumite.

**Execuție**: **2.477/2.477 rânduri redenumite, 0 sărite, 0 erori**. Verificat independent, direct în bază: totalul `match_history` neschimbat (58.300 rânduri, 51.565 live, 6.735 superseded — identic înainte/după, cum era de așteptat pentru o operație care nu schimbă numărul de rânduri). Re-rularea analizei D2 confirmă rezultatul: **nume distincte în uz 1.236 → 1.066**, D2 rămas = exact cele 2 nume din singura coliziune cunoscută (`Nijmegen`/`NEC`, `Vitesse`/`SBV Vitesse`), nicio altă fragmentare reziduală.

**Consecință**: vocabularul de identitate e acum stabil — orice extindere viitoare de vocabular trebuie să repete ciclul complet (extinde → reconciliază duplicate → redenumește supraviețuitorii), documentat ca proces obligatoriu în Faza 2c de mai sus.

## Jurnal de execuție — Faza 3 (rebuild feature-uri, singura operație ireversibilă)

Executat 2026-08-22, cu aprobare explicită separată (per condiția 4) pentru pasul de reset — dincolo de delegarea generală de arhitect, cerută explicit de skill-ul `supabase-safety` pentru orice operație distructivă.

**Descoperire care a schimbat scopul, verificată înainte de a acționa**: propunerea inițială discutată cu proprietarul produsului viza „rebuild ELO" (4 coloane). Citind direct codul `sync/backfill_features.py` înainte de a scrie orice SQL, s-a constatat că **toți cei 7 tracker-e din `run_backfill()`** (`ELOTracker`, `FormTracker`, `ShotsTracker`, `FoulsTracker`, `ShotCountTracker`, `CornerCardTracker`, `H2HTracker`) sunt indexate pe **numele echipei ca șir de caractere** (sau perechi de nume, pentru H2H) — exact același defect structural care a fragmentat ELO fragmentează identic toate cele **20 de `BACKFILL_COLUMNS`**. Scopul a fost extins corect, nu ținut la „doar ELO" din inerție.

**Verificare că mecanismul existent e suficient, fără cod nou**: `run_backfill()` recalculează întotdeauna toate cele 20 valori (calcul Python ieftin) dar scrie DOAR coloanele NULL curente (`_missing_feature_columns`). Deci: resetarea celor 20 de coloane la NULL, urmată de o rulare normală, nemodificată, a `sync/backfill_features.py` (deja folosit zilnic în producție, `backfill.yml`) recalculează corect totul, fără nicio linie de cod nouă pentru replay — se reutilizează mecanismul deja testat, nu se scrie unul paralel.

**Verificări de siguranță, înainte de scriere**:
- `home_elo`/`away_elo` (pre-meci) alimentează `ml_predictor.FEATURE_COLUMNS`, citite live din DB la antrenare — fără snapshot înghețat, deci fără risc de scurgere temporală prin rebuild.
- `home_elo_after`/`away_elo_after` (post-meci) confirmate, din nou, absente din setul de antrenare ML.
- `database.queries.get_latest_team_elo()` (servire live) citește direct din DB, cu doar un cache in-memory per-proces, fără persistență — nicio invalidare manuală necesară.
- Mecanismul de scriere (`update_match_features`) e idempotent și reluabil per-coloană — un timeout la jumătatea rulării nu corupe nimic, doar lasă progres parțial, reluabil identic.

**Corpus** (condiția 2): `WHERE superseded_by IS NULL AND actual_result IS NOT NULL` — **51.046 rânduri**, verificat prin `count(*)` înainte de orice scriere.

**Backup, înainte de orice scriere distructivă**: `CREATE TABLE match_history_backfill_backup_20260822 AS SELECT ...` — snapshot al celor 20 de coloane + `backfill_done` pentru exact cele 51.046 de rânduri din corpus, `ENABLE ROW LEVEL SECURITY` (același tipar ca `odds_history`, ADR-005). Verificat independent, nu presupus: `count(*)` din backup = 51.046 (potrivire exactă cu corpusul), plus comparație directă valoare-cu-valoare pe un eșantion (5 rânduri, `home_elo`/`home_elo_after` identice live vs. backup).

**Reset** (SQL exact arătat, aprobat explicit): `UPDATE match_history SET <20 coloane> = NULL, backfill_done = false WHERE superseded_by IS NULL AND actual_result IS NOT NULL`. Verificat direct în bază, nu presupus corect: 51.046 rânduri din corpus au acum `home_elo IS NULL` (potrivire exactă). Un semnal aparent de alarmă — 504 rânduri suplimentare cu `home_elo IS NULL` în afara corpusului — investigat imediat, nu ignorat: 498 sunt meciuri viitoare (`actual_result IS NULL`, nu au avut niciodată ELO calculat) și 6 sunt rânduri superseded fără rezultat; **zero** rânduri superseded CU rezultat afectate. Confirmat atât logic (WHERE-ul exclude structural aceste categorii) cât și empiric (breakdown pe categorii) — fals pozitiv închis prin verificare, nu prin presupunere.

**Timeout mărit**: `backfill.yml`, `timeout-minutes: 60 → 300` — durata estimată pentru 51.046 scrieri individuale la ~0,19s/rând observat empiric (din log-urile Fazelor 2b/2c) e ~2,7 ore.

**Rebuild**: declanșat `backfill.yml` (`dry_run=false`, `retrain_ml=false` — reantrenarea ML rămâne, deliberat, o decizie separată, niciodată bundle-uită tacit într-un fix de date, per „Filosofia proiectului" din `CLAUDE.md`).

**Rezultat rulare 1** (`run 32573933801`, ~2h53min): `conclusion: failure` la nivel de job — investigat imediat, nu tratat ca eșec catastrofal. Log-ul propriu al scriptului arată aproape succes total: „Procesate: 51041, Erori: 5" — `conclusion: failure` reflectă doar `errors > 0` din exit code, nu o oprire prematură. Descărcarea log-ului brut prin `curl` a fost blocată de proxy-ul mediului (403, aceeași clasă de blocaj notată anterior pentru artefacte GitHub) — s-a pivotat pe interogare directă în bază, nu pe presupunere. Interogare directă a găsit **6** rânduri încă `NULL`, nu 5 cât raporta propriul contor al scriptului — discrepanța investigată, nu ignorată: id=126780 (`flashscore_zc0VjBZF`, `kickoff_date=2026-08-22T11:30:00`) are un tipar temporal consistent cu un meci inserat concurent de un alt proces de sincronizare, chiar în fereastra de execuție a rulării — deci niciodată încercat de rebuild (fără eroare logată), spre deosebire de un rând încercat-și-eșuat (cu eroare logată). Explicație plauzibilă, nu confirmată direct — s-a preferat o reluare empirică, idempotentă, în locul unei presupuneri.

**Rezultat rulare 2 — reluare** (`run 32582575394`, 40,4s, `conclusion: success`): mecanismul idempotent (gating NULL-only) a procesat doar rândurile încă incomplete. Log: „Procesate: 6, Erori: 0". Verificat direct în bază, pe toate cele 6 id-uri anterior eșuate: toate cu `home_elo`/`away_elo`/`home_elo_after`/`away_elo_after` complet populate, `backfill_done: true`.

**Verificare finală pe întregul corpus** (nu doar pe cele 6 rânduri spot-verificate): `SELECT count(*) WHERE superseded_by IS NULL AND actual_result IS NOT NULL AND (<oricare din ELO/formă/H2H> IS NULL OR backfill_done IS NOT TRUE)` → **0**. Corpusul a crescut între timp la 51.047 (un meci nou finalizat după crearea backup-ului) — și acel rând suplimentar e de asemenea complet, populat pe altă cale (sincronizarea zilnică live), nu prin rebuild — consistent, nu o anomalie.

**Măsurătoare de închidere a buclei** (`scripts/measure_elo_divergence.py`, strict read-only, aceeași unealtă care a motivat decizia inițială de rebuild): rulat înainte (`run 32558948226`, 2026-08-22 07:12, PRE-rebuild) și după (`run 32582899754`, 2026-08-22 15:51, POST-rebuild), rezultatele comparate direct:

| Metrică | ÎNAINTE de rebuild | DUPĂ rebuild |
|---|---|---|
| Meciuri în replay | 53.872 | 51.047 (scădere așteptată — reconcilierea de identitate, Faza 2c, a scos duplicatele din replay) |
| ELO pre-meci identic (persistat = recalculat) | 66,4% | **100,0%** |
| ELO pre-meci divergență ≥ 50 puncte | 1,1% (1.225 valori) | **0** |
| ELO pre-meci, divergență maximă | 641 puncte | **0** |
| ELO post-meci identic | 66,2% | **100,0%** |
| Echipe cu ELO servit LIVE corect | 70,9% (856/1.207) | **100,0% (1.045/1.045)** |
| Divergență maximă servită azi | 115 puncte (Liverpool FC (ENG)) | **0** |

Confirmă, măsurat nu presupus, că rebuild-ul a rezolvat exact problema care l-a motivat: zero divergență reziduală, pe orice metrică urmărită, pe întregul corpus recalculat.

**Suită de teste**: `pytest tests/` — **2.560 passed, 2 skipped**, verde, rulată după rebuild (nicio regresie introdusă de reset+replay).

**Backup — decizie de retenție (2026-08-23)**: `match_history_backfill_backup_20260822` verificat izolat — 9,77 MB, 51.046 rânduri, niciun cod din repo nu-l referențiază (`grep` exhaustiv, doar acest document îl menționează). Proprietarul produsului a decis explicit: **păstrare 30 de zile de la rebuild, cu revizuire la ~2026-09-21** (nu ștergere imediată, nu păstrare pe termen nelimitat fără termen) — programat un reminder separat pentru acea dată. La revizuire, decizia se ia din nou explicit (ștergere sau prelungire), nu automat.

## Referințe

- ADR-036 / D3.5 — Canonical Feature Ownership
- ADR-059 — Reconcilierea identității este o operație de identitate, nu de date
- `scripts/audit_penalty_shootout_rows.py` — auditul care a produs corpusul Fazei 1
- `scripts/correct_penalty_shootout_scores.py` — execuția Fazei 1
- `scripts/analyze_d2_vocabulary_drift.py`, `scripts/detect_identity_alias_candidates.py` — pregătirea Fazei 2 (neexecutată)
- `scripts/measure_elo_divergence.py` — măsurătoarea care motivează Faza 3, rulată PRE (`run 32558948226`) și POST (`run 32582899754`) rebuild pentru închiderea buclei
