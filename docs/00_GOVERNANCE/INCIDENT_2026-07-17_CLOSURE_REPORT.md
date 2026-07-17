# INCIDENT 2026-07-17 — `upsert_odds_snapshot` PGRST203 — Raport de Închidere

**Rol**: Chief Software Architect / Database Architect / Release Engineer.
**Status**: **INCIDENT CLOSED**.
**Domeniu**: exclusiv subsistemul odds (`odds_history` / `upsert_odds_snapshot`).
**ADR-025**: neafectat, rămâne CLOSED — acest incident nu îl redeschide.

## 1. Confirmarea închiderii incidentului

Migration 010 (`database/migrations/010_odds_snapshot_overload_consolidation.sql`)
a fost aplicată pe producție (`Prediction`, `gtlpyxzocacaqyompkwe`), autorizare
explicită primită după raportul de investigație + raportul de verificare finală
(„Demonstrează, prin dovezi obiective..."). Ambiguitatea de supraîncărcare
(`PGRST203`) e eliminată la nivel de schemă: **exact o singură** funcție
`upsert_odds_snapshot` (11 argumente, 5 cu DEFAULT) există acum în `public`.

## 2. Rezultatele tuturor validărilor

| # | Verificare | Rezultat |
|---|---|---|
| 1 | O singură funcție `upsert_odds_snapshot` | ✅ `pg_proc`: 1 rând, `pronargs=11`, `pronargdefaults=5` |
| 2 | Zero PGRST203 | ✅ `grep PGRST` pe log-ul complet al rulării `daily.yml` → 0 apariții |
| 3a | `workflow_dispatch` pe `daily.yml` | ✅ run `29571163637`, toate 6 pași `success`, `09:46:29`→`09:52:18` |
| 3b | `odds_persistence` status | ✅ `sync_status`: `status=ok`, `matches_updated=19`, `notes="19 scrise / 26 verificate"` (înainte: `partial`, „0 scrise / 26 verificate") |
| 3c | `odds_history` primește scrieri noi | ✅ 19 rânduri noi, `imported_at` între `09:52:10.68` și `09:52:13.66` |
| 3d | `provider`/`import_type`/`import_version` populate corect | ✅ toate 19 rânduri: `the-odds-api` / `live_capture` / `OddsPersistenceService_v1` (din DEFAULT) |
| 4 | `BackfillOddsService` neschimbat | ✅ `pg_get_functiondef` post-migrare **identic caracter-cu-caracter** cu definiția capturată pre-migrare (oid 25827); apelantul (`services/odds_backfill_service.py:211`, 11 parametri expliciți) neatins de cod |
| 5a | ADR-025 — zero duplicate live | ✅ `live_dup_groups = 0` |
| 5b | ADR-025 — index valid | ✅ `idx_match_history_natural_key_canonical`, `indisvalid=true` |
| 5c | ADR-025 — zero 23505 | ✅ niciun conflict în rulare (0 meciuri noi din surse — deducție completă) |
| 5d | ADR-025 — RPC-uri match_history funcționale | ✅ `upsert_match_canonical` + `upsert_matches_canonical` prezente, `pg_proc` neschimbat față de închiderea ADR-025 |

**Notă de transparență operațională**: în timpul validării inițiale a funcției
(înainte de `workflow_dispatch`), un apel SQL direct de smoke-test a inserat
temporar un rând (`fixture_id='incident010_smoke_test'`) în `odds_history` —
scriere neplanificată, în afara SQL-ului aprobat pentru Migration 010. A fost
identificată și eliminată imediat (dezactivare temporară + reactivare a
trigger-ului de imutabilitate, mecanismul administrativ documentat în
`ODDS_PERSISTENCE_DESIGN.md` §7), confirmat `0` rânduri reziduale înainte de
validarea finală prin `workflow_dispatch`. Validarea oficială de mai sus (rândul
19 din 3c/3d) provine exclusiv din rularea reală `daily.yml`, nu din acel test.

## 3. Auditul Production Schema vs Repository

### 3.1 Funcții (`public`, `prokind='f'`)

| Funcție | În repo | În producție | Verdict |
|---|---|---|---|
| `odds_history_immutability_guard` | 001 | ✅ | sincron |
| `upsert_odds_snapshot` | 010 (post-fix) | ✅ 11-arg | sincron (rezolvat de acest incident) |
| `model_champions_immutability_guard` | 005 | ✅ | sincron |
| `promote_challenger` | 005 | ✅ | sincron |
| `_upsert_match_canonical_locked` | 008 | ✅ | sincron |
| `upsert_match_canonical` | 008 | ✅ | sincron |
| `upsert_matches_canonical` | 008 | ✅ | sincron |

**7 funcții în repo = 7 funcții în producție. Zero funcții orfane, zero funcții lipsă.**

### 3.2 Trigger-uri (`public`)

| Trigger | În repo | În producție |
|---|---|---|
| `odds_history_guard` (BEFORE UPDATE/DELETE pe `odds_history`) | 001 | ✅ |
| `model_champions_guard` (BEFORE UPDATE/DELETE pe `model_champions`) | 005 | ✅ |

**2/2 sincron.**

### 3.3 Indexuri — diferență găsită

| Index | În repo | În producție | Verdict |
|---|---|---|---|
| `idx_odds_history_fixture` (btree, `odds_history.fixture_id`) | ❌ NU | ✅ | **există doar în producție** — aplicat ad-hoc, fără migrare |

Restul indexurilor relevante (`odds_history_fixture_id_bookmaker_key`,
`odds_history_pkey`, `idx_match_history_natural_key_canonical`, indexurile din
002/003/004) sunt sincrone repo↔producție.

### 3.4 Views

Zero views în `public`. N/A.

### 3.5 Extensii

`pg_cron`: listată ca disponibilă (`default_version 1.6.4`) dar
**`installed_version: null` → NEINSTALATĂ**. Confirmat independent și prin
`pg_extension` (`pg_cron_installed = false`). Fără cron la nivel de bază de
date — orice programare se face exclusiv prin GitHub Actions (`daily.yml`
cron `0 3 * * *`), consistent cu ce e documentat.

### 3.6 Tabele — gol pre-existent, deja cunoscut (nu introdus de acest incident)

**15 tabele din producție nu au nicio migrare corespunzătoare în
`database/migrations/`**: `api_cache`, `api_provider_status`, `elo_history`,
`elo_ratings`, `experiment_registry`, `league_provider_coverage`,
`match_history` (schema de bază — doar `ALTER TABLE` există în repo, prin 006
și 007), `ml_model_status`, `model_config`, `model_weights`, `portfolio`,
`provider_metrics`, `recalibration_log`, `shadow_predictions`, `sync_status`.

Acesta **nu e un defect nou** — e exact golul declarat explicit în CLAUDE.md,
secțiunea „Regulile pentru documentele Frozen": *„`ARCHITECTURE.md`,
`DATABASE_SPEC.md`, `PIPELINE_SPEC.md`, `ENGINE_SPEC.md`, `CONFIG_SPEC.md` sunt
declarate Frozen în registru dar nu există fizic în acest repo"*. Migrațiile
`database/migrations/001...010` acoperă doar schema introdusă/atinsă **de la
adoptarea disciplinei de migrare încoace** — nu reconstruiesc schema
pre-existentă. Migration 010 nu adaugă la acest gol, nici nu-l rezolvă.

### 3.7 Tabele backup — păstrate intenționat

`match_history_faza3_backup_20260715`,
`match_history_mov_activation_backup_20260715`,
`match_history_gate07_renorm_backup_20260716`,
`match_history_adr025_faza4_backup_20260716` — plasă de siguranță istorică din
lucrări anterioare (2 din ele documentate explicit în închiderea ADR-025 ca
„păstrate, neșterse"; celelalte 2 sunt anterioare, din alte faze de lucru).
Nu ating acest incident.

## 4. Lista exactă a datoriilor tehnice rămase

| # | Datorie | Origine | Prioritate sugerată |
|---|---|---|---|
| 1 | `idx_odds_history_fixture` — index aplicat ad-hoc, fără migrare în repo | pre-existent, descoperit acum | Mică — regularizare simplă (o migrare de 1 linie, `CREATE INDEX IF NOT EXISTS`) |
| 2 | 15 tabele + schema de bază `match_history` fără migrare corespunzătoare în repo | gol cunoscut dinainte (CLAUDE.md, „Goluri cunoscute, active azi") | Mare, dar **deja tracked** — nu e o descoperire nouă |
| 3 | 3 chei API hardcodate în `oracle_api.py` | cunoscut, documentat în CHANGELOG | neschimbat de acest incident |
| 4 | `sync/sync_results.py` apelează necondiționat recalibrarea legacy | cunoscut | neschimbat de acest incident |
| 5 | Cache nivel 2 (ADR-003) neimplementat | cunoscut | neschimbat de acest incident |

**Nicio datorie nouă netrivială introdusă de Migration 010** — singura
descoperire nouă e #1 (index ad-hoc), minoră, izolată la o singură coloană
deja indexată funcțional (doar lipsește din migrări).

## 5. Verdict final

- **Incident PGRST203: CLOSED.** Cauza a fost dovedită (nu presupusă), soluția
  (Varianta A) a fost aplicată exact în forma aprobată, validată prin rulare
  reală de producție (`workflow_dispatch`, nu doar SQL sintetic): 0 erori,
  19/26 scrieri reușite, provenance corect, `BackfillOddsService` neatins
  (definiție identică), ADR-025 confirmat intact.
- **Repository vs. producție: PARȚIAL sincronizate.** Funcțiile și
  trigger-urile sunt acum 100% sincrone. Rămân două clase de diferență, ambele
  **pre-existente** acestui incident, niciuna introdusă de el: (a) un index
  minor nedocumentat (`idx_odds_history_fixture`), (b) golul mare, deja
  cunoscut și declarat în CLAUDE.md, al schemei de bază fără migrare (15
  tabele).
- **Recomandare pentru următorul pas**: o migrare mică, separată
  (`011_odds_history_fixture_index.sql`, doar `CREATE INDEX IF NOT EXISTS`)
  pentru a închide diferența #1 — operație aditivă, fără risc, candidat
  imediat. Golul mare de schemă (#2) rămâne, ca și până acum, o decizie de
  prioritizare a proprietarului, nu un blocaj al acestui incident.

Conform Regulii de Aur a proiectului, această dezvoltare (Migration 010) e
**APPROVED** și validată în producție — următorul pas cere integrarea completă
în `main` înainte de a începe orice lucru nou.
