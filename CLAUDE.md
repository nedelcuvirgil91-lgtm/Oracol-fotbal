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

## Knowledge Map — rolul fiecărui modul

| Modul | Rol (o propoziție) | Depinde de | Consumat de |
|---|---|---|---|
| `oracle_api.py` | Strat unificat de acces la provideri externi (cote, meciuri, vreme, ELO), cu fallback între surse. | `key_manager.py`, `cache_manager.py`, `mappings.py` | `oracle_engine.py`, `sync/run_daily.py` |
| `oracle_engine.py` | Motorul de predicție — Poisson, Monte Carlo, blend ELO/ML, de-vig, value betting. | `oracle_api.py`, `feature_engine.py`, `ml_predictor.py`, `recalibration.py`, `shadow_testing.py`, `supabase_client.py`, `database/queries.py` | `app.py` |
| `ml_predictor.py` | Model XGBoost, antrenat pe `match_history`, walk-forward validation (expanding window). | `supabase_client.py` | `oracle_engine.py`, `sync/run_daily.py` |
| `recalibration.py` | Funcție pură de ajustare a ponderilor per ligă, fără I/O. | (niciuna) | `oracle_engine.py`, `sync/sync_results.py` |
| `shadow_testing.py` | Infrastructură generică de shadow testing + Statistics Engine, independentă de `oracle_engine.py`. | `supabase_client.py` | `oracle_engine.py` (gated), `sync/run_daily.py` |
| `feature_engine.py` | Calcul formă, H2H, rest days (existent, neapelat — vezi `REST_DAYS_VALIDATION.md`). | (date brute) | `oracle_engine.py` |
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

## Regulile testelor

- `pytest tests/` trebuie să rămână verde — 82 de teste confirmate, fără dependință de rețea.
- Orice schimbare în calea de predicție (`oracle_engine.py`) se verifică funcțional (rulare reală pe fixture-uri cunoscute), nu doar prin teste unitare.

## Regulile Champion vs. Challenger (Learning Core)

- Promovare doar din statusul `candidate_for_promotion`, doar dacă Brier + Log-loss + Accuracy sunt *simultan* semnificativ mai bune (vezi `shadow_testing.evaluate_experiment()`).
- Promovarea automată (`auto_promotion_enabled=True`) contrazice azi ADR-002 și necesită un ADR nou dedicat înainte de activare — niciodată implicit pornită.
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

- `oracle_api.py` conține 3 chei API hardcodate (`ODDS_API_KEY`, `WEATHER_API_KEY`, `RAPIDAPI_KEY`) — cunoscut, documentat în `CHANGELOG.md` ca „neurgent, repo privat", dar tratat ca risc real, nu ignorat.
- `sync/sync_results.py` apelează încă necondiționat recalibrarea legacy (`_recalibrate_for_result`), contrazicând flag-ul `auto_recalibration_enabled` promis de ADR-004 dar niciodată implementat.
- Cache nivel 2 (ADR-003, Supabase comun între instanțe) — proiectat, neimplementat.

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
