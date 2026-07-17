# ADR-025 — Gate-08: Natural-Key UNIQUE Index (2026-07-16)

**Status**: Index UNIQUE parțial creat pe producție, verificat. **Execuția s-a
oprit** pentru revizuire — niciun pas din Gate-09 sau ulterior.
**Autorizare**: Gate-08, Owner, 2026-07-16 — "exclusiv executarea Gate-08,
conform ADR-025, ID-025-04 și ID-025-05".

## Ce s-a creat

Garanția structurală **A** din ADR-025 (ID-025-04): index UNIQUE **parțial** pe
cheia naturală, scopat exclusiv la rândurile canonice.

```sql
CREATE UNIQUE INDEX idx_match_history_natural_key_canonical
  ON match_history (home_team, away_team, kickoff_date)
  WHERE superseded_by IS NULL;
```

Aplicat pe producția `Prediction` prin `apply_migration` (non-destructiv — nu
atinge date, reversibil prin `DROP INDEX`). Artefact în repo:
`database/migrations/009_match_natural_key_unique_index.sql`.

Clauza `WHERE superseded_by IS NULL` face indexul compatibil cu designul
non-destructiv: rândurile `superseded` păstrează, prin construcție, aceeași cheie
naturală ca randul lor canonic, deci un index neconditionat ar fi fost imposibil
de adăugat. Această condiție e, prin ID-025-04, definiția oficială a unui rând
canonic la nivel de schemă.

## Precondiții verificate înainte de creare

| Verificare (read-only, înainte) | Rezultat |
|---|---|
| Grupuri duplicate pe cheia exactă `(home_team, away_team, kickoff_date)` printre rândurile live | **0** (indexul poate fi creat fără violare) |
| Rânduri live cu `kickoff_date` lungime ≠ 10 | **0** |
| Rânduri live cu `kickoff_date` NULL | **0** |
| min/max lungime `kickoff_date` live | 10 / 10 |

Toate `kickoff_date` live sunt exact 10 caractere → indexul pe coloana exactă
`kickoff_date` e identic ca efect cu cheia coarse `left(kickoff_date,10)` folosită
de lookup-ul RPC (ID-025-03). Combinat cu numele deja normalizate (Gate-07),
indexul exact-coloană coincide cu cheia naturală a motorului de scriere.

## Verificări Gate-08 (mandat + ID-025-05)

### 1. Indexul a fost creat cu succes
`pg_indexes`: index prezent (`index_present=1`); `pg_index.indisvalid = true`.
Definiție confirmată din `pg_get_indexdef`:
`CREATE UNIQUE INDEX idx_match_history_natural_key_canonical ON public.match_history
USING btree (home_team, away_team, kickoff_date) WHERE (superseded_by IS NULL)` —
identică cu ID-025-04.

### 2. Zero duplicate rămase după creare
`live_dup_groups = 0` (grupare pe cheia exactă, rânduri canonice). Total rânduri
`53.432`, superseded `3.504`, live `49.928` — neschimbat.

### 3. Writerii migrați (Gate-06) funcționează în continuare prin RPC, fără regresii
- **Smoke test producție, RPC pe un meci existent** (rulat într-o tranzacție
  `ROLLBACK`): `upsert_match_canonical` pentru Burnley vs Manchester City,
  2023-08-11 → `{"id":13,"action":"update"}` — RPC-ul găsește rândul canonic și
  face UPDATE non-destructiv, corect, cu indexul prezent. Rolled back, zero
  persistență.
- **Backstop (V-10), smoke test producție**: INSERT direct care ocolește RPC-ul,
  pentru aceeași cheie canonică → **eșuează dur** cu
  `duplicate key value violates unique constraint "idx_match_history_natural_key_canonical"`
  (SQLSTATE 23505) — exact "Comportament la violare" din ID-025-04. Tranzacția
  abortează, zero persistență (`smoke_leftover=0`, total neschimbat).
- **Suita de teste**:
  - `pytest tests/` (fără PG): **416 passed, 1 skipped**.
  - `pytest tests/` (cu Postgres local, indexul natural-key adăugat în schema de
    test): **427 passed** — inclusiv cele 11 teste de concurență, dintre care **2
    noi V-10** (`test_V10_direct_insert_bypassing_rpc_violates_unique_index`,
    `test_V10_superseded_row_coexists_with_canonical_key`). RPC-ul migrat + indexul
    coexistă fără regresie; backstop-ul respinge scrierile directe; rândurile
    superseded coexistă cu cheia canonicului fără a viola indexul parțial.

## Gate-08 (ID-025-05)

**Criteriu**: `CREATE UNIQUE INDEX ...` a rulat cu succes (indexul apare în
`pg_indexes`, `pg_index.indisvalid = true`).
**No-Go dacă**: eșec la creare (semn că o precondiție nu era satisfăcută).

**Verificare**: index prezent, valid, definiție conformă; 0 duplicate rămase;
writeri migrați funcționali; backstop demonstrat pe producție; suită verde.

### Verdict: **Gate-08 = GO**

## Backup-uri (păstrate, NEȘTERSE)

Confirmat pe producție, ambele intacte:
- `match_history_adr025_faza4_backup_20260716` — **53.432 rânduri** (snapshot complet pre-Faza-4).
- `match_history_gate07_renorm_backup_20260716` — **5.403 rânduri** (id/home/away pre-re-normalizare).

Niciunul nu a fost șters. Rămân disponibile pentru rollback.

## Interdicții respectate (mandat Gate-08)

Doar crearea + verificarea indexului. Niciun pas din Gate-09 sau ulterior. Mă
opresc pentru revizuire înainte de orice altă autorizare.

## Referințe

- ID-025-04 — Database Constraint (definiția indexului, precondiții, comportament la violare)
- ID-025-05 — Validation (Gate-08, V-10)
- ADR-025 — Match Identity Implementation Strategy (garanția structurală A)
- `database/migrations/009_match_natural_key_unique_index.sql`
