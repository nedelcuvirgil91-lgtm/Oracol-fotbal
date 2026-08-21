# F0 — Artefacte de audit al identității de echipă (ADR-058)

**Data capturii**: 2026-08-21 · **Proiect Supabase**: `gtlpyxzocacaqyompkwe` (`Prediction`)
**Regim**: strict read-only. Nicio scriere în Supabase, niciun flag, nicio migrare.

## De ce există acest director

Auditul manual anterior a transcris liste de nume **de mână**. Rezultatul: trei
erori de numărare, toate descoperite ulterior prin re-verificare mecanică:

| Eroare | Valoare manuală | Valoare reală |
|---|---|---|
| E1 — rânduri orfane viitoare | 85 | **50** |
| E1b — rânduri terminate afectate | 843 | **878** |
| E2 — baze deja canonice | 25 | **31** |
| E3 — total perechi cu bază existentă | 84 | **85** |

> **Regula operațională**: F3 (extinderea `mappings.py`) consumă
> `class_a_bases.csv`, **niciodată** o listă copiată dintr-un text de audit.
> Un nume purtat de mână printr-un raport e exact mecanismul care a produs E1-E3.

## Fișiere

| Fișier | Conținut | Generat de |
|---|---|---|
| `suffix_pairs.csv` | 85 perechi `X (CCC)` → `X`, cu bază existentă în `match_history` | Q1 (mai jos) |
| `class_a_bases.csv` | aceleași 85, clasificate contra `mappings.TEAM_ALIASES` | `scripts/identity_f0_classify.py` |
| `orphan_future_rows.csv` | cele 50 de rânduri viitoare afectate de clasa A | Q4 |
| `baseline_counts.json` | baseline înghețat pentru Poarta 2 | Q2, Q3, Q5 |

## Interogările exacte

Toate sunt `SELECT`. Rulate prin conectorul MCP Supabase.

### Q1 — perechi sufix → bază (produce `suffix_pairs.csv`)
```sql
WITH sides AS (
  SELECT home_team AS team FROM match_history
  UNION ALL SELECT away_team FROM match_history
),
names AS (SELECT DISTINCT team FROM sides),
sfx AS (
  SELECT team AS suffixed,
         regexp_replace(team,'\s*\([A-Z]{2,4}\)$','') AS base,
         substring(team from '\(([A-Z]{2,4})\)$')     AS country_code
  FROM names WHERE team ~ '\([A-Z]{2,4}\)$'
)
SELECT s.suffixed, s.base, s.country_code
FROM sfx s WHERE EXISTS (SELECT 1 FROM names n WHERE n.team = s.base)
ORDER BY s.base, s.suffixed;
```
→ **85 rânduri, 85 baze distincte** (raport 1:1).

### Q2 — dovada de siguranță #1: zero ambiguitate de cod de țară
```sql
WITH sides AS (SELECT home_team AS team FROM match_history
               UNION ALL SELECT away_team FROM match_history),
sfx AS (SELECT DISTINCT team,
               regexp_replace(team,'\s*\([A-Z]{2,4}\)$','') AS base,
               substring(team from '\(([A-Z]{2,4})\)$')     AS cc
        FROM sides WHERE team ~ '\([A-Z]{2,4}\)$')
SELECT base, COUNT(DISTINCT cc) FROM sfx GROUP BY base HAVING COUNT(DISTINCT cc) > 1;
```
→ **0 rânduri.** Niciun nume dezbrăcat nu e produs de două coduri de țară
diferite. Fără această dovadă, regula de strip ar fi putut uni cluburi diferite
(ex. un ipotetic `Nacional (POR)` + `Nacional (URU)`).

### Q3 — dovada de siguranță #2: zero auto-confruntări
```sql
SELECT COUNT(*) FROM match_history
WHERE regexp_replace(home_team,'\s*\([A-Z]{2,4}\)$','')
    = regexp_replace(away_team,'\s*\([A-Z]{2,4}\)$','');
```
→ **0.** Nicăieri în 58.299 de rânduri cele două variante nu joacă una
împotriva celeilalte — ar fi fost dovada că sunt cluburi distincte.

### Q4 — cele 50 de rânduri orfane (produce `orphan_future_rows.csv`)
```sql
SELECT id, fixture_id, home_team, away_team, league, kickoff_date,
       (home_xg_pred IS NOT NULL OR away_xg_pred IS NOT NULL) AS has_xg_pred
FROM match_history
WHERE superseded_by IS NULL AND actual_result IS NULL
  AND ( home_team ~ '\([A-Z]{2,4}\)$' OR away_team ~ '\([A-Z]{2,4}\)$'
     OR home_team IN (<lista A2>) OR away_team IN (<lista A2>) )
ORDER BY kickoff_date, id;
```
→ **50 rânduri.** Verificat prin trei formulări independente (CTE+UNION, CTE
simplu, formă plată). Zero ELO, zero feature-uri de backfill, zero goluri reale,
zero `superseded_by` setat. **8 au `home/away_xg_pred` scris** de
`_cache_prediction()` — deci afirmația „complet fără stare derivată" e falsă.

`<lista A2>` = `'Nottingham','Zwolle','Heerenveen','sc Heerenveen','Schalke',
'FC Schalke 04','Atl. Madrid','B. Monchengladbach','Sittard','For Sittard',
'Leuven','Telstar','Alverca'`

### Q5 — baseline pentru Poarta 2
```sql
-- B1
SELECT COUNT(DISTINCT team) FROM (SELECT home_team AS team FROM match_history
  UNION SELECT away_team FROM match_history) x;                       -- 1252
-- B2
SELECT COUNT(DISTINCT team) FROM (...) WHERE team ~ '\([A-Z]{2,4}\)$'; -- 183
-- B3
SELECT COUNT(*) FROM (SELECT home_team, away_team, LEFT(kickoff_date,10), league
  FROM match_history WHERE superseded_by IS NULL
  GROUP BY 1,2,3,4 HAVING COUNT(*) > 1) x;                            -- 0
```

## Rezultatul clasificării (`class_a_bases.csv`)

| Status | Număr | Ce înseamnă |
|---|---|---|
| `ALREADY_CANONICAL` | **31** | baza e deja cheie în `TEAM_ALIASES` → regula de sufix o rezolvă fără alias nou |
| `NEW_CANONICAL_NEEDED` | **54** | baza există doar de facto în `match_history` → trebuie promovată la canonic |
| `ALIAS_OF_OTHER` | **0** | zero conflicte cu vocabularul existent |
| **Total** | **85** | |

`ALIAS_OF_OTHER = 0` e o dovadă de siguranță în sine: nicio bază propusă nu
intră în conflict cu un alias deja existent.

## Ce NU acoperă acest audit

- Cele **98** nume cu sufix **fără** bază în `match_history` (183 − 85). Nu
  fragmentează nimic azi. Rămân neatinse — regula le lasă neschimbate.
- Clasa B (familii ambigue: `Utrecht`/`FC Utrecht`, `Arouca`/`FC Arouca`,
  `Braga`/`Sp Braga` etc.) — decizie individuală, ADR-059.
- Cele 208 duplicate logice ascunse — Out-of-Scope Discovery #1.
- Fixture-ul de test `shadow-probe-d2b0d9e2` — Out-of-Scope Discovery #3.

## ⚠️ Reproducere — artefactul înregistrează starea DE DINAINTE de F3

`class_a_bases.csv` e o **fotografie a vocabularului la momentul F0**, nu o
interogare vie. Re-rularea clasificatorului cu `mappings.py` de DUPĂ F3 îl
rescrie ca `ALREADY_CANONICAL: 85` — corect ca stare curentă, dar distruge
dovada pe care se sprijină ADR-058 §3.

Pentru a-l regenera fidel:
```bash
git stash push mappings.py          # revino la vocabularul pre-F3
python scripts/identity_f0_classify.py
git stash pop
```
Rezultatul corect: `ALREADY_CANONICAL 31` + `NEW_CANONICAL_NEEDED 54`.
Dacă vezi `85 / 0`, ai rulat peste `mappings.py` post-F3 — reface pașii.

## Reproducerea celorlalte verificări

Interogările Q1-Q5 se re-rulează manual prin conectorul Supabase; cifrele se
compară cu `baseline_counts.json`. Orice divergență = variantă nouă apărută,
investigație obligatorie.
