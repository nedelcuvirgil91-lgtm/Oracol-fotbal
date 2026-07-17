# ADR-025 — Faza 2: Raport DRY-RUN Reconciliere (2026-07-16)

**Status**: DRY-RUN complet, verificat. **Zero scriere pe producție.**
**Autorizare**: Fazei 2, Owner, 2026-07-16 — "DRY-RUN strict read-only".
**Domeniu**: `docs/03_ENGINE/ID-025-02-historical-reconciliation-engine.md`,
algoritm din `docs/03_ENGINE/ID-025-01-canonical-row-selection.md`.

## Cum a fost produs acest raport

Codul de decizie determinist (clasificare HARD CONFLICT, rezolvare sursă,
selecție canonică, merge non-destructiv) e implementat și testat unitar în
`services/match_identity_reconciliation_service.py` (`process_group()`, 17
teste, fără rețea/Supabase live — vezi
`tests/test_match_identity_reconciliation_service.py`).

Numerele din acest raport au fost produse prin interogări **exclusiv
SELECT** (agregare server-side), executate direct pe proiectul `Prediction`
via `mcp__Supabase__execute_sql`, replicând exact aceeași logică de decizie
(rang sursă din prefixul `fixture_id`, HARD CONFLICT pe cele 3 coloane,
selecție canonic prin rang minim + tiebreak id minim, merge NULL→valoare cu
câștigător de rang minim la conflict). Motivul: acest mediu de execuție nu
are credențiale directe către Supabase (doar canalul MCP, folosit aici
exclusiv pentru citire) — codul din `services/` e scris să ruleze real via
`supabase_client.py` (paginat, identic altor servicii din proiect), pentru
o rulare viitoare (CLI/GitHub Actions), nu doar pentru acest raport.
Verificare încrucișată: cele 5 categorii de cazuri (Case 1-4 din
ID-025-01, HARD CONFLICT, sursă necunoscută, tiebreak, formatul exact al
`superseded_reason`) sunt acoperite individual de teste unitare pe cod real.

Confirmare independentă a metodei de grupare: grupare brută (`lower(trim())`
pe echipe, fără `normalize_team_name()`) a produs **exact** 3.504 grupuri —
identic cu numărul audiat în ADR-024. Verificare suplimentară: cele 6 perechi
de alias-uri de echipă găsite în tot corpusul (ex. `AC Sparta Praha` /
`SPARTA PRAHA`) aparțin unor sezoane diferite de cupe europene, fără
suprapunere de dată — normalizarea completă (`match_key()`, folosită de codul
real) nu produce niciun grup suplimentar față de gruparea brută, pentru
datele curente.

## Rezultat — Clasa 1 (metrici obligatorii, ID-025-02 §"Raportare")

| Metrică | Valoare |
|---|---|
| Total grupuri descoperite | **3.504** |
| Total rânduri în grupuri | **7.008** (toate grupurile au exact 2 rânduri) |
| Excluse — HARD CONFLICT | **0** |
| Excluse — sursă necunoscută | **0** |
| Reconciliate cu succes | **3.504** (100%) |
| Rânduri canonice care ar primi ≥1 completare | **61** din 3.504 |
| Rânduri necanonice care ar fi marcate `superseded` | **3.504** |
| **Total rânduri afectate** (canonice completate + necanonice marcate) | **3.565** |
| Erori de scriere | N/A — DRY-RUN, nicio scriere încercată |

## Compoziția canonic/superseded, per sursă

| Grup | Canonic (rang câștigător) | Superseded |
|---|---|---|
| 3.501 grupuri istorice | `football_data` (rang 1) | `kaggle_historical` (rang 4) |
| 3 grupuri active (World Cup 2026) | `espn` (rang 2) | `odds_api` (rang 3) |

Coincide exact cu compoziția demonstrată în ADR-024 (3.501 istorice + 3
active) și cu Source Trust Policy din Faza 1 (`source_trust_policy.py`).

## Completări per coloană (Pasul 3, Case 2+3 — NULL → valoare)

Toate coloanele din `MERGE_COLUMNS` (51 total) au 0 completări, **cu excepția**
celor 8 coloane de medie recentă (backfill mai recent, ADR-011/012/013/021),
fiecare cu **55** completări:

| Coloană | Completări |
|---|---|
| `home_corner_avg_recent` / `away_corner_avg_recent` | 55 / 55 |
| `home_card_avg_recent` / `away_card_avg_recent` | 55 / 55 |
| `home_foul_avg_recent` / `away_foul_avg_recent` | 55 / 55 |
| `home_shot_avg_recent` / `away_shot_avg_recent` | 55 / 55 |
| Toate celelalte 43 coloane (`home_elo`, `home_shots`, `actual_*` exclus etc.) | 0 |

**Interpretare**: rândurile canonice (`football_data`/`espn`, sursele cu rang
1-2) au deja aproape toate coloanele populate — exact observația empirică din
ADR-024 ("100% din rândurile `fd_` au shots/corners populate"). Singurul gol
sunt cele 8 coloane de medie recentă, introduse ulterior scrierii inițiale a
acestor rânduri, pe 55 din cele 3.504 rânduri canonice (backfill-ul lor nu a
acoperit încă acele rânduri specifice — neafectat de reconciliere, doar
expus de ea).

## Ce NU s-a întâmplat (verificat explicit)

- **Zero scriere**: `superseded_by`/`superseded_at`/`superseded_reason` rămân
  `NULL` pe toate cele 53.432 rânduri — verificat direct după rulare (aceeași
  interogare de verificare de la Gate-01).
- Nicio modificare de schemă, writeri, sau constrângeri.
- Toate interogările folosite au fost exclusiv `SELECT`/agregare — niciun
  `INSERT`/`UPDATE`/`DELETE`/`ALTER` executat în această fază.

## Gate-02 (ID-025-05): Faza 2 → Faza 3

**Criteriu**: Raportul DRY-RUN există, acoperă tot corpusul cunoscut
(3.501 + 3 grupuri, ADR-024), zero scriere confirmată.
**No-Go dacă**: raport incomplet, sau orice scriere detectată în modul
DRY-RUN.

**Rezultat**: Raportul acoperă exact 3.504/3.504 grupuri cunoscute (100%),
zero scriere confirmată. Criteriul Gate-02 e satisfăcut din perspectivă
tehnică — **verdictul GO/NO-GO rămâne decizia explicită a Owner-ului**,
neautomatizat de acest document.

## Ce NU acoperă acest raport

- Pilotul pe subset izolat (Faza 3) — următorul pas, cu aprobare separată.
- Scrierea efectivă (modul EXECUTE) — neimplementată în cod în această fază
  (`MatchIdentityReconciliationService.run(dry_run=False)` ridică explicit
  `NotImplementedError`).
- Constrângerea UNIQUE (Faza 6, ID-025-04) și migrarea writerilor (Faza 7,
  ID-025-03).

## Referințe

- ADR-025 — Match Identity Implementation Strategy
- ID-025-01 — Canonical Row Selection
- ID-025-02 — Historical Reconciliation Engine
- ID-025-05 — Validation (Gate-02)
- ADR-024 — Canonical Match Identity & Data Contract (corpus audiat: 3.501 + 3)
