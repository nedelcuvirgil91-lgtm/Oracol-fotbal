# ADR-025 — Gate-05: Verificare Precondiții (2026-07-16)

**Status**: Verificare formală, **strict read-only** — zero scriere, zero DDL.
**Autorizare**: Gate-05, Owner, 2026-07-16 — "exclusiv executarea verificării
Gate-05 conform ID-025-05".

## Ce verifică Gate-05 (ID-025-05)

Poarta Faza 5 → migrare writeri (ID-025-03). Criteriu, definit strict:
(a) zero grupuri cu >1 rând canonic pentru aceeași cheie naturală normalizată;
(b) zero HARD CONFLICT nerezolvate; și — conform autorizării — (c) zero surse
necunoscute rămase.

**Rând canonic la nivel DB** = `superseded_by IS NULL` (definiția din ID-025-04).
Corpus curent: 53.432 rânduri total, 3.504 superseded, **49.928 rânduri live
(canonice)**.

## (a) Zero grupuri cu >1 rând canonic pe cheia naturală

Verificat pe **două chei**, fiindcă motorul de reconciliere folosește cheia
`normalize_team_name()` (via `match_key()`), mai puternică decât un simplu
`lower(trim())`:

### (a.1) Cheia brută `lower(trim())` — SQL

```sql
WITH live AS (
  SELECT lower(trim(home_team)) AS h, lower(trim(away_team)) AS a, left(kickoff_date,10) AS d
  FROM match_history WHERE superseded_by IS NULL
)
SELECT count(*) FROM (SELECT h,a,d FROM live GROUP BY h,a,d HAVING count(*) > 1) g;
```
**Rezultat: 0 grupuri** (din 49.928 rânduri live).

### (a.2) Cheia normalizată `normalize_team_name()` — verificare țintită

Simpla `lower(trim())` NU prinde alias-urile care se contopesc sub
`normalize_team_name()` (ex. `SPARTA PRAHA` → `AC Sparta Praha`). Am identificat,
din cele 960 nume distincte de echipe live, **6 grupuri de contopire** (12
variante brute) care sub normalizare devin un singur nume canonic:

| Nume canonic | Variante brute live |
|---|---|
| Sparta Praha | `AC Sparta Praha`, `SPARTA PRAHA` |
| Crvena Zvezda | `CRVENA ZVEZDA`, `FK Crvena Zvezda` |
| Dinamo Zagreb | `DINAMO ZAGREB`, `GNK Dinamo Zagreb` |
| Red Bull Salzburg | `FC Red Bull Salzburg`, `RED BULL SALZBURG` |
| Shakhtar Donetsk | `FK Shakhtar Donetsk`, `SHAKHTAR DONETSK` |
| Sporting CP | `Sporting Clube de Portugal`, `SPORTING CP` |

Am adus (read-only) toate cele **122 rânduri live** care implică oricare din
cele 12 nume și am calculat cheia `match_key()` (exact funcția motorului) pentru
fiecare. **Rezultat: 122 chei normalizate distincte, 0 coliziuni.** Variantele
all-caps (meciuri de cupă europeană 2021-2022, provenite din `kaggle_`, rămase
live fiindcă nu au avut un duplicat `fd_`) și variantele `fd_` (meciuri 2023+)
sunt fixture-uri reale diferite, pe date diferite — nu produc niciun duplicat
nici sub cheia normalizată.

**Concluzie (a): 0 grupuri cu >1 rând canonic**, atât pe cheia brută cât și pe
cheia normalizată completă.

> Observație (nu parte din Gate-05): faptul că cele 122 chei rămân distincte
> înseamnă că re-normalizarea de la Gate-07 (care va rescrie `SPARTA PRAHA` →
> `AC Sparta Praha` etc.) **nu** va produce coliziuni noi — dar verificarea
> formală a acelui fapt aparține Gate-07, după re-normalizarea efectivă, nu
> acestei porți.

## (b) Zero HARD CONFLICT nerezolvate

```sql
WITH live AS (
  SELECT lower(trim(home_team)) AS h, lower(trim(away_team)) AS a, left(kickoff_date,10) AS d,
    actual_result, actual_home_goals, actual_away_goals
  FROM match_history WHERE superseded_by IS NULL
),
dup AS (SELECT h,a,d, count(DISTINCT actual_result) dr, count(DISTINCT actual_home_goals) dh,
        count(DISTINCT actual_away_goals) da FROM live GROUP BY h,a,d HAVING count(*)>1)
SELECT count(*) FROM dup WHERE dr>1 OR dh>1 OR da>1;
```
**Rezultat: 0.** (Consecință directă: nu mai există niciun grup duplicat printre
rândurile live — deci niciun grup care ar putea fi în stare HARD CONFLICT. În
plus, Faza 4 a exclus explicit 0 grupuri pentru HARD CONFLICT.)

## (c) Zero surse necunoscute rămase

```sql
SELECT count(*) FROM match_history
WHERE superseded_by IS NULL
  AND fixture_id NOT LIKE 'fd_%' AND fixture_id NOT LIKE 'espn_%'
  AND fixture_id NOT LIKE 'odds_%' AND fixture_id NOT LIKE 'kaggle_%';
```
**Rezultat: 0 rânduri live** cu prefix `fixture_id` nerecunoscut (toate se
rezolvă în `SourceTrustProvider`).

## Rezumatul verificărilor Gate-05

| Criteriu | Cheie/metodă | Rezultat |
|---|---|---|
| (a) grupuri cu >1 rând canonic | `lower(trim())` (SQL) | **0** |
| (a) grupuri cu >1 rând canonic | `normalize_team_name()` / `match_key()` (122 rânduri la risc) | **0** |
| (b) HARD CONFLICT nerezolvate | SQL, pe rânduri live | **0** |
| (c) surse necunoscute rămase | SQL, prefix `fixture_id` | **0** |

Confirmare read-only: `total_rows=53.432`, `total_superseded=3.504`,
`total_live=49.928` — neschimbat față de finalul Fazei 4 (această verificare
nu a scris nimic).

## Verdict: **Gate-05 = GO**

Toate cele trei criterii = 0, criteriul (a) verificat pe cheia normalizată
completă (nu doar pe un proxy `lower(trim())`). Baza este pregătită structural
pentru pasul următor.

## Interdicții respectate (mandat Gate-05)

Nicio modificare de date, nicio migrare de writeri, nicio re-normalizare, nicio
modificare de schemă, niciun `CREATE INDEX`, niciun `UPDATE` pe coloanele de
audit. Execuția se oprește aici. **Gate-06 (migrarea writerilor, ID-025-03) nu
începe fără o autorizare nouă, explicită.**

## Snapshot

`match_history_adr025_faza4_backup_20260716` (53.432 rânduri) rămâne pe
producție ca plasă de rollback — de păstrat, conform recomandării Owner-ului,
cel puțin până la finalizarea și validarea Gate-05…Gate-08 și activarea
constrângerii UNIQUE.

## Referințe

- ADR-025 — Match Identity Implementation Strategy
- ID-025-04 — Database Constraint (definiția rândului canonic: `superseded_by IS NULL`)
- ID-025-05 — Validation (Gate-05)
- `docs/03_ENGINE/ADR025_PHASE4_FULL_RECONCILIATION_REPORT_2026-07-16.md`
