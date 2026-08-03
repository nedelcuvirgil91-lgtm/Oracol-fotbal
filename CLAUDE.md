# CLAUDE.md — Football Oracle

Ghid de orientare pentru orice sesiune Claude Code care lucrează pe acest proiect. Scop: eliminarea nevoii de a redescoperi, de la zero, contextul arhitectural la fiecare sesiune nouă.

## Ce e proiectul

Football Oracle e o platformă personală de predicție și analiză a pariurilor pe fotbal — Elo, Poisson, Monte Carlo, blend XGBoost, de-vig, value betting. Repo privat, un singur dezvoltator + Claude Code. Stack: Python 3.11, Streamlit, Supabase (Postgres), GitHub Actions.

Disclaimer de proiect (nu al acestui document): instrument de analiză statistică personală, nu consultanță financiară.

## Current Implementation Status — Learning Core

**Sursa de adevăr actualizată e `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md`** (branch vs. `main`, ce rulează live, ce e activat prin flag-uri) — secțiunea de mai jos e un rezumat, nu duplică detaliile.

✔ Model Registry · LearningAlgorithm interface · XGBoost Adapter · ProductionChampion Adapter · Training Runner · CLI `train.py`
✔ Challenger Runner + Challenger FSM (ADR-016) · Promotion Engine (`promotion_service.py`) · Champion Manager (`model_champions`, doi scriitori: Promotion + Rollback) · Continuous Learning / Daily Scheduler integration (ADR-030, `continuous_learning.yml`)
✔ **Rollback Engine** (ADR-037, R1) — append-only, CAS-guarded
✔ **Champion Guardian** (ADR-037, R2) — evaluator read-only al sănătății campionului activ
✔ **Orchestrare Learning Core** (ADR-037, R3, R3.0-R3.7) — Faza D + execuție rollback cu țintă înghețată (Execution Contract) — **cod complet, testat, NEMERGE-UIT pe `main`** (vezi `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md` pentru planul de activare)

Not Implemented
- Auto-promovare/auto-rollback fără om în buclă (contrazice ADR-002; cere ADR dedicat de risc)
- Activarea ADR-037 în producție (R4 — separată deliberat de merge, vezi planul de deployment)

## Filosofia proiectului

**„Verificat, nu presupus."** Orice pretenție de îmbunătățire (feature nou, algoritm nou, ipoteză nouă) se demonstrează cu test de ablație pe date reale, nu se acceptă din intuiție — vezi `docs/03_ENGINE/REST_DAYS_VALIDATION.md` ca exemplu de rigoare: un feature cu fundament teoretic solid, respins explicit după ce testul măsurat n-a arătat câștig.

O stare necunoscută rămâne explicit „necunoscută"/„insuficiente date" — nu se aproximează niciodată (vezi ADR-001: `supported: "necunoscut"`, niciodată dedus dintr-o valoare lipsă).

Guvernanța (ADR-uri, documente Frozen, promovare manuală) e tratată ca avantaj pe termen lung, nu ca frână — costul de disciplină e acceptat conștient (vezi ADR-002, „Consecințe").

**Nu păstrăm buguri în cod doar pentru că produc rezultate bune** (regulă permanentă, adăugată 2026-08-03, precedent: EPIC ML Activation Pasul 8, „Oracle Insight" — dubla numărare `avg_goals_for`, `docs/03_ENGINE/ORACLE_INSIGHT_GOALS_WEIGHT.md`). Dacă un bug demonstrat matematic produce empiric o performanță mai bună pe backtest, nu se acceptă păstrarea lui — se identifică explicit informația predictivă utilă pe care o introduce (analiză cauzală, nu doar corelație), se documentează ca „Oracle Insight". **Dar bug fix-urile nu introduc schimbări de model**: orice modificare a parametrilor matematici ai Oracle (recalibrare de pondere, prag, cap) — chiar dacă rezolvă corect regresia cauzată de eliminarea bugului și e validată prin backtest — e tratată ca **experiment de calibrare separat**, cu propriul review și propria aprobare explicită, niciodată bundle-uit tacit în task-ul de fix. Un backtest favorabil nu e, singur, suficient pentru a schimba formula Oracle.

## Architectural North Star — 10 reguli care nu se încalcă niciodată

1. Producția nu e niciodată afectată de un experiment activ — shadow rămâne shadow până e dovedit, niciodată invers.
2. Promovarea unui model cere dovadă statistică simultană pe metrici multiple — niciodată o singură metrică, niciodată intuiție.
3. Niciun flag nou nu pornește implicit activ.
4. Niciun document Frozen nu se editează direct — doar printr-un ADR nou.
5. Orice schimbare de contract (model de date, responsabilitate, flux) trece printr-un ADR — nu prin editare tăcută.
6. Nicio scriere directă pe date live (Supabase producție) fără confirmare explicită, vizibilă, a exact ce se scrie.
7. Zero scurgere temporală în orice proces de învățare — disciplina walk-forward, fără excepție, indiferent de algoritm.
8. Nicio stare necunoscută nu se aproximează — rămâne explicit „necunoscut"/„insuficiente date".
9. Orice rezultat — predicție, evaluare, promovare — trebuie trasabil complet până la sursă.
10. Nicio dependință „în sus" între straturile arhitecturale — servirea live nu depinde niciodată de infrastructura de învățare.

## Viziune pe termen lung — Oracle și ML (constrângere permanentă, adăugată 2026-08-03)

Oracle rămâne motorul principal în prezent datorită performanței demonstrate (verificat prin benchmark, `docs/00_GOVERNANCE/ORACLE_VS_ML_REPORT.md`) — nu din inerție sau preferință.

**ML nu este un experiment abandonat și nu este un fallback.** Obiectivul proiectului e dezvoltarea unui sistem ML autonom care:

- învață continuu din istoricul complet;
- învață incremental din meciurile noi;
- își calibrează automat modelele;
- își monitorizează performanța;
- își generează propriile predicții, independente de Oracle;
- afișează permanent aceste predicții în UI;
- permite compararea Oracle vs. ML;
- poate deveni în timp predictorul principal, DACĂ dovezile statistice demonstrează superioritatea sa (North Star #2 — dovadă simultană pe metrici multiple, niciodată o singură metrică sau intuiție).

Această viziune fixează direcția pe termen lung a proiectului și previne „optimizarea" proiectului prin eliminarea ML — orice propunere viitoare de a simplifica arhitectura prin renunțarea la stratul ML trebuie evaluată explicit împotriva acestei viziuni, nu decisă tacit.

## Knowledge Map — rolul fiecărui modul

| Modul | Rol (o propoziție) | Depinde de | Consumat de |
|---|---|---|---|
| `oracle_api.py` | Strat unificat de acces la provideri externi (cote, meciuri, vreme, ELO), cu fallback între surse. | `key_manager.py`, `cache_manager.py`, `mappings.py` | `oracle_engine.py`, `sync/run_daily.py` |
| `oracle_engine.py` | Motorul de predicție — Poisson, Monte Carlo, blend ELO/ML, de-vig, value betting. | `oracle_api.py`, `feature_engine.py`, `ml_predictor.py`, `recalibration.py`, `shadow_testing.py`, `supabase_client.py`, `database/queries.py` | `app.py` |
| `ml_predictor.py` | Model XGBoost, antrenat pe `match_history`, walk-forward validation (expanding window). | `supabase_client.py` | `oracle_engine.py`, `sync/run_daily.py` |
| `recalibration.py` | Funcție pură de ajustare a ponderilor per ligă, fără I/O. | (niciuna) | `oracle_engine.py`, `sync/sync_results.py` |
| `shadow_testing.py` | Infrastructură generică de shadow testing + Statistics Engine, independentă de `oracle_engine.py`. | `supabase_client.py` | `oracle_engine.py` (gated), `sync/run_daily.py` |
| `feature_engine.py` | Calcul formă, H2H, ELO→multiplicatori of./def., calibrare xG, Poisson, ponderi per ligă, off/def rating — 8 din 9 funcții active. Excepție: `rest_days_modifier` rămâne neapelat, DELIBERAT (respins explicit prin test de ablație pe 53.409 meciuri reale, vezi `REST_DAYS_VALIDATION.md` — nicio îmbunătățire măsurabilă). | (date brute) | `oracle_engine.py`, `sync/backfill_features.py` |
| `mappings.py` | Sursă canonică unică pentru ligi/provideri (`LEAGUE_PROVIDERS`, ADR-001). | (niciuna) | `oracle_api.py`, `sync/sync_results.py` |
| `supabase_client.py` | Client Supabase + query-uri de nivel înalt (weights, config, ML status). | Supabase (proiect `Prediction`) | `oracle_engine.py`, `ml_predictor.py`, `sync/*` |
| `database/queries.py` | Interogări structurate pentru match_history, ELO canonic (D2), H2H canonic (D3), sync status. | Supabase | `sync/*`, `oracle_engine.py` (servire live — ELO/H2H Database-First) |
| `services/odds_persistence_service.py` | Persistare istorică cote (opening/closing) — **Frozen**, ADR-005/006. | `database/migrations/001_odds_history.sql` | `sync/run_daily.py` |
| `cache_manager.py` / `key_manager.py` | Cache local (nivel 1) + quota API — nivel 2 (ADR-003) încă neimplementat. | (disc local) | `oracle_api.py` |
| `football_providers.py` / `injury_manager.py` | Adaptoare API-Football (accidentări, antrenori). | `key_manager.py` | `oracle_engine.py` |
| `sync/run_daily.py` | Orchestrator zilnic — sincronizare, ELO, shadow eval, odds, ML retrain (ordinea din ADR-004). | Toate modulele `sync/` | GitHub Actions (`daily.yml`) |
| `app.py` | UI Streamlit — predicții, config, League Learning, diagnostics. | `oracle_engine.py`, `supabase_client.py` | Utilizator final |
| `config.json` / `weights.json` | Configurare globală + ponderi per ligă, aditiv, compatibilitate păstrată. | (fișier local / `model_config` Supabase) | `oracle_engine.py`, `recalibration.py` |

**Notă de tranziție (ADR-023 Phase 6 / ADR-035 D2, finalizată 2026-07-20)**: `oracle_engine._build_profile()` citește ELO-ul de club PRIMAR din `match_history.home_elo_after`/`away_elo_after` (Canonical Live ELO Snapshot) prin `database.queries.get_latest_team_elo()` — global per club, fără filtru de ligă (ELOTracker urmărește ratingul per echipă, nu per competiție). `oracle_api.get_elo_rating()` rămâne fallback, singura sursă reală pentru echipele fără meciuri de club sincronizate (tipic: naționale). Cleanup-ul sursei vechi (`_fetch_elo_ratings()`, `ELO_RATINGS_FALLBACK` dacă rămâne neapelat) rămâne programat pentru Phase 8 (ADR-023), neînceput.

**Notă de tranziție (ADR-035 D3 — H2H Database-First, Completed 2026-07-20)**: `oracle_engine._build_h2h()` citește H2H-ul PRIMAR din `match_history` prin `database.queries.get_h2h_from_history()` — confruntări directe BRUTE, globale per pereche de cluburi (fără filtru de ligă, consecvent cu ELO-ul D2), recalculate din `actual_result`/`actual_home_goals`/`actual_away_goals` (niciodată din coloanele precalculate `h2h_modifier`/`h2h_meetings`). Fluxul: DB (≥3 confruntări, `MIN_H2H_MEETINGS`) → FreeLF `get_h2h(event_id)` → Odds API scores → `H2HRecord.empty()`. Logica de recalcul e în `oracle_engine._h2h_record_from_history_rows()` (punct unic, garda AST); NU mai există o cale live care să citească H2H direct din provider fără să treacă întâi prin DB. `H2HTracker` (`sync/backfill_features.py`) rămâne scriitorul coloanelor precalculate pentru antrenarea ML, neatins. Cursa de scriere concurentă pe `FEATURE_COLUMNS` (`_save_prediction` vs. `run_backfill`, semantică `COALESCE`) e documentată ca task separat **D3.5 — Feature Canonicalization** (`docs/00_GOVERNANCE/D3.5-FEATURE_CANONICALIZATION_TASK.md`), neînceput.

## Disciplina ADR

- Orice schimbare de model de date/contract/responsabilitate de componentă = ADR nou, numerotat secvențial, format `Status/Context/Decizie/Consecințe` (vezi `architecture/ADR-001…004`, `docs/00_GOVERNANCE/ADR-005…006`).
- Detaliile de implementare (formatul unei erori, ora unui cron) NU necesită ADR — vezi `FROZEN_REGISTRY.md`, Change Policy.
- Motivație invalidă pentru un ADR: preferințe subiective, stil, „cum aș fi făcut eu".
- **Discovery Rule** (adăugată permanent, 2026-08-03, precedent: ADR-047, descoperirea `recalibration_log.new_dna_w` în timpul implementării): dacă în timpul implementării unui ADR deja aprobat e descoperit un contract nou, o migrare nouă, un tabel/coloană nouă sau o dependență care NU a fost identificată în ADR-ul aprobat — implementarea se oprește imediat, descoperirea e prezentată explicit proprietarului produsului, și acesta decide dintre: (a) rămâne în afara scopului, documentată ca „Out of Scope Discovery" în ADR-ul curent; (b) se extinde ADR-ul curent printr-un amendament explicit; (c) se creează un ADR nou, separat. **Nu se extinde niciodată scopul unui ADR aprobat „din mers", tacit, fără această decizie explicită.**

## Regulile pentru documentele Frozen

- Documentele listate în `docs/00_GOVERNANCE/FROZEN_REGISTRY.md` sunt imuabile fără ADR dedicat.
- **Gol cunoscut, activ**: `ARCHITECTURE.md`, `DATABASE_SPEC.md`, `PIPELINE_SPEC.md`, `ENGINE_SPEC.md`, `CONFIG_SPEC.md` sunt declarate Frozen în registru dar nu există fizic în acest repo — orice pretenție de conformitate cu ele e neverificabilă până se rezolvă acest gol de trasabilitate. Nu se inventează conținutul lor.
- `ODDS_PERSISTENCE_DESIGN.md` există și e Frozen — orice atingere trece prin ADR nou (regulă stabilită explicit de ADR-005).

## Regulile ML

- Walk-forward (expanding window) obligatoriu, zero scurgere temporală, indiferent de algoritm — vezi `ml_predictor._walk_forward_validate()`.
- `random_state` fixat explicit pentru orice antrenare.
- Feature nou în `FEATURE_COLUMNS` doar cu dovadă de ablație (nu presupunere) — precedent: 6 feature-uri deja eliminate prin permutation importance măsurată pe 53.409 meciuri reale.
- `MIN_SAMPLES_TO_TRAIN` respectat — sub prag, doar Poisson, niciodată ML forțat.

## Regulile bazelor de date (Supabase, proiect `Prediction`)

- Orice tabelă nouă: idempotentă la creare (`CREATE TABLE IF NOT EXISTS`), RLS activ, scriere doar prin `service_role` — vezi `database/migrations/001_odds_history.sql` ca precedent.
- Scriere atomică (o singură operație `INSERT ... ON CONFLICT`), niciodată check-then-act.
- **Canonical Feature Ownership (ADR-036 / D3.5, COMPLETED 2026-07-20)**: fiecare coloană canonică din `match_history` are un owner unic de scriere — `run_backfill` pentru `FEATURE_COLUMNS` (+ import pentru `home_elo`/`away_elo`), `sync_results` pentru `actual_*`, `_cache_prediction` doar pentru ieșirile de predicție. Prediction Engine NU scrie niciodată feature-uri ML sau rezultate; garda AST `tests/test_canonical_feature_ownership.py` impune asta. RPC `upsert_match_canonical` rămâne contract generic. Niciun cod nou nu scrie o coloană cu owner existent.
- **Proiectul Supabase conectat e producție reală, nu sandbox** — `execute_sql`/`apply_migration` scriu direct, fără preview automat. Nicio migrare fără să fi arătat utilizatorului SQL-ul exact înainte de rulare.

## Regulile pentru chei API și provideri externi (aprobate explicit, 2026-07-27; validate live prin migrarea API-Football, 2026-07-27)

Cheile API sunt tratate ca infrastructură critică — nu ca detalii de configurare, nu ca ceva ce se rotește sau se înlocuiește „din mers".

- **Niciun secret, cheie API, provider sau variabilă de mediu nu se șterge sau se înlocuiește fără un audit scris al utilizării** (tabel: Provider / Variabilă / Folosită? / Unde exact / Poate fi eliminată?) **și aprobarea explicită a proprietarului produsului.** Nicio „curățenie preventivă".
- **Regula 1 — proces obligatoriu de migrare a unei chei**, fără excepție, pas cu pas, fiecare pas aprobat separat:
  1. cheia nouă se adaugă ca secret **separat**, temporar (ex. `<PROVIDER>_KEY_NEW`) — niciodată suprascriind cheia activă;
  2. se validează autentificarea cu cheia nouă;
  3. se validează endpoint-urile relevante cu cheia nouă;
  4. se compară răspunsurile cu ce așteaptă implementarea existentă (parsere, forme de date, ID-uri);
  5. abia după validare completă se poate schimba providerul activ către cheia nouă;
  6. cheia veche rămâne disponibilă ca fallback până la aprobarea explicită a proprietarului produsului — **excepție documentată**: dacă cheia veche e deja suspendată/blocată de provider (caz real, API-Football, 2026-07-27), acest pas devine inaplicabil prin forța faptelor, nu se omite din neglijență — se notează explicit motivul în CHANGELOG;
  7. eliminarea cheii vechi se face doar după un audit separat, dedicat, nu ca parte a pasului 5.
- **Regula 2 — zero regresii funcționale**: nu e suficient ca o cheie/provider nouă „să răspundă". Trebuie demonstrat că produce aceleași date, aceleași ID-uri, aceleași mapping-uri, și că nu schimbă comportamentul Oracle Engine, Predictorului sau ML. Orice diferență găsită = cheia nouă NU devine activă.
- **Validarea unei chei noi se face printr-un POC izolat, temporar** (nu importă niciodată `key_manager.py` sau modulul providerului activ, nu citește niciodată variabila de mediu a cheii vechi, nu modifică workflow-uri existente, nu e importat de niciun cod de producție, rulează doar `workflow_dispatch` manual) — comparația structurală se face contra formei STATICE așteptate de parserul de producție (citată exact, cu linie sursă), nu contra unui al doilea apel live pe cheia veche. POC-ul se șterge din cod după închiderea migrării — dovada rămâne în istoricul rulărilor GitHub Actions + CHANGELOG, nu ca infrastructură vie permanentă.
- **Nu se presupune niciodată că o cheie/provider nou e „mai bun" doar pentru că e nou.** Sistemul funcțional existent rămâne activ până când cel nou dovedește, prin teste și audit, că îl poate înlocui fără regresii — regulă valabilă pentru orice provider extern, nu doar API-Football.

## Regulile testelor

- `pytest tests/` trebuie să rămână verde — 1576 de teste confirmate (2026-07-28, `pytest tests/ --collect-only -q`; numărul crește cu fiecare migrare Database-First), fără dependință de rețea.
- Orice schimbare în calea de predicție (`oracle_engine.py`) se verifică funcțional (rulare reală pe fixture-uri cunoscute), nu doar prin teste unitare.

## Regulile Champion vs. Challenger (Learning Core)

- Promovare doar din statusul `candidate_for_promotion`, doar dacă Brier + Log-loss + Accuracy sunt *simultan* semnificativ mai bune (vezi `shadow_testing.evaluate_experiment()`).
- Promovarea automată (concept `auto_promotion_enabled`, propus DOAR ca design în `docs/04_LEARNING_CORE/LEARNING_CORE_ARCHITECTURE.md` §3.4 — corectat 2026-08-03, EPIC ML Activation Pasul 5: nu există azi ca flag citit de niciun cod, confirmat prin grep exhaustiv, `docs/00_GOVERNANCE/ML_ENGINE_AUDIT.md` §11/§13) contrazice azi ADR-002 și necesită un ADR nou dedicat înainte de orice implementare — niciodată implicit pornită.
- Champion Manager mutabil exclusiv de Promotion Engine și Rollback Engine.
- Niciun Challenger nu servește predicții live.

## Regulile pentru Learning Core

- Straturile L0-L6 (Data Layer → Odds Persistence → Feature Engineering/Calibration → Registries → Learning process → Scheduling → Serving → Observability) — nicio dependință „în sus".
- Prediction Engine nu scrie niciodată în Experiment Registry, direct sau indirect.
- Oracle Engine nu antrenează niciodată modele.
- Orice model identificabil unic prin `(algorithm_family, algorithm_version, training_run_id, dataset_id)`.
- Orice rezultat trasabil complet, cu timestamp UTC.
- Documentele complete de arhitectură (Faza 1 — componente și flux; Faza 2 — contracte, dependency graph, invarianți) există în istoricul conversațiilor de proiect; se transcriu în `docs/` pe măsură ce Learning Core intră efectiv în implementare.

## Goluri cunoscute, active azi (nu ascunse, de tratat cu prioritate)

**Notă**: secțiunea a fost re-verificată prin citire directă de cod (Sprint 2, Etapa C — Data Quality, Pasul 4) — 3 intrări vechi s-au dovedit false (rezolvate între timp, fără actualizare aici) și au fost eliminate: cheile API hardcodate din `oracle_api.py` (eliminate la R4.1), recalibrarea necondiționată din `sync/sync_results.py` (gatată azi de `auto_recalibration_enabled`, verificat), Cache nivel 2/ADR-003 (implementat complet, `cache_manager.py` `get()`/`set()` citesc și scriu prin `supabase_client.get_cached_response()`/`set_cached_response()`).

- **R-Sync-6a, neînceput**: `freelf_form_adapter.py` reproduce fidel un bug preexistent — `get_freelf_standings()` nu copiază niciodată câmpul `"form"` din răspunsul brut FreeLF, deci `freelf_team_form_snapshot.form` e mereu gol. Confirmat prin citire de cod, nu presupus; verificarea payload-ului live rămâne task separat.
- **Cotă FreeLF/RapidAPI (`freelivefootball`) cronic epuizată** — confirmat live (Sprint 2, validare `sync_team_form_freelf`): endpoint `football-get-matches-by-date` cu zeci de eșecuri consecutive, `football-get-standing-all` niciodată reușit. Sync-ul rămâne activ în pipeline (degradare corectă via `RateLimitManager`), dar `freelf_team_form_snapshot` nu se populează până la recuperarea cotei sau schimbare de strategie de consum (deliberat neinvestigat încă, la cererea proprietarului produsului).
- **Descoperirea meciurilor (calea ESPN, `oracle_api.get_matches_for_week()`) nu populează `venue_city` pentru majoritatea meciurilor** — confirmat live (Sprint 2, validare `sync_weather_forecast`): din perechile (oraș, dată) identificate într-o rulare reală, majoritatea au fost excluse de `WeatherForecastAdapter.validate()` din lipsă de oraș. `weather_forecast_cache` se populează doar pentru meciurile unde ESPN întoarce efectiv orașul stadionului. Migrarea completă a descoperirii meciurilor la Supabase (R-Sync-7) ar putea rezolva asta ca efect secundar, dar rămâne în afara scopului actual.
- **Descoperirea meciurilor pentru calificările cupelor europene (Champions/Europa/Conference League) e structural incompletă** — confirmat live (audit Sprint 3, 2026-07-28, raportat de proprietarul produsului: UCL arăta 1 meci din 6 reale azi). Nicio sursă din cele 4 testate (ESPN raw scoreboard, TSDB `eventsseason.php`, Soccer Football Info `matches/day/full`) nu găsește meciurile lipsă — doar `eventsnextleague.php` (folosit singur, fără reconcilierea pe 3 surse aplicată SuperLigii) prinde o "fereastră glisantă" de 1 meci simultan. Vezi comentariul detaliat din `mappings.py`, lângă `TSDB_TEAM_IDS`. Nu s-a forțat o extindere nedovedită a reconcilierii per-echipă (ar necesita înregistrare manuală, per rundă, pentru zeci de cluburi de calificare) — tratat ca gol upstream real, nu bug de cod.
- **Romania SuperLiga (sezonul nou, iulie 2026+) nu primește rezultate reale prin niciuna din cele 2 surse curente ale `sync_results.py`** — confirmat live (audit Sprint 3, 2026-07-28): football-data.org nu acoperă liga (documentat) și `soccer_romania_1_liga` (Odds API) e marcat "dead" de validarea proprie (`/sports?all=true`, filtrat după `has_outrights`) — Odds API nu are piață per-meci pentru această ligă azi. Alternativă reală, dar NEconfirmată end-to-end: Soccer Football Info acoperă liga și are un rezultat real deja verificat (Dinamo București 5-1 Universitatea Craiova, 2026-07-25) — o reverificare live ulterioară a întors 0 meciuri, inconcludent (posibil rate-limit din testare repetată, neconfirmat). Vezi comentariul detaliat din `sync/sync_results.py`. Nu s-a implementat o a treia sursă pe date neconfirmate.
- **`match_history.season` — două cauze distincte pentru `NULL`, nu una singură** (Master Repair Plan, Pasul 3, 2026-08-03): (1) **provider nu oferă sezonul** — Kaggle/football-data.co.uk (89% din `match_history`, 47.653 rânduri): sursa istorică brută nu e împărțită pe fișiere de sezon, fără o sursă nouă rămâne `NULL` la nesfârșit, corect conform regulii „nicio stare necunoscută aproximată" (`season_cleanup.py`, interzice explicit aproximarea calendaristică); Flashscore (301 rânduri): nicio extracție de sezon nu există încă în pipeline (nu doar netransmisă — genuin necolectată de pe pagină), ar cere investigație live nouă, neinclusă acum. (2) **bug istoric, deja remediat** — football-data.org (5.756 rânduri): `sync/sources/football_data.py` parsa `season` din răspunsul API dar îl arunca înainte de scriere (variabilă locală neutilizată); fix la sursă (commit `a959b9e`) + backfill dedicat (`sync/backfill_season_football_data.py`, `backfill_season_football_data.yml`) au completat retroactiv toate cele 5.756 rânduri deja existente — verificat live, 100%, zero duplicate, zero coloane afectate. De acum, orice meci nou de la football-data.org are `season` corect de la prima scriere.

## Comenzi de bază

```bash
pip install -r requirements.txt
pytest tests/ -q                       # 82 teste, fără rețea
python sync/run_daily.py --dry-run     # simulare sincronizare zilnică, fără scriere
streamlit run app.py                   # UI local
```

## Acces live — GitHub + Supabase

- Branch de lucru: `claude/fotbal-oracle-repo-j4rlqo`. Niciodată push direct pe `main` fără aprobare explicită.
- Niciun commit/push fără să fi fost cerut.
- Supabase (`Prediction`, `eu-central-1`) conectat prin MCP — vezi „Regulile bazelor de date" mai sus.

## Infrastructura de skill-uri

Nucleul obligatoriu pentru v4.1 (`.claude/skills/`): `supabase-safety`, `frozen-doc-guard`, `security-review`, `architecture-review`, `walk-forward-validation`, `test-coverage-guard`. Restul (16 skill-uri suplimentare) e planificat etapizat pentru v4.2/v5.0, activat doar când apare nevoie reală — nu implementat preventiv.
