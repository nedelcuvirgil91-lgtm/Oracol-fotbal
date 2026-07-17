# ADR-025 — Gate-06: Writer Migration (2026-07-16)

**Status**: Writeri migrați, RPC canonic în producție, testat. **Execuția s-a
oprit** — nu s-a rulat re-normalizarea (Gate-07), nu s-a creat indexul UNIQUE
(Gate-08), niciun pas ulterior.
**Autorizare**: Gate-06, Owner, 2026-07-16 — "executarea exclusivă a Gate-06
(ID-025-03 — Writer Migration)".

## Ce s-a implementat

Mecanismul **D** din ADR-025 la sursă (ID-025-03): orice scriere care ar putea
crea un al doilea rând fizic pentru un meci deja existent devine acum UPDATE
non-destructiv pe rândul canonic, sub `pg_advisory_xact_lock` scopat pe cheia
naturală normalizată. Race-safe **independent** de constrângerea UNIQUE (care
vine abia la Gate-08).

### RPC canonic (producție — `database/migrations/008_match_canonical_upsert.sql`)

Aplicat pe `Prediction` prin `apply_migration` (3 funcții, `CREATE OR REPLACE`,
non-destructiv — nicio tabelă/dată atinsă). Smoke-test pe producție într-o
tranzacție `ROLLBACK` (ramura INSERT rulează pe schema reală → `action:insert`,
apoi rollback; `total_rows` neschimbat 53.432, zero rând rezidual, cele 3 funcții
prezente).

- `_upsert_match_canonical_locked(p jsonb)` — nucleul: `pg_advisory_xact_lock` pe
  `hash(lower(trim(home))||'||'||lower(trim(away))||'||'||date)` → lookup rând
  canonic (`superseded_by IS NULL`, egalitate `lower/trim` pe valorile deja
  normalizate în Python) → HARD CONFLICT (rezultat/goluri divergente) opreşte
  scrierea → altfel UPDATE care completează DOAR coloanele NULL (Writer
  Protection, COALESCE) sau INSERT rând canonic nou. Cheia naturală
  (`fixture_id`/`home_team`/`away_team`/`kickoff_date`) nu se schimbă la UPDATE.
- `upsert_match_canonical(p_payload jsonb)` — intrare pentru un singur meci.
- `upsert_matches_canonical(p_payloads jsonb)` — intrare pentru un lot (o singură
  tranzacție; lock-uri achiziționate în ordine crescătoare a cheii → deadlock-free
  între loturi concurente; gestionează și duplicate în interiorul aceluiași lot).

Normalizarea numelor rămâne **exclusiv în Python** (`normalize_team_name`) înainte
de apel — RPC-ul face doar egalitate exactă `lower/trim`, niciodată normalizare
proprie (ID-025-03: fără reimplementare în SQL).

### Writeri migrați (Python)

| Writer | Fișier | Înainte | După |
|---|---|---|---|
| `upsert_matches_bulk()` | `database/queries.py` | `.upsert(batch, on_conflict="fixture_id")` | `.rpc("upsert_matches_canonical", {"p_payloads": batch})` |
| `upsert_match()` | `database/queries.py` | `.upsert(row, on_conflict="fixture_id")` | `.rpc("upsert_match_canonical", {"p_payload": row})` |
| `upsert_match_history()` | `supabase_client.py` | `.upsert(payload, on_conflict="fixture_id")` | `.rpc("upsert_match_canonical", {"p_payload": payload})` |

`upsert_match()` nu e listat explicit în ID-025-03 (folosit azi doar în teste),
dar e o cale de scriere care POATE crea rânduri (upsert pe `fixture_id`) — migrat
și el, ca să nu rămână nicio cale directă de creare a duplicatelor (revizuire
explicită a listei, cerută de ID-025-03).

Call-site actualizat: `oracle_engine.py` (înregistrare rezultat) trimite acum și
`kickoff_date` (din cache) — RPC-ul cheamă rândul după cheia naturală completă,
nu după `fixture_id`.

Normalizarea + eliminarea cheilor `None` (`_normalize_team_fields`,
`_strip_none_values`) rămân neschimbate, aplicate înainte de apelul RPC.

## Criterii Gate-06 (mandat Owner)

### 1. Toate căile de scriere din ID-025-03 folosesc RPC-ul
Verificat prin cod: `grep` pe `.upsert(`/`.insert(` asupra `match_history` în tot
codul de producție (exclus `/tests/`) → **zero rezultate**. Toți cei trei writeri
+ toți apelanții de producție (`sync/sync_matches.py`, `sync/import_historical.py`,
`oracle_engine.py`) rutează exclusiv prin RPC.

### 2. Niciun INSERT/UPDATE direct care poate crea duplicate
Niciun path fixture_id-based de creare rămas. Singurele scrieri directe rămase pe
`match_history` sunt UPDATE-uri pe rânduri deja găsite prin lookup
(`backfill_features.py`, `services/*backfill*`, `sync_results.update_results_in_supabase`)
— nu pot crea un al doilea rând (confirmat de ID-025-03, "Nu necesită migrare").

### 3. Testele de concurență V-06, V-07, V-08 + testul compus — verzi
`tests/test_writer_migration_concurrency.py`, rulat contra unui Postgres 16 local
efemer, cu `pg_advisory_xact_lock` real (9 teste, toate PASSED):

| Test | Proprietate ID-025-05 | Rezultat |
|---|---|---|
| `test_V06_two_writers_complementary_fields` | V-06: doi writeri, câmpuri NULL complementare → un rând, ambele completate | PASS |
| `test_V07_identical_payloads_second_is_noop` | V-07: payload-uri identice → al doilea e no-op, fără al doilea rând | PASS |
| `test_V08_both_new_no_existing_row_single_insert` | V-08: ambii pentru un meci nou, fără rând existent → exact un INSERT (exact cazul pentru care `SELECT FOR UPDATE` a fost respins) | PASS |
| `test_V11_compound_bulk_and_single_concurrent` | V-11 compus: writer bulk + writer single, concurent, aceeași cheie | PASS |
| `test_stress_many_threads_single_row` | 12 thread-uri pe aceeași cheie nouă → exact un rând | PASS |
| `test_insert_then_update_fills_only_nulls` | Writer Protection (merge doar NULL) | PASS |
| `test_hard_conflict_not_written` | HARD CONFLICT → nu se scrie | PASS |
| `test_superseded_row_never_revived` | rând superseded nu e reînviat de o scriere nouă | PASS |
| `test_batch_merges_intra_batch_duplicate` | lot cu duplicat intern → un singur rând | PASS |

Metoda V-06/07/08: **timing controlat** — t1 deschide tranzacție și cheamă RPC
(achiziționează lock-ul, ține tranzacția), t2 cheamă RPC pe aceeași cheie într-un
thread și **blochează** pe lock (verificat: thread încă viu după 1s), apoi t1 face
commit → t2 continuă și găsește rândul creat de t1 (UPDATE, niciodată al doilea
INSERT). Testul demonstrează empiric alegerea `pg_advisory_xact_lock` din
ID-025-03, nu doar argumentul teoretic.

Testele sunt **skip automat** dacă `ADR025_TEST_PG_DSN` nu e setat sau psycopg2
lipsește — deci `pytest tests/` implicit rămâne verde și fără rețea/Supabase live
(disciplina de test din CLAUDE.md respectată).

### 4. Comportament identic funcțional, cu excepția protecției la concurență
Verificare end-to-end prin codul Python real al writerilor migrați, contra
Postgres-ului local (client fals care execută SQL-ul real):
- `upsert_matches_bulk` pe variante-alias (`Man Utd`/`Ath Madrid` și
  `Manchester United`/`Atletico Madrid`, aceeași dată) → **un singur rând
  canonic**, `home_shots=12` și `away_shots=3` ambele păstrate (merge
  non-destructiv), `home_elo=None` eliminat (nu suprascrie).
- `upsert_match_history` completează `actual_result='H'` → True.
- HARD CONFLICT (A vs H) → returnează False, loghează, nu scrie.

Diferența față de implementarea anterioară: (a) meciuri deja existente sub cheia
naturală devin UPDATE non-destructiv în loc de un al doilea rând; (b) protecție la
concurență prin lock advisory. Restul contractului (normalizare, Writer Protection
per-coloană NULL, dedup) — identic.

### 5. Fără regresii; toate testele proiectului trec
- `pytest tests/` (fără PG): **416 passed, 1 skipped** (modulul de concurență
  skip curat).
- `pytest tests/` (cu PG local activ): **425 passed** (416 + 9 concurență).
- Testele writerilor afectate (`test_team_normalization_writers.py`,
  `test_sync_writer_protection.py`) actualizate la noul mecanism (`.rpc()` în loc
  de `.upsert()`) — proprietățile testate (normalizare la punct unic, eliminare
  chei None) neschimbate, doar calea de apel.

### 6. Commit SHA + raport
Acest document + commit-ul asociat (vezi mai jos).

## Gate-06 (ID-025-05)

**Criteriu**: toți writerii din tabelul ID-025-03 rulează prin RPC-ul cu
`pg_advisory_xact_lock`; verificat prin inspecție de cod + testul de concurență.
**Verificare**: cele 3 căi de scriere rutează prin RPC (secțiunea 1); zero cale
directă de creare rămasă (secțiunea 2); testele de concurență verzi (secțiunea 3).

### Verdict: **Gate-06 = GO**

## Interdicții respectate (mandat Gate-06)

Nu s-a executat re-normalizarea (Gate-07), nu s-a creat indexul UNIQUE (Gate-08),
niciun pas ulterior. Snapshot-ul `match_history_adr025_faza4_backup_20260716`
rămâne pe producție (de păstrat până după Gate-08, conform recomandării Owner-ului).

## Note

- Producția a fost provizionată cu logica RPC identică celei din
  `database/migrations/008_...sql` (artefactul canonic, validat de teste); diferă
  doar formatarea listei `INSERT ... VALUES`, nu comportamentul.
- Impact operațional: `upsert_matches_bulk` face acum un apel RPC per lot de 250
  (nu upsert nativ) — o singură tranzacție server-side per lot, throughput
  comparabil; nicio schimbare de dimensiune de lot.

## Referințe

- ID-025-03 — Writer Migration
- ID-025-05 — Validation (Gate-06, V-06..V-08, V-11)
- ADR-025 — Match Identity Implementation Strategy (mecanismul D)
- Precedent RPC atomic: `services/odds_persistence_service.py`,
  `database/migrations/005_promotion.sql`
