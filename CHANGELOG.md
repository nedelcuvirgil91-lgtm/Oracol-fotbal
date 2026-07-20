# Changelog

Toate schimbările notabile ale proiectului sunt documentate aici.

## [Nelansat] — Database-First Prediction Engine (ADR-035)

Seria D1–D4 mută Prediction Engine-ul pe sursa canonică internă (Supabase
`match_history`) înaintea providerilor externi. Principiul: niciun provider
extern nu poate avea prioritate asupra unei informații deja sincronizate în
baza canonică. Formulele ML/xG/Poisson/Monte Carlo rămân neatinse — se repară
exclusiv fluxul de date de intrare.

### Adăugat
- **D1 (PR #30, `ddf376a`)** — `oracle_engine._build_profile()` primește un
  nivel DB PRIMAR care citește forma/goluri din `match_history`, înaintea
  cascadei de provideri (prag `MIN_DB_MATCHES=3`).
- **D2 (PR #32, `d94d332`)** — ELO de club citit PRIMAR din
  `match_history.home_elo_after`/`away_elo_after` (Canonical Live ELO Snapshot,
  Phase 6 din ADR-023) prin `database.queries.get_latest_team_elo()`, global
  per club; `oracle_api.get_elo_rating()` rămâne fallback (naționale).
- **D3 (H2H Database-First)** — `database.queries.get_h2h_from_history()`
  (nouă) devine sursa canonică pentru Head-to-Head:
  - **Noul flux**: `oracle_engine._build_h2h()` recalculează bilanțul direct
    din rânduri BRUTE (`actual_result`/`actual_home_goals`/`actual_away_goals`),
    global per pereche de cluburi (fără filtru de ligă), înaintea FreeLF/Odds.
  - **Fallback**: sub 3 confruntări în DB (`MIN_H2H_MEETINGS`), se cade pe
    cascada FreeLF → Odds API → `H2HRecord.empty()` (influence 0), neschimbată.
  - **Impact asupra Oracle Engine**: H2H-ul folosit în blend-ul xG
    (`h2h_modifier`) provine acum din propriile date sincronizate, recalculat
    walk-forward-safe, nu din coloane precalculate contaminabile. Zero atingere
    a formulelor de model.
  - Nu se folosesc niciodată coloanele precalculate `h2h_modifier`/
    `h2h_meetings` (cursă de scriere concurentă documentată separat ca task
    **D3.5 — Feature Canonicalization**, neatins în D3).
- **D3.5 — Canonical Feature Ownership (ADR-036, PR #35, `f8bd73a`) — COMPLETED** —
  repară contractul de SCRIERE al `match_history` descoperit în review-ul D3:
  fiecare coloană canonică are un owner clar; `first-writer-wins` (`COALESCE`)
  încetează să fie arbitraj între componente.
  - **Stage 1**: `oracle_engine._cache_prediction()` nu mai scrie cele 10
    `FEATURE_COLUMNS` owner-ate de backfill — rămân NULL până le completează
    `run_backfill()` walk-forward (sursă canonică unică).
  - **Stage 3**: `update_weights_from_result()` nu mai scrie `actual_*`
    (owner: `sync/sync_results.py`); gărzi AST Single-Writer permanente.
  - **Neatins**: RPC `upsert_match_canonical` (contract generic, folosit
    legitim de import), formulele ML, D1/D2/D3.
  - **Stage 2** (curățarea ≤29 rânduri pendinte) = **Deferred Operational
    Task**, documentat în ADR-036, NEexecutat — mentenanță de date, nu
    corectitudine de arhitectură.

### Verificare
- Fiecare pas (D1/D2/D3) cu teste fail-before/pass-after, gardă statică AST
  pentru unicitatea punctelor de citire, și verificare live pe date reale
  (GitHub Actions). Zero regresii pe cele 9 ligi.

## [4.1.0] — 2026-07-17

### Adăugat (Learning Core)
- ADR-026 — substrat de guvernanță pentru automatizare (`automation_runs`, `decision_feed`), stări impuse prin trigger Postgres, nu doar logică de aplicație.
- ADR-028 — `league_weights_adaptive`, primul algoritm din `recalibration.py` migrat în Model Registry ca `LearningAlgorithm` real (traseabil în `training_runs`); calea legacy din `sync/sync_results.py` devine opt-in (`auto_recalibration_enabled`, implicit `False`, era `True`).
- ADR-030 — Continuous Learning, funcție decuplată de `sync/run_daily.py` (workflow GitHub Actions propriu), gated de `learning_core_enabled` (implicit `False`, neactivat încă în producție).
- ADR-031 — N-way Serving Policy: ieșirile brute per motor de predicție expuse aditiv, view-ul compus rămâne neschimbat.

### Corectat
- **Hotfix ADR-030** (`learning_core/continuous_learning.py`, `_count_finished_matches()`): `league_scope="all"` era tratat ca nume literal de ligă, deci numărătoarea de meciuri terminate întorcea mereu 0 pentru orice algoritm cu acest scope (toți cei 3 înregistrați azi) — Faza B (antrenare automată) n-ar fi pornit niciodată. Descoperit exclusiv în etapa de pregătire a activării `learning_core_enabled` în producție, nu mai devreme, fiindcă flag-ul n-a fost pornit până acum — nicio consecință reală până la acest punct. Nu e o schimbare de arhitectură, doar o corecție locală, generică (pe valoare, nu pe nume de algoritm).

## [4.0.0] — 2026-07-12

### Adăugat
- **Odds Persistence Service** (`services/odds_persistence_service.py`) — persistare istorică a cotelor de piață (opening/closing), cu contract de arhitectură dedicat (`docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md`, ADR-005, ADR-006).
- Migrare SQL versionată pentru `odds_history` (`database/migrations/001_odds_history.sql`) — schemă, trigger de imutabilitate structurală, funcție RPC de persistare atomică.
- Walk-forward validation (expanding window) pentru antrenarea ML, înlocuind `train_test_split` aleator — elimină scurgerea temporală.
- De-vig pentru probabilitățile implicite ale bookmaker-ilor (`_devig_probabilities()`) — Value Betting Engine folosește acum probabilități "fair", fără marja bookmaker-ului.
- Audit de feature importance (permutation importance, ablație) pe 53.409 meciuri reale — 6 feature-uri ML cu importanță zero eliminate din antrenare.
- `docs/03_ENGINE/FEATURE_ENGINEERING_ROADMAP.md` — analiză completă a candidaților de feature engineering, ordonați după ROI/complexitate.
- `docs/03_ENGINE/REST_DAYS_VALIDATION.md` — validare empirică (nu doar teoretică) a ipotezei "rest days" — verdict: neintegrat, fără câștig măsurabil.
- Consolidare alias echipă (`Dinamo Bucuresti`/`Dinamo București`/`Din. Bucuresti` → o singură identitate canonică) în `mappings.py`.

### Corectat
- Import Romania SuperLiga extins (2021-2026, 917 meciuri noi), cu deduplicare corectă prin normalizare de nume.
- Câmp `bookmaker` curat, expus explicit pe obiectele `match` (anterior doar încapsulat în șirul de afișare `odds_source`).

### Guvernanță
- `docs/00_GOVERNANCE/FROZEN_REGISTRY.md` — registru oficial al documentelor de arhitectură Frozen.
- ADR-005, ADR-006 — clarificări de guvernanță și operaționale pentru `ODDS_PERSISTENCE_DESIGN.md`.

### Cunoscut, neschimbat în această versiune
- `recalibrate_weights()` — mecanism legacy, păstrat activ pentru continuitatea unui viitor benchmark comparativ; nu mai primește dezvoltare nouă.
- Schema completă Supabase (15 din 16 tabele) nu are încă migrări `.sql` versionate — doar `odds_history` e acoperit complet.
- Chei API (`ODDS_API_KEY`, `WEATHER_API_KEY`, `RAPIDAPI_KEY`) rămân hardcodate în `oracle_api.py` — migrare planificată, neurgentă (repo privat).

---

*Versiunile anterioare nu au fost documentate retroactiv în acest changelog — istoricul complet de dezvoltare există în conversațiile de proiect asociate.*
