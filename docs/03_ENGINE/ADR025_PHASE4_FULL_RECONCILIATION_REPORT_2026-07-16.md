# ADR-025 — Faza 4: Raport Reconciliere Completă (2026-07-16)

**Status**: Reconciliere completă a corpusului — încheiată, verificată.
**Execuția s-a oprit conform mandatului** — nu s-a migrat niciun writer, nu
s-a rulat re-normalizarea, nu s-a creat indexul UNIQUE, niciun pas din Faza 5
sau ulterior.
**Autorizare**: Faza 4, Owner, 2026-07-16 — "exclusiv reconcilierea completă
a corpusului folosind algoritmul deja validat la Gate-02 și Gate-03".

## Algoritm — identic cu Gate-02/Gate-03, fără nicio modificare de logică

`services/match_identity_reconciliation_service.py` și `source_trust_policy.py`
**nu au fost modificate** (verificat: `git diff` gol înainte de rulare).
Reconcilierea completă a fost executată prin **exact aceeași replicare
set-based SQL validată la Gate-02** (aceeași grupare pe cheie naturală
`lower(trim())`, același rang de sursă din prefixul `fixture_id`, aceeași
selecție canonic = rang minim + tiebreak `id`, același merge non-destructiv
NULL→valoare, același format de `superseded_reason`), generată programatic din
lista exactă `MERGE_COLUMNS` (52 coloane) a modulului neschimbat. Logica
set-based a fost încrucișat-validată cu funcția pură `process_group()` la
Gate-03 (potrivire exactă pe 5 grupuri). `SourceTrustProvider`, criteriile de
selecție și writerii rămân neatinși.

**Mecanism de execuție**: o **singură instrucțiune SQL atomică** cu două CTE-uri
modificatoare de date (`merge_update` + `supersede_update`), ambele rulate la
completare pe același snapshot pre-instrucțiune — atomicitate totală
(all-or-nothing pe întreg corpusul), mai puternică decât tranzacția-per-grup
din ID-025-02 (care exista pentru a evita stări parțiale de grup; o singură
tranzacție pe tot corpusul elimină complet acea posibilitate). Mediul de
execuție nu are credențiale directe Supabase — scrierea s-a făcut prin canalul
MCP, exclusiv pentru această instrucțiune.

**Snapshot de siguranță** (ADR-025 Faza 4 + `supabase-safety`): înainte de
scriere s-a creat `match_history_adr025_faza4_backup_20260716` (copie completă,
53.432 rânduri) — plasă de rollback suplimentară peste reversibilitatea
intrinsecă (merge doar completează NULL-uri; marcajele `superseded_*` se pot
șterge).

## Raport complet EXECUTE

| Metrică | Valoare (Faza 4) |
|---|---|
| Grupuri în scope (rânduri live, necanonice-excluse) | 3.499 |
| **Grupuri procesate / reconciliate** | **3.499 / 3.499 (100%)** |
| **Rânduri marcate `superseded`** | **3.499** |
| **Rânduri canonice completate (merge)** | **58** |
| Coloane completate | exclusiv cele 8 `*_avg_recent` (52 completări fiecare) |
| Grupuri excluse — HARD CONFLICT | **0** |
| Grupuri excluse — sursă necunoscută | **0** |
| Grupuri non-pereche (>2 rânduri) | 0 |
| Erori de scriere | 0 |

### Numărul total pe întreg corpusul (Faza 3 pilot + Faza 4)

| Metrică | Pilot (Faza 3) | Faza 4 | **Total corpus** |
|---|---|---|---|
| Grupuri reconciliate | 5 | 3.499 | **3.504** |
| Rânduri `superseded` | 5 | 3.499 | **3.504** |
| Rânduri canonice completate | 3 | 58 | **61** |

## Lista completă a grupurilor HARD CONFLICT

**Niciunul (0).** Nicio pereche cu `actual_result`/`actual_home_goals`/
`actual_away_goals` divergent — consistent cu ADR-024 (100% scoruri identice)
și cu Gate-02.

## Lista completă a surselor necunoscute

**Niciuna (0).** Toate rândurile din toate grupurile au prefix `fixture_id`
recunoscut (`fd_`/`espn_`/`odds_`/`kaggle_`), rezolvabil în
`SourceTrustProvider`.

## Compoziția canonic / superseded (verificată post-execuție)

| | Canonic | Superseded |
|---|---|---|
| 3.501 grupuri istorice | `football_data` (`fd_`, rang 1) | `kaggle_historical` (`kaggle_`, rang 4) |
| 3 grupuri World Cup 2026 | `espn` (rang 2) | `odds_api` (`odds_`, rang 3) |

Verificat direct: `superseded_kaggle=3501`, `superseded_odds=3`,
`canonical_fd=3501`, `canonical_espn=3`, restul 0. **`superseded_reason` —
0 nepotriviri de format** față de șirul generat de algoritm (verificat
caracter cu caracter pe toate cele 3.504 rânduri).

## Abateri față de estimările DRY-RUN (Gate-02)

**Zero abateri.** Gate-02 (corpus complet, DRY-RUN) a estimat: 3.504 grupuri,
61 rânduri canonice cu completări, 3.504 rânduri de marcat, 55 completări per
coloană `*_avg_recent`. Rezultatul real (pilot + Faza 4): **3.504 grupuri,
61 canonice completate, 3.504 superseded**. Faza 4 singură = exact estimarea
Gate-02 minus pilotul (3.504−5=3.499 grupuri; 61−3=58 canonice; 55−3=52 per
coloană). Nicio discrepanță de explicat.

## Dovada încheierii complete + trasabilitate prin coloanele de audit

Verificare read-only, post-execuție:

| Verificare | Rezultat |
|---|---|
| Total rânduri tabelă | 53.432 (**neschimbat** — 0 rânduri adăugate/șterse) |
| Total rânduri `superseded_by` setat | **3.504** |
| Rânduri superseded fără `superseded_at`/`superseded_reason` | **0** (trasabilitate completă) |
| Grupuri duplicate rămase printre rândurile live (`superseded_by IS NULL`) | **0** |
| `superseded_by` care indică un `id` inexistent | **0** (integritate referențială) |
| Lanțuri superseded→superseded (canonic el însuși superseded) | **0** |

### Dovada de containment (diff vs. snapshot `..._backup_20260716`)

| Diferență față de backup | Rânduri |
|---|---|
| `superseded_by` nou setat | **3.499** (exact grupurile Faza 4) |
| Vreo coloană `*_avg_recent` modificată | **58** (exact canonicele completate) |
| **Orice ALTĂ coloană** (elo, shots, corners, fouls, ratings, `actual_*`, echipe, `fixture_id`, ligă, `used_for_training`...) modificată oriunde | **0** |
| Completări `*_avg_recent` ajunse pe un rând superseded | **0** (toate pe rânduri canonice/live) |

Footprint-ul de scriere e **exact** cel prezis de algoritm: 3.499 rânduri
necanonice marcate + 58 rânduri canonice completate strict în cele 8 coloane
`*_avg_recent`. Nicio valoare reală suprascrisă (Writer Protection —
`other_cols_changed=0`), nicio identitate/scor atins, nicio ștergere.

## Gate-04 (ID-025-05): Faza 4 → Faza 5

**Criteriu**: Rularea completă (ID-025-02) s-a încheiat — raport final produs,
inclusiv secțiunile "excluse — HARD CONFLICT" și "excluse — sursă necunoscută".
**No-Go dacă**: rulare încă în curs sau întreruptă fără raport final.

**Verificare**: rularea completă s-a încheiat (o singură instrucțiune atomică,
`COMMIT` confirmat implicit prin rezultatul returnat: 3.499/3.499). Raportul
final e acest document, inclusiv ambele secțiuni de excludere (ambele goale,
0 grupuri). Zero eroare de scriere. Toate cele 3.504 rânduri superseded sunt
integral trasabile prin coloanele de audit.

### Verdict: **Gate-04 = GO**

Dovezi: raportul EXECUTE complet de mai sus, cele 6 verificări de integritate
post-execuție (toate 0 pe metricile de eroare), dovada de containment prin diff
vs. snapshot (`other_cols_changed=0`), potrivirea exactă cu estimarea Gate-02,
și compoziția canonic/superseded identică cu ADR-024.

## Notă privind Faza 5 / Gate-05 (NU parte din această autorizare)

Verificarea suplimentară "0 grupuri duplicate rămase printre rândurile live"
(inclusă mai sus ca dovadă) este, formal, criteriul **Gate-05** (Faza 5 →
migrare writeri), nu Gate-04. Este raportată aici doar ca observație
factuală — **verdictul formal Gate-05, re-normalizarea, migrarea writerilor și
indexul UNIQUE rămân în afara acestei autorizări** și necesită o autorizare
nouă, explicită, separată.

## Interdicții respectate (mandat Faza 4)

Execuția s-a oprit aici. **Nu s-a început migrarea writerilor (ID-025-03), nu
s-a executat re-normalizarea, nu s-a creat indexul UNIQUE, nu s-a continuat
către fazele următoare.**

## Artefacte

- Snapshot de rollback: tabela `match_history_adr025_faza4_backup_20260716`
  (53.432 rânduri, stare pre-Faza-4). Recomandare: păstrată până la
  confirmarea stabilității post-Faza-9; ștergere ulterioară printr-un pas
  operațional explicit.

## Referințe

- ADR-025 — Match Identity Implementation Strategy (Faza 4, Rollback Strategy)
- ID-025-01 / ID-025-02 — Canonical Row Selection / Historical Reconciliation Engine
- ID-025-05 — Validation (Gate-04)
- `docs/03_ENGINE/ADR025_PHASE2_DRY_RUN_REPORT_2026-07-16.md` (estimarea Gate-02)
- `docs/03_ENGINE/ADR025_PHASE3_PILOT_EXECUTE_REPORT_2026-07-16.md` (pilotul Gate-03)
