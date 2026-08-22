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
| Redenumire D2+D3 (rânduri deja scrise) | recalculat după extinderea vocabularului — vezi Faza 2b | `home_team`, `away_team` în `match_history` | Neexecutat — următoarea etapă |
| Rebuild ELO | Toate rândurile cu `home_elo`/`away_elo`/`home_elo_after`/`away_elo_after` deja populate | cele 4 coloane ELO | Neexecutat — după unificarea vocabularului, ca să ruleze o singură dată pe serii curate |

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

## Referințe

- ADR-036 / D3.5 — Canonical Feature Ownership
- ADR-059 — Reconcilierea identității este o operație de identitate, nu de date
- `scripts/audit_penalty_shootout_rows.py` — auditul care a produs corpusul Fazei 1
- `scripts/correct_penalty_shootout_scores.py` — execuția Fazei 1
- `scripts/analyze_d2_vocabulary_drift.py`, `scripts/detect_identity_alias_candidates.py` — pregătirea Fazei 2 (neexecutată)
- `scripts/measure_elo_divergence.py` — măsurătoarea care motivează Faza 3 (neexecutată)
