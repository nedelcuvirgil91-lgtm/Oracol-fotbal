# Architecture Audit — Independent Verification (Code First)

**Rol asumat**: auditor extern, fără încredere implicită în documentație/ADR-uri/rapoarte anterioare. Fiecare afirmație de mai jos e verificată direct în cod (fișier + linie), nu citată din documente. Documentele (ADR-uri, rapoarte) sunt tratate ca intenție arhitecturală, nu ca dovadă.

**Legendă**: ✅ Confirmat din cod · ⚠️ Parțial confirmat · ❌ Infirmat · 📌 Neconfirmabil

---

## 1. Integritatea arhitecturii

### 1.1 Cod duplicat — ELO, categoria cea mai gravă găsită

**✅ Confirmat.** `sync/calculate_elo.py` (întregul fișier, 178 linii) e o **a doua implementare completă, independentă**, a algoritmului Elo — `_expected_score()` (:53-55), `_k_factor()` (:58-62), `calculate_elo_for_league()` (:65-126) reimplementează aproape identic `ELOTracker` din `sync/backfill_features.py` (aceleași constante `INITIAL_ELO=1500`, `HOME_ADVANTAGE=50`, `K_FACTOR_BASE=32`, `K_FACTOR_NEW=40`), dar **fără formula MOV** — `calculate_elo_for_league()` (:92-123) citește doar `result`, niciodată `actual_home_goals`/`actual_away_goals`. De la ADR-022, cele două implementări au **divergat**: `ELOTracker.process_match()` (`sync/backfill_features.py:283-336`) aplică multiplicatorul V2_damped, `calculate_elo_for_league()` nu.

**✅ Confirmat — cod mort din perspectiva consumului, dar ACTIV din perspectiva execuției.** `sync/run_daily.py:199-200` apelează necondiționat `recalculate_all_elo()` la fiecare rulare zilnică (Pasul 2/6, înainte de `run_backfill()` de la Pasul 3/6, linia 227-228). Rezultatele se scriu în tabela Supabase `elo_ratings` (`database/queries.py:284`, `upsert_elo_ratings()`). Am verificat exhaustiv: **`get_elo_ratings()`** (`database/queries.py:294-309`, singura funcție care face `SELECT` pe tabela `elo_ratings`) **nu e apelată nicăieri altundeva în tot codul** (`grep` complet, zero rezultate). Concluzie: `sync/calculate_elo.py` rulează zilnic, consumă timp real de execuție și cote API/DB, scrie o tabelă Supabase reală — dar **nimic nu citește vreodată acea tabelă**. E simultan (a) muncă irosită zilnic și (b) o sursă latentă de confuzie: dacă cineva conectează vreodată `get_elo_ratings()` la UI/altă componentă, va reintroduce silențios formula categorială veche, paralel cu `match_history.home_elo` (care e V2_damped).

**✅ Confirmat — a treia sursă ELO, tot write-only.** `elo_history` (populată o singură dată, import istoric, `sync/import_historical.py:619-740`, `upsert_elo_history_bulk` la `database/queries.py:317-341`) — verificat, zero `.select()` pe această tabelă în tot codul. Deja semnalat parțial în roadmap (P4), dar re-confirmat aici direct din cod, nu citat.

**Verdict 1.1**: 3 surse de adevăr ELO paralele în Supabase (`match_history.home_elo` — reală, V2_damped; `elo_ratings` — zilnică, categorială, moartă la citire; `elo_history` — istorică, moartă la citire). Risc real: **niciunul** dintre cele două tabele moarte nu declanșează vreo eroare — nimeni nu va observa divergența până când cineva le conectează.

### 1.2 `backfill_done` — flag inconsistent, deja parțial auto-documentat ca atare

**⚠️ Parțial confirmat, severitate joasă.** `update_match_features()` (`sync/backfill_features.py:170-183`) setează necondiționat `"backfill_done": True` la fiecare UPDATE, chiar și când `features` e un **subset strict** al coloanelor lipsă (linia 954 a codului: `features = {col: computed[col] for col in missing if computed[col] is not None}` — coloanele opționale rămase `None` din motive legitime, Regula #8, sunt excluse din payload). Deci un rând poate ajunge `backfill_done=True` cu unele din cele 18 `FEATURE_COLUMNS` încă `NULL`. **Nu e un bug funcțional** — verificat: nimic din pipeline-ul real nu se bazează pe `backfill_done` pentru gating; `already_done`/`to_process` (`run_backfill()`, linia 867) folosesc direct `_missing_feature_columns()`, nu flag-ul. Codul însuși recunoaște asta explicit (comentariu, linia 864-866: *"Completitudinea reală se verifică per-coloană... nu prin flag-ul backfill_done — acesta poate fi inexact"*). `sync/sync_results.py:408` are un comentariu învechit ("Backfill doar pentru meciurile recent actualizate (backfill_done=False)") care **nu descrie codul real** de la linia 409 (`run_backfill(batch_size=50)` — apel global, fără niciun filtru pe `backfill_done`). Comentariu fals, nu bug.

### 1.3 Fallback-uri — verificate, toate justificate, niciunul mort

**✅ Confirmat.** `ELO_RATINGS_FALLBACK` (`mappings.py`) — folosit activ în `oracle_api._fetch_elo_ratings()` (linia 862-863, 882, 887-888) ca fallback la eșec scraping — cod viu, funcțional. `avg_sot = real_sot if real_sot is not None else avg_gf * 0.45` (`sync/backfill_features.py:743`) — fallback sintetic activ, folosit când `ShotsTracker` nu are încă istoric real. Ambele justificate, niciunul redundant.

### 1.4 Coupling — Learning Core vs. producție, graniță respectată

**✅ Confirmat.** `ml_predictor._record_training_run()` (:49-84) importă `learning_core.champion_comparison`/`learning_core.storage`/`learning_core.model_registry` — dependință **într-un singur sens** (producție → Learning Core, pentru logging), niciodată invers. Verificat: `learning_core/` nu importă nimic din `ml_predictor.py`/`oracle_engine.py`. Respectă Regula #10 (nicio dependință „în sus").

---

## 2. ELO — V2_damped

**✅ Confirmat.** Implementare: `MOV_C=4.4`, `MOV_D=0.0005` (`sync/backfill_features.py:262-263`), `_mov_multiplier()` (:266-273), aplicat în `ELOTracker.process_match()` (:283-336, semnătura nouă cere `home_goals`/`away_goals`).

**✅ Confirmat — toate call-site-urile reale actualizate.** Singurele 2 locuri care apelează `ELOTracker.process_match()`: `sync/backfill_features.py:959` (`elo_tracker.process_match(home, away, hg, ag, result)`) și `sync/bootstrap_league_learning.py:362` (`elo_tracker.process_match(home, away, home_goals, away_goals, result_code)`). Ambele confirmate cu semnătura nouă (5 argumente).

**❌ Infirmat — NU e adevărat că formula veche nu mai e folosită nicăieri.** Vezi §1.1: `sync/calculate_elo.py` implementează formula categorială veche într-o clasă separată, ne-legată de `ELOTracker`, și rulează zilnic prin `run_daily.py`. Din perspectiva strictă a întrebării „există vreun loc unde vechea formulă mai e folosită?" — **da**, dar scrie într-o tabelă (`elo_ratings`) fără niciun consumator, deci **fără impact funcțional** asupra ML sau servirii live.

**✅ Confirmat — live serving neatins.** `oracle_engine._build_profile()` (:633) → `self.api.get_elo_rating(canonical)` → `oracle_api._fetch_elo_ratings()` (:855-888) citește din scraping extern (`ELO_URL`) sau `ELO_RATINGS_FALLBACK`, cache local (`self._cget("elo_ratings")` — **cheie de cache locală, NU tabela Supabase `elo_ratings`**, coincidență de nume, verificată separat prin citirea codului cache). Zero legătură cu `ELOTracker` sau `match_history.home_elo`.

---

## 3. Writer Protection

**✅ Confirmat — mecanism corect.** `_missing_feature_columns()` (`sync/backfill_features.py:110-113`) folosește `is None` (nu falsy-check) — o valoare legitimă `0` (ex. `h2h_meetings=0`) nu e tratată greșit ca „lipsă". `FEATURE_COLUMNS` (18 coloane, :87-107) e sursa unică pentru `SELECT` (`fetch_all_matches()`, :137-143, construiește dinamic `+ ",".join(FEATURE_COLUMNS)` — **niciun risc de SELECT învechit** care ar putea face o coloană reală să pară „lipsă").

**✅ Confirmat — payload-ul de scriere exclude explicit `None`.** `features = {col: computed[col] for col in missing if computed[col] is not None}` — nu se scrie niciodată `None` peste o valoare deja `NULL`, evitând UPDATE-uri redundante infinite (comentat corect la linia 949-953).

**❌ Infirmat — nu există niciun loc unde se poate scrie accidental peste date existente.** Verificat exhaustiv: `update_match_features()` primește DOAR `features` (subsetul `missing`-and-`not None`), nu întregul rând recalculat — chiar dacă `computed` conține valori pentru toate 18 coloane (recalculate mereu, indiferent de completitudine, linia 894-913 vechi/929-948 actuale), doar subsetul filtrat ajunge în payload-ul de UPDATE. Nu există cale de cod prin care o valoare deja populată să fie inclusă în payload.

**⚠️ Bug logic minor, severitate joasă** — vezi §1.2 (`backfill_done` inconsistent, fără impact funcțional).

---

## 4. Tracker-e — consistență post-consolidare

Toate 6 verificate direct în `sync/backfill_features.py`:

| Tracker | Cheie | Linie | Status post-P3.5 |
|---|---|---|---|
| `ELOTracker` | `dict[str, float]`, nume echipă | :224-226 | ✅ Confirmat — cheiat pe string simplu, corect după consolidare (0 nume brute rămase, verificat live în §5) |
| `FormTracker` | `dict[str, list]`, nume echipă | :274-277 | ✅ Confirmat — idem |
| `H2HTracker` | `dict[tuple, list]`, **pereche** `(min, max)` | :476-478 | ✅ Confirmat — singurul cheiat pe 2 string-uri; `get_h2h_before()` (:493-501) derivă orientarea din numele curente la apel, nu din ordinea cheii — corect, verificat |
| `ShotCountTracker` | `dict[str, list]`, nume echipă | :407-409 | ✅ Confirmat |
| `CornerCardTracker` | 2× `dict[str, list]`, nume echipă | :436-439 | ✅ Confirmat |
| `FoulsTracker` | `dict[str, list]`, nume echipă | :372-374 | ✅ Confirmat |

**✅ Confirmat — niciun tracker nu mai poate fragmenta istoricul EXISTENT** (verificat live pe Supabase, `SELECT COUNT(*) WHERE home_team/away_team IN (176 nume brute)` = 0, măsurat în această sesiune).

**⚠️ Parțial confirmat — risc de fragmentare VIITOARE, nu de istoric.** Toți cei 6 tracker-i depind 100% de faptul că `home_team`/`away_team` sunt deja canonice la citire (`fetch_all_matches()`). Asta ține doar dacă **toate** punctele de scriere normalizează înainte de insert. Verificat (§ mai jos, secțiunea 5): 3 funnel-uri confirmate normalizate (`database.queries._normalize_team_fields()`, `supabase_client.upsert_match_history()`, `sync/sync_results.py` la extragere). **Nu am putut verifica exhaustiv fiecare cale de scriere din `services/*.py`** (`odds_backfill_service.py`, `match_stats_backfill_service.py` fac `.update()` pe rânduri existente prin `id`, nu par să atingă `home_team`/`away_team` — verificat parțial, nu linie cu linie pentru fiecare payload). 📌 Neconfirmabil complet fără citire exhaustivă a fiecărui payload de UPDATE din `services/`.

---

## 5. Team normalization

**✅ Confirmat.** 3 funnel-uri de scriere normalizate: `database/queries._normalize_team_fields()` (:41-59, apelat la :73 și :112), `supabase_client.py:272-274` (payload normalizat înainte de upsert la :275), `sync/sync_results.py:245-246` (normalizare la extragere, nu doar la scriere).

**✅ Confirmat — 0 surse directe de scriere care ocolesc funnel-urile.** `sync/sources/football_data.py`, `kaggle.py`, `openfootball.py`, `football_data_co_uk.py` — verificat, niciunul nu apelează `.insert()`/`.upsert()`/`table("match_history")` direct; toate returnează date către apelanți care trec prin funnel-urile de mai sus.

**✅ Confirmat — 0 aliasuri lipsă rămase.** Cele 2 excepții găsite în această sesiune (`Colon Santa FE`→`Colon Santa Fe`, `FENERBAHCE`→`Fenerbahce`) au fost adăugate în `TEAM_ALIASES` (`mappings.py`, secțiunea „Champions League / Europa League"), verificat direct: `normalize_team_name('Colon Santa FE')` → `'Colon Santa Fe'`, `normalize_team_name('FENERBAHCE')` → `'Fenerbahce'` (testat, `tests/test_mappings.py` + verificare manuală în această sesiune).

**📌 Neconfirmabil complet — aliasuri redundante.** Nu am rulat un scan sistematic nou (dedup pe `ALIAS_TO_CANONICAL`) în această sesiune pentru a găsi eventuale intrări duplicate/suprapuse în `TEAM_ALIASES` — auditul din P3.5 a raportat „zero clustere noi" pe 729 nume rămase, dar acela era un raport, nu o re-verificare directă acum. Recomand un scan dedicat, separat, dacă se dorește certitudine completă.

**✅ Confirmat — risc de fragmentare viitoare redus, nu eliminat.** Vezi §4 — depinde de completitudinea funnel-urilor, nu de `normalize_team_name()` însuși (funcția e corectă, verificată).

---

## 6. ML — feature-uri calculate vs. folosite vs. populate

**✅ Confirmat — toate cele 18 coloane backfill sunt consumate.** `ml_predictor.FEATURE_COLUMNS` (14 intrări, `ml_predictor.py:95-116`) — 10 reutilizate direct (`home/away_elo`, `home/away_form_score`, `home/away_offensive_rating`, `home/away_defensive_rating`, `h2h_modifier`, `h2h_meetings`), 4 derivate (`corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance`) din restul de 8 coloane brute (`*_avg_recent`) — verificat în `_fetch_training_dataframe()` (:194-215). Nicio coloană din cele 18 nu e „calculată dar niciodată folosită".

**✅ Confirmat — 6 chei calculate în `_build_ml_features()` dar NU în `FEATURE_COLUMNS`** (`oracle_engine.py:1013-1014, 1045-1048`: `home_xg_pred`, `away_xg_pred`, `weather_penalty`, `mc_prob_home`, `mc_prob_draw`, `mc_prob_away`) — comentariul din `ml_predictor.py:87-93` confirmă explicit: eliminate din antrenare (permutation importance 0.0000, 100% goale în `match_history` istoric), dar **păstrate intenționat** în dict-ul live pentru alte scopuri (explainability/UI) — nu e cod mort, e separare deliberată input-ML vs. payload-afișare.

**✅ Confirmat — zero drift train/inference la nivel de chei.** `MLPredictorEngine.predict()` (:428-437) filtrează explicit prin `self.feature_names` (=`FEATURE_COLUMNS`), ignorând cheile extra din `_build_ml_features()`. Toate cele 14 `FEATURE_COLUMNS` sunt prezente în dict-ul live (verificat 1:1). Niciun mismatch găsit.

**⚠️ Parțial confirmat — populare inegală, deja documentată, nu o eroare nouă.** `home_shot_avg_recent`/`away_shot_avg_recent` (ShotCountTracker) au rată de populare globală ~17% (măsurată direct pe producție în această sesiune, P3.5) — legitim, Regula #8, dependent de acoperirea reală de statistici pe ligi/sezoane vechi, nu un bug.

---

## 7. Roadmap — coerență

**✅ Confirmat — inconsistență introdusă chiar în această sesiune, nefixată încă.** `ML_EVOLUTION_ROADMAP.md:39`: `| P4 | ELO Trend | ... | Planned (după decizia de implementare P3 Revalidation) |` — text scris **înainte** de activarea V2_damped; **decizia s-a luat deja** (Accepted, implementat, activat, verificat, benchmark-uit) — linia e acum stale, ar trebui reformulată (ex. „Planned — precondiție îndeplinită, `elo_history` trebuie repopulat pe formula nouă înainte de a fi util pentru P4").

**⚠️ Parțial confirmat — P7.2 marcat „condiționat, poate începe la aprobare explicită" — vezi §8, verdictul se schimbă semnificativ.**

**📌 Neconfirmabil fără re-citire completă** dacă P5/P6/P8/P9/P10 rămân coerente — nu au fost atinse de niciunul din milestone-urile acestei sesiuni, deci status-ul lor (`Planned`/`Idea`) rămâne presupus valid prin lipsă de contradicție, nu re-verificat activ.

---

## 8. P7.2 (`sot_dominance`) — reevaluare, nu presupunere

**✅ Confirmat — infrastructura NU există încă**, spre deosebire de P7.1. `ShotsTracker` (`sync/backfill_features.py:344-361`) calculează `avg_shots_on_target` **doar în memorie**, consumat exclusiv de `team_pre_match_rating()` (:742) pentru blend-ul de `offensive_rating`/`defensive_rating` — **nu există nicio coloană `home_sot_avg_recent`/`away_sot_avg_recent`** în `FEATURE_COLUMNS` sau în schema `match_history` (verificat, zero rezultate la căutare). Spre deosebire de P7.1 (care a reutilizat coloane deja existente, `home_shots`/`away_shots` brute), P7.2 ar necesita: (a) coloane noi, (b) o rulare de backfill nouă pe toate ~53.409 rânduri, (c) abia apoi ablația. Cost de implementare mai mare decât P7.1, contrar impresiei că ar fi „doar o repetare".

**✅ Confirmat — risc de redundanță cu `offensive_rating`, cuantificabil direct din cod.** `feature_engine.py:191` — `shots_ot_weight: 0.30` — SOT e deja blendat cu pondere 30% în `home/away_offensive_rating`, feature marcat **CRITICAL** (ADR-020). `sot_dominance` ar testa un semnal parțial deja prezent într-un feature critic deja folosit.

**✅ Confirmat — risc de redundanță cu `shot_dominance` (deja Accepted).** SOT e prin definiție un subset al șuturilor totale (`shot_dominance`, deja `Accepted`, ADR-021) — nicio măsurătoare de corelație SOT-vs-total-shots nu a fost făcută vreodată în proiect (verificat — nu există niciun script/raport de audit al acestei corelații specifice în `docs/03_ENGINE/`). Riscul e arhitectural plauzibil (demonstrat prin structura de cod: ambele derivă din același eveniment de joc — un șut), dar magnitudinea exactă a suprapunerii **rămâne neconfirmată empiric** — 📌 necesită un audit de corelație dedicat înainte de decizie, nu presupunere.

**Verdict P7.2**: NU „mai are sens ca înainte" — cost de implementare mai mare decât se credea (schema nouă, nu doar flag), plus 2 căi independente de redundanță (offensive_rating CRITICAL + shot_dominance Accepted), niciuna testată empiric. Recomand: dacă se face, precedat obligatoriu de un audit rapid de corelație (SOT vs. total shots, pe date deja existente în `home_shots_on_target`/`home_shots`, fără backfill nou) — ieftin, ar putea închide P7.2 fără nicio implementare de schema.

---

## 9. Technical Debt

| Item | Severitate | Dovadă |
|---|---|---|
| `sync/calculate_elo.py` — formulă categorială moartă la citire, rulează zilnic, scrie o tabelă nefolosită | **High** | §1.1, §2 — cost real de execuție zilnic, risc de confuzie/regresie silențioasă dacă e conectată vreodată |
| `elo_history` — tabelă write-only, date neexploatate | **Medium** | §1.1, precondiție semnalată deja pentru P4, acum și mai relevantă (V2_damped activ, `elo_history` conține doar formula veche categorială din import istoric) |
| `backfill_done` — flag inconsistent, comentariu fals în `sync_results.py:408` | **Low** | §1.2 — fără impact funcțional, dar generează confuzie la citirea codului |
| P7.2 — scop de implementare subestimat în roadmap (pare „doar o repetare a P7.1", de fapt cere schema nouă) | **Medium** | §8 |
| Roadmap — linia P4 stale (referă o decizie deja luată ca „viitoare") | **Low** | §7 |
| Aliasuri redundante în `TEAM_ALIASES` — neverificat exhaustiv în această sesiune | **Low** (risc, nu confirmat) | §5 — necesită scan dedicat pentru certitudine |
| Verificare completă a tuturor payload-urilor de `.update()` din `services/*.py` pentru risc de scriere `home_team`/`away_team` nenormalizat | **Low** (risc, nu confirmat) | §4, §5 — verificare parțială, nu linie cu linie |

**Nimic clasificat Critical** — nu am găsit nicio cale de cod care corupe date, suprascrie greșit, sau produce rezultate incorecte silențios în fluxul activ (live serving sau antrenare ML).

---

## 10. Următorii pași — propunere, ignorând roadmap-ul existent

Pe baza exclusiv a codului verificat mai sus:

1. **Curățenie ELO (1-2 ore, risc minim)** — elimină sau repară `sync/calculate_elo.py`. De ce primul: e singurul lucru găsit în acest audit cu **cost real recurent** (rulează zilnic) și **zero valoare** (nimeni nu-l citește) — cel mai ieftin câștig din tot auditul, elimină și un risc de regresie silențioasă viitoare.
2. **Audit rapid de corelație SOT vs. shots totale** (câteva ore, pe date deja existente, zero schema nouă) — răspunde definitiv la P7.2 înainte de orice decizie de implementare. De ce acum: e ieftin și ar putea închide P7.2 permanent, evitând un cost de implementare (schema + backfill) pentru un feature probabil redundant.
3. **Repopulare `elo_history` pe formula V2_damped** (dacă P4 rămâne prioritate) — precondiție tehnică reală pentru P4, nesemnalată ca atare în roadmap azi (§7).
4. **Abia apoi**: P4/P5/P6/P8/finishing_efficiency/defensive_efficiency, în ordinea deja discutată — niciun cod verificat în acest audit contrazice fezabilitatea lor, dar niciunul nu a fost reexaminat activ (📌 neconfirmabil în acest audit, în afara scopului cerut).

**De ce schimb ordinea**: roadmap-ul actual nu menționează deloc `calculate_elo.py` (nu apărea ca „debt" undeva anterior în proiect, verificat) — e o descoperire nouă a acestui audit, cu cost recurent real, deci prioritate mai mare decât orice feature nou. Auditul de corelație SOT e ieftin și poate elimina un cost de implementare mai mare decât cel presupus (schema nouă) — merită făcut înainte de a decide dacă P7.2 pornește.

---

## Top 10 riscuri rămase

1. `sync/calculate_elo.py` — formulă veche, rulează zilnic, scrie date moarte (§1.1) — **High**.
2. Reintroducere silențioasă a formulei categoriale dacă cineva conectează vreodată `get_elo_ratings()` (§1.1).
3. P7.2 subestimat ca „ușor" în roadmap — cost real ascuns (schema nouă) (§8).
4. Redundanță netestată SOT vs. `shot_dominance`/`offensive_rating` — decizie fără dovadă empirică dacă P7.2 pornește necontrolat (§8).
5. Aliasuri redundante neverificate exhaustiv — risc mic, dar necuantificat (§5).
6. Verificare incompletă a payload-urilor `.update()` din `services/*.py` pentru risc de scriere nenormalizată (§4).
7. `elo_history` conține acum date pe formula veche, potențial confuz dacă P4 pornește fără repopulare (§9).
8. `backfill_done`/comentarii false — risc de confuzie pentru viitori dezvoltatori, nu de date (§1.2).
9. Linia P4 din roadmap, stale — risc mic de decizie greșită dacă cineva o citește fără context (§7).
10. Nicio verificare automată (test) care ar fi prins duplicarea ELO — `tests/test_elo_mov.py` testează doar `ELOTracker`, nu verifică deloc că `calculate_elo.py` a rămas nesincronizat.

## Top 10 oportunități de îmbunătățire

1. Șterge sau repară `sync/calculate_elo.py` (§10.1).
2. Audit de corelație SOT — ieftin, poate închide P7.2 definitiv (§10.2).
3. Corectează comentariul fals din `sync/sync_results.py:408`.
4. Actualizează linia P4 din roadmap (§7).
5. Redenumește/reconsideră `backfill_done` — fie îl faci corect (calculat din `_missing_feature_columns`), fie îl elimini.
6. Scan dedicat de aliasuri redundante în `TEAM_ALIASES`.
7. Test automat care verifică că `sync/calculate_elo.py` și `ELOTracker` NU divergă (sau, mai bine, elimină duplicarea complet).
8. Documentează explicit (cod, nu doar text) că `elo_ratings`/`elo_history` sunt tabele istorice/inactive, cu un comentariu de headers care avertizează viitori dezvoltatori.
9. Verificare exhaustivă (nu parțială) a tuturor payload-urilor `.update()` din `services/*.py`.
10. Considerați consolidarea `ELOTracker`/`calculate_elo.calculate_elo_for_league` într-o singură sursă de adevăr (dacă al doilea chiar mai e necesar pentru ceva neconfirmat aici).

---

## Verdict arhitectural general

**7/10** — arhitectura de bază (Writer Protection, tracker-e, normalizare, separare live/training) e solidă și verificată riguros de cod, nu doar de documentație. Scăderea de la un scor mai mare vine strict din §1.1 (duplicarea ELO, cost real recurent, nedescoperită până acum) și din scopul subestimat al P7.2.

| Dimensiune | Scor |
|---|---:|
| Arhitectură | 7/10 |
| Mentenabilitate | 6/10 (duplicarea ELO + flag-uri inconsistente reduc claritatea) |
| Consistență | 7/10 (o singură sursă reală de adevăr pentru date active; 2 surse moarte, nesincronizate) |
| Scalabilitate | 8/10 (Writer Protection + gating per-coloană se scalează bine, dovedit pe 53.409+ rânduri) |
| Risc de regresie | 6/10 (riscul real e tăcut — nimic nu eșuează vizibil dacă `calculate_elo.py` rămâne nesincronizat la nesfârșit) |
