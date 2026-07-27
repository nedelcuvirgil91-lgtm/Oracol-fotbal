# Changelog

Toate schimbările notabile ale proiectului sunt documentate aici.

## [Nelansat] — Migrare cheie API-Football: `API_FOOTBALL_KEY_NEW` devine cheia activă

**Context**: cheia API-Football originală (`API_FOOTBALL_KEY`) a fost suspendată/blocată de provider — nu mai poate fi folosită. Migrarea a urmat integral procesul aprobat explicit (§„Regulile pentru chei API și provideri externi", `CLAUDE.md`), cu excepția documentată a pasului 6 (cheie veche ca fallback), inaplicabil prin forța faptelor.

### Guvernanță
- POC izolat rulat live (`workflow_dispatch`, GitHub Actions run [30276111299](https://github.com/nedelcuvirgil91-lgtm/Oracol-fotbal/actions/runs/30276111299)) — **VERDICT: PASS**. Autentificare OK, 4/4 verificări structurale compatibile (`/status`, `/teams`, `/injuries`, `/coachs`), zero diferență de plan/cotă față de ce era documentat pentru cheia veche (Free, 100/zi). Segmentul validat = exact ce e activ azi în producție (Team Health, R-Sync-2) — `/fixtures/statistics`, `/fixtures/lineups`, `/standings` rămân netestate, în afara scopului acestei migrări.
- POC-ul (`sync/poc_api_football_new_key_validation.py` + workflow-ul dedicat + testele lui) **șters din cod** după închiderea migrării — dovada rămâne în istoricul rulării GitHub Actions de mai sus, nu ca infrastructură vie permanentă.
- Adăugată secțiunea „Regulile pentru chei API și provideri externi" în `CLAUDE.md` — Regula 1 (proces de migrare pas-cu-pas), Regula 2 (zero regresii funcționale), regulă generală (niciun provider nou „mai bun" doar pentru că e nou).

### Cunoscut, neschimbat în această versiune
- `key_manager.py` — zero schimbare de cod: `PROVIDERS["apifootball"]` citește în continuare din variabila de mediu `API_FOOTBALL_KEY` (nume standard, neschimbat) — doar **valoarea** secretului GitHub s-a schimbat (acțiune manuală, ireductibilă, a proprietarului produsului — acces la serviciu extern).
- Orchestrarea automată (`sync/sync_team_health.py` → `sync/run_daily.py`) **rămâne un pas separat**, neexecutat încă în acest commit — necesită confirmare explicită înainte de implementare (schimbare de comportament în producție), prezentată separat.

## [Nelansat] — Learning Core: Orchestrare (ADR-037, Stage R3) — cod complet, NEMERGE-UIT pe `main`

Cablarea Champion Guardian (R2) + Rollback Engine (R1) în bucla `continuous_learning`
(ADR-030): Faza D nouă (evaluează sănătatea campionului activ, propune rollback dacă
recomandat) + extinderea Fazei C (execută rollback-ul aprobat). Pură orchestrare —
niciun prag/metrică recalculat, Guardian și Rollback Service rămân owneri unici ai
logicii lor. **Merge pe `main` amânat deliberat** — vezi §„Descoperire critică" mai jos.

### Adăugat
- **R3.1 — Faza D (read-only)**: `_phase_d_champion_health` — evaluează campionul
  activ prin `champion_guardian.evaluate_champion_health()`, jurnalizează rezultatul
  într-un `automation_run` (`champion_health_check`, T2). Zero efect de decizie.
- **R3.2A — Propunere T3a de rollback**: dacă Guardian recomandă rollback, Faza D
  propune o decizie T3a (`rollback_candidate`), cu două gărzi obligatorii:
  - **gardă anti-ping-pong** — un campion deja reactivat printr-un rollback anterior
    (`rollback_service.is_rollback_promoted()`, singurul loc care interpretează
    formatul `promoted_by`) nu declanșează automat un al doilea rollback — lanțul
    automat plafonat la un singur pas (ADR-037 §14);
  - **gardă R3-Risk-1** — `propose_decision()` suprascrie evidence-ul oricărei
    decizii deschise pe același target; Faza D sare peste propunere dacă există deja
    o decizie deschisă, ca să nu stivuiască peste ea.
- **R3.2A.1 — Execution Contract: ținta rollback-ului înghețată la propunere**
  (descoperire dintr-un Execution Readiness Review, cerut explicit înainte de a
  scrie codul de execuție): `evidence` capătă `current_training_run_id` +
  `predecessor_training_run_id`, fixate la momentul propunerii — simetric cu
  `promote_challenger` (target fix, nu recalculat). Motiv: `get_champion_predecessor()`
  derivă predecesorul DINAMIC din campionul activ curent — fără înghețare, un retry
  peste timp (proces mort între RPC și `commit_decision`) ar recalcula un predecesor
  diferit, producând un rollback în lanț neintenționat.
- **R3.2B — Execuția rollback-ului aprobat, cu țintă fixă (CAS pinned)**: Faza C
  extinsă (`_phase_c_execute_rollback`) citește **exclusiv** ținta înghețată din
  evidence, niciodată recalculată. `rollback_service.rollback_champion()` primește
  un parametru opțional nou, `expected_predecessor_training_run_id` — transmis
  explicit, folosit direct ca sămânța CAS; omis (`None`), comportamentul R1 (cale
  manuală) rămâne neschimbat. RPC 014 **neatins** — CAS-ul deja existent din R1 e
  singura sursă de adevăr pentru validare. Testat explicit: retry după crash (nimic
  altceva schimbat) → `already_active`; retry după schimbare externă de stare →
  `predecessor_mismatch` → `rejected`, niciodată un rollback peste o stare învechită.
- **R3.5 — Verificare live, read-only (Production Topology Audit)**: confirmă zero
  mutație/efect secundar din codul R3 pe Supabase `Prediction` — dar cu o descoperire
  semnificativă (vezi mai jos).
- **R3.7 — Flag-uri de deployment dedicate**: `champion_guardian_enabled` (gatează
  exclusiv Faza D) + `champion_guardian_proposals_enabled` (gate separat, doar pentru
  propunerea T3a) — ambele implicit `False`, independente de `learning_core_enabled`
  (rămas exclusiv al Fazelor A/B/C, neschimbat). Oglindește tiparul deja stabilit de
  ADR-033 (`consensus_capture_enabled`/`consensus_validation_enabled`).
- **26 de teste noi** (`tests/test_continuous_learning_rollback.py`) + **9 teste noi**
  (`tests/test_rollback_service.py`, helper `is_rollback_promoted` + parametrul
  `expected_predecessor_training_run_id`) + gărzi AST actualizate.

### Descoperire critică — merge pe `main` amânat deliberat
Auditul R3.5 a găsit `model_config.learning_core_enabled = true` deja activ în
producție (pre-existent, susține bucla ADR-030/Fazele A/B/C, neînrudit cu R3) — și
`.github/workflows/continuous_learning.yml` rulează pe `main`, care nu conține deloc
codul R3. Consecință: un merge simplu, fără flag dedicat, ar fi activat Faza D
automat la prima rulare programată de după merge, fără niciun pas de activare
deliberat — încălcând separarea intenționată „R3 (cod gata) ≠ R4 (activare
deliberată)". R3.7 (flag-urile dedicate) închide acest gol înainte de orice merge.
Detalii complete: `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md`.

### Documentație
- `docs/04_LEARNING_CORE/R3_IMPLEMENTATION_CHECKLIST.md` — reconciliat cu execuția
  reală (R3.2A/R3.2A.1/R3.2B, nu planul inițial R3.2/R3.3).
- `docs/04_LEARNING_CORE/CHAMPION_GUARDIAN_IMPLEMENTATION.md` §17 — stare de
  implementare R3 completă.
- `docs/DEPLOYMENT/ADR037_DEPLOYMENT_PLAN.md` (nou) — manual de lansare.
- `docs/00_GOVERNANCE/ARCHITECTURE_STATE.md` (nou) — sursă unică de adevăr pentru
  starea proiectului (ADR-uri implementate, branch, ce e pe `main`, ce rulează live,
  ce e activat prin flag-uri).

## [Nelansat] — Learning Core: Champion Guardian (ADR-037, Stage R2)

Evaluator **read-only** al sănătății campionului activ: clasifică starea în cinci
valori și persistă fapte imuabile în `champion_health_evaluations`. NU promovează,
NU face rollback, NU orchestrează, NU atinge servirea — doar citește, clasifică,
persistă. Fără cablare în Continuous Learning (R3), fără activare (R4).

### Adăugat
- **R2.1 — migrarea 015 (`database/migrations/015_champion_health.sql`)**: tabela
  `champion_health_evaluations`, aditivă, **append-only**, RLS activ,
  `UNIQUE(training_run_id, n_matches_evaluated)` (aceeași fereastră → un singur
  rând, pentru totdeauna), `CHECK health_state IN` (5 valori),
  `CHECK baseline_source IN` (`promotion_evaluation`/`trend_only`/`manual_override`),
  FK către `training_runs`, două indexuri. Imuabilitatea e garantată de
  `UNIQUE + ON CONFLICT DO NOTHING` (precedent `challenger_evaluations`, ADR-018),
  **fără trigger**.
- **R2.3 — `supabase_client`**: `get_champion_served_outcomes()` (doar rânduri
  scorabile — `prob_home_pred` ȘI `actual_result` prezente, `kickoff_date ≥
  since_date`, ordine totală `(kickoff_date, fixture_id)`),
  `record_champion_health_evaluation()` (INSERT idempotent, `on_conflict=
  "training_run_id,n_matches_evaluated"`, `ignore_duplicates=True`),
  `get_recent_champion_health_evaluations()` (istoric DESC după
  `n_matches_evaluated`).
- **R2.4 — `learning_core/champion_guardian.py`**: punct unic de intrare public
  `evaluate_champion_health(algorithm_family, league_scope)`; patru dimensiuni de
  sănătate (structural, deviație de la baseline, trend 50/50, stabilitate
  informativă) reduse la o singură clasificare într-un punct unic de decizie
  (`_classify_champion_health`). Reutilizează `shadow_testing._brier`. Constante
  stabilite: `MIN_MATCHES_FOR_HEALTH=30`, `BASELINE_DEGRADATION_MARGIN=0.10`,
  `TREND_DEGRADATION_MARGIN=0.10`, `CONSECUTIVE_DEGRADED_WINDOWS=2`,
  `STABILITY_DISPERSION_THRESHOLD=0.20`. Prioritatea clasificării: **Critical
  (structural) > InsufficientData (n<MIN) > Degrading (consecutiv) > Watch >
  Healthy**.
  - **Politica de persistare**: `n==0` → return-only (Critical structural e
    returnat, dar NU persistat — F3); `n≥1` → persistă exact o dată per fereastră,
    idempotent.
  - **Regula ferestrelor consecutive (F1)**: `_count_consecutive_degraded` exclude
    rândurile cu `n_matches_evaluated >= current_n` — o rerulare pe aceeași
    fereastră nu mai dublează numărătoarea, nu mai escaladează fals Watch →
    Degrading.
- **R2.5–R2.7 — teste** (35 total, fără rețea): `test_champion_guardian.py` (21 —
  toate cele 5 stări, prioritatea clasificatorului, regresie F1 unit +
  end-to-end, persistență, best-effort); `test_supabase_client_champion_health.py`
  + `test_champion_guardian_ownership.py` (14 — wrappere pe client fabricat +
  gărzi AST de ownership).
- **R2.7 — gărzi AST de ownership**: `champion_guardian` NU importă
  `promotion_service`/`rollback_service`/`oracle_engine`/`continuous_learning`, NU
  referențiază promovare/rollback/`automation_runs`; `record_champion_health_
  evaluation` are un singur apelant de producție (Guardian). Impune mecanic
  granița R2 vs. R3: Guardian scrie DOAR `champion_health_evaluations`.
- **R2.8 — verificare de integrare `validated without state mutation`**: pe DB
  live, `champion_health_evaluations` = 0 rânduri, 3 campioni activi neatinși.
  Calea statistică live nu a putut fi exercitată pe date reale fiindcă
  **`scoreable = 0`** (zero rânduri `match_history` cu `prob_home_pred` ȘI
  `actual_result`); corectitudinea e acoperită integral de cele 35 de teste
  sintetice.

### Limitare operațională
Champion Guardian este complet implementat și testat, însă validarea live a căii
statistice (Healthy/Watch/Degrading bazate pe meciuri scorabile) este amânată
până când `match_history` conține predicții servite care au și rezultat
(`scoreable > 0`). În starea actuală (`scoreable = 0`), Guardian intră în
`insufficient_data` și nu produce mutații de stare.

### Notă operațională (disciplină de deployment)
- Migrarea 015 a fost aplicată prin **Supabase SQL Editor**, nu prin
  `apply_migration` (conexiunea MCP în mod read-only la momentul aplicării) —
  identic cu 014. Consecință: tabela NU apare în tracker-ul „Database Migrations"
  al Supabase (oprit la `013`). **Sursa canonică rămâne fișierul comitat**
  `database/migrations/015_champion_health.sql`.

## [Nelansat] — Learning Core: Rollback Engine (ADR-037, Stage R1)

Închiderea ciclului de viață al campionului — mecanism de rollback append-only,
simetric (dar separat) de Promotion, care reactivează predecesorul unui campion
degradat. Doar fundația SQL + serviciul Python; fără Champion Guardian (R2),
fără orchestrare/apelanți automați (R3), fără activare (R4).

### Adăugat
- **R1.1 — migrarea 014 (`database/migrations/014_rollback.sql`)**: funcția
  Postgres `rollback_champion(algorithm_family, league_scope,
  expected_predecessor_training_run_id, reason, by)` — eveniment de domeniu
  „Rollback Champion", **append-only** (retrage campionul activ, reactivează
  predecesorul printr-un rând nou), o singură tranzacție atomică pe
  `model_champions`, cu **gardă compare-and-swap** (predecesor derivat
  server-side sub lock, comparat cu cel așteptat → `predecessor_mismatch` la
  neconcordanță). Oglindește `promote_challenger` (005); nu atinge
  `challengers`, triggerul de imuabilitate (005), sau alte tabele.
  - Modificări din auditul pre-R1: gardă `NULL` explicită pe
    `expected_predecessor` (previne ocolirea CAS prin logică trivalentă SQL);
    derivare deterministă a predecesorului (`ORDER BY superseded_at DESC
    LIMIT 1` — predecesorul imediat, ADR-037 §3).
- **R1.2 — deploy + verificare** pe proiectul `Prediction`: funcția aplicată și
  verificată read-only — semnătură corectă (5×`text` → `text`), owner/privilegii
  **identice cu `promote_challenger`** (`service_role` are `EXECUTE`), **zero
  rânduri modificate** (conturi `model_champions`/`challengers`/`training_runs`/
  `challenger_evaluations` = baseline), trigger 005 + `promote_challenger`
  intacte, invariantul „un singur campion activ" respectat.
- **R1.3 — `learning_core/rollback_service.py`**: owner exclusiv al evenimentului
  „Rollback Champion", simetric cu `promotion_service.py`. Precondiții în Python
  ÎNAINTE de RPC (motiv ∈ set de 6 → citire predecesor → validare artefact
  predecesor), CAS (predecesorul validat trimis ca `expected_predecessor`),
  niciodată nu propagă excepții (`RollbackResult`), izolat, declanșare manuală.
- **R1.4 — `supabase_client`**: `get_champion_predecessor()` (derivă predecesorul
  imediat, `ORDER BY superseded_at DESC LIMIT 1`, oglindind RPC-ul) și
  `rpc_rollback_champion()` (wrapper simetric cu `rpc_promote_challenger`).
- **R1.5–R1.7 — teste** (29 total, fără rețea): comportament serviciu (16,
  fail-fast + CAS + idempotență + excepții), wrapper-e `supabase_client` (client
  fabricat), gărzi AST de ownership (`rpc_rollback_champion` un singur apelant;
  `rollback_service` izolat; nu importă `shadow_testing`).
- **R1.8 — verificare de integrare `validated without state mutation`**: pe DB
  live, cele 3 gărzi ale RPC-ului confirmate prin căi negative (motiv invalid,
  `expected_predecessor` NULL, fără campion activ) — toate ridică excepție înainte
  de orice scriere; `model_champions` neschimbat (4 rânduri, 3 activi, 0 rollback).
  **Happy-path (swap-ul atomic real) e DEFERAT** deliberat: presupune modificarea
  campionului activ din producție și se va executa doar într-o operație controlată
  (prima utilizare reală guvernată, R2/R3, sau un mediu dedicat).

### Notă operațională (disciplină de deployment)
- Migrarea 014 a fost aplicată prin **Supabase SQL Editor**, nu prin
  `apply_migration` (conexiunea MCP era în mod read-only în momentul aplicării).
  Consecință: funcția NU apare în tracker-ul „Database Migrations" al Supabase
  (care se oprește la `013`). **Sursa canonică rămâne fișierul comitat**
  `database/migrations/014_rollback.sql`. Pe viitor, la folosirea migrării
  automate (CLI / Supabase migrations), trebuie evitată reaplicarea aceleiași
  funcții sau sincronizat istoricul migrărilor. Nu e un blocker pentru R1 —
  doar disciplină operațională de consemnat.

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
- **D4 — Honest Data Quality Labeling (PR #37, `4ba8bb2`) — COMPLETED** —
  `data_quality` nu mai raportează „statistici reale" pentru eșantioane
  sintetice/subțiri. Taxonomie finală **LIVE / PARTIAL / ELO / NEUTRAL**
  (nivel nou `PARTIAL` pentru surse agregat/proxy/sintetice).
  `_classify_data_quality()` = punct UNIC de decizie (cele 9 atribuiri inline
  eliminate); LIVE doar pentru `supabase-history` cu n≥3. Text LIVE onest
  („Date reale — meciuri terminate"). UI: badge PARTIAL, un singur emoji
  (dublu-emoji curățat). Value Bets neatins (zero schimbare comportamentală),
  zero migrare. Cazul central (1 meci TSDB) nu mai e „statistici reale".

**Seria Database-First (D1–D4) e ÎNCHISĂ.** Următorul obiectiv: Learning Core.

### Verificare
- Fiecare pas (D1/D2/D3) cu teste fail-before/pass-after, gardă statică AST
  pentru unicitatea punctelor de citire, și verificare live pe date reale
  (GitHub Actions). Zero regresii pe cele 9 ligi.

## [4.2.0] — 2026-07-27

Merge în `main` (PR #41, commit `6a39461`) — 21 commit-uri, trei arcuri de lucru, fiecare închis cu disciplina audit → design → implementare → teste → auto-audit → aprobare explicită → commit.

### Adăugat (Universal Synchronization Architecture — ADR-038/039, R4.1, R-Sync-1→7a)
- Migrarea accesului la provideri externi într-un tipar exclusiv Sync-Layer (`Provider → Sync Adapter → Normalize → Validate → Persist → Supabase`) — Oracle Engine/Prediction Engine/ML nu mai apelează niciun provider extern direct, pentru domeniile migrate.
- R4.1 — Request Manager, Rate Limit Manager, Coverage Cache, Sync Orchestrator; eliminarea completă a cheilor de provider hardcodate.
- R-Sync-1 — interfața `SyncAdapter` formalizată.
- R-Sync-2 — API-Football (accidentări/antrenori).
- R-Sync-3 — football-data.org (formă/standings).
- R-Sync-4 — ELO național (eloratings.net) — corectat pe parcurs dintr-o clasificare greșită inițială (TheSportsDB), găsită și reparată prin dovadă de cod live, nu presupunere.
- R-Sync-5 — sincronizare prognoză meteo.
- R-Sync-6 — formă FreeLF + fallback H2H/formă Odds API.
- R-Sync-7a — fundația Universal Match Discovery Layer: `scheduled_fixtures` + RPC `FixtureMergePolicy` field-level (migrarea 023), validat live pe producție, inclusiv un bug real de concurență găsit și reparat în timpul validării (`INSERT ... ON CONFLICT DO NOTHING` + fallback de merge).
- R-Sync-7b — **oprit deliberat la etapa de design/audit** (§6f/§6g din auditul de sincronizare) după ce a fost găsit un defect structural chiar în mecanismul lui de shadow logging — vezi ADR-040 mai jos.

### Adăugat (ADR-040 — Automated Migration Gate & Equivalence Governance)
- Escaladat dintr-un bug (validarea shadow a R-Sync-7b producea dovezi vizibile doar dacă cineva citea log-uri manual) într-o infrastructură de guvernanță generică, reutilizabilă — `equivalence_evaluations` + view-ul `migration_gate_status` + `migration_gate.py` (`status`/`explain`/`attest`/`verify`).
- Validat live pe producție cu exemple reale GREEN/YELLOW/RED/GRAY plus un caz intenționat invalid (prins de o migrare ulterioară care adaugă constrângeri `CHECK` de integritate).
- `scheduled_fixtures_shadow_enabled` rămâne `False` — acest merge construiește și demonstrează poarta, nu activează comparația shadow live a R-Sync-7b.

### Adăugat (Data Warehouse — Etapa A/B)
- `docs/05_DATA_AUDIT/DATA_WAREHOUSE_CURRENT_STATE_2026-07-27.md` — consolidează 4 audituri preexistente în loc să le dubleze; găsirea centrală: 6 componente Sync Layer complet construite au zero rânduri pentru că `sync/run_daily.py` nu le apelează niciodată (gol de orchestrare, nu de infrastructură lipsă).
- `docs/05_DATA_AUDIT/DATA_WAREHOUSE_ARCHITECTURE_ETAPA_B_2026-07-27.md` — document de arhitectură viu, 11 domenii funcționale (Match Statistics, Team Form, Lineups, Injuries, Referees, Weather, Betting Markets, Team Strength, Historical Performance, Player Statistics, Competition Metadata), fiecare câmp cu owner/fallback/politică de merge/consumator, plus Data Freshness, Data Lineage, matrice P0-P3 cu Business Impact.

### Guvernanță
- ADR-038, ADR-039 — înghețate (Frozen).
- ADR-040 — introdus ca PROPOSED (devine Frozen abia după G4-G6, puse deliberat în așteptare).
- Regulă nouă de proces, adoptată de proprietarul produsului: `main` e sursa oficială de adevăr; branch-urile sunt spații temporare; fiecare etapă aprobată urmează commit → push → PR → merge (după aprobare explicită) → confirmare restore point → ștergere branch — o etapă nu se consideră închisă până la confirmarea tuturor acestor pași.

### Cunoscut, neschimbat în această versiune
- **Zero schimbare de comportament live** — toate flag-urile noi implicit `False`; `oracle_engine.py` citește exact aceleași surse ca înainte de acest merge.
- Sync Layer (R-Sync-3→7a) rămâne neorchestrat — prioritatea #1 din Etapa A, neexecutată încă.
- Cele 8 tabele fără RLS semnalate în auditul din 13 iulie rămân nerezolvate (preexistente acestui merge).
- Ștergerea branch-ului remote `claude/continua-faza-1-adr5-o52jat` a eșuat (HTTP 403, politică de proxy a sesiunii pe operații distructive remote) — branch-ul local a fost șters; cel remote rămâne, complet fuzionat, inert.

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
