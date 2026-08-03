# Oracle Insight — dublă numărare `avg_goals_for` + candidat de recalibrare `goals_weight` (0.45 → 0.75)

**Status**: Insight documentat, 2026-08-03 (EPIC „ML Activation & Oracle Evolution", Pasul 8) — **investigație completă, cod NEAPLICAT**. Bugul de dublă numărare rămâne confirmat, dar nerezolvat în cod, per decizia explicită a proprietarului produsului. Recalibrarea `goals_weight` → 0.75 e un **candidat** validat prin backtest, nu o schimbare aplicată — orice modificare a parametrilor matematici Oracle e tratată ca experiment de calibrare separat, cu propria aprobare. Vezi **FOLLOW-UP-P8-01 — Oracle Calibration**, task viitor, neînceput.

**Nu e un „bug acceptat"** din punct de vedere arhitectural — analiza demonstrează că trebuie eliminat. Dar eliminarea lui fără compensare degradează Oracle (§2), iar compensarea (recalibrarea `goals_weight`) e o schimbare de model, nu un bug fix — motiv pentru care nu a fost aplicată în acest task.

**Regulă de proiect stabilită prin acest caz** (permanentă, vezi CLAUDE.md): dacă un bug produce empiric performanță mai bună, nu se păstrează bugul — se identifică explicit informația utilă pe care o introduce (analiză cauzală, nu doar corelație) și se documentează ca „Oracle Insight". Dar bug fix-urile nu introduc schimbări de model: orice modificare a parametrilor matematici ai Oracle (recalibrare de pondere, prag, cap) — chiar dacă rezolvă corect regresia cauzată de eliminarea bugului și e validată prin backtest — e tratată ca experiment de calibrare separat, cu propriul review și propria aprobare explicită, niciodată bundle-uit tacit în task-ul de fix. Un backtest favorabil nu e, singur, suficient pentru a schimba formula Oracle.

---

## 1. Bugul original (confirmat, neatins în cod)

`feature_engine.compute_team_offdef_rating()` conține un termen duplicat, prezent azi în producție, neschimbat de acest task:

```python
off_stat = min(
    g_norm * goals_weight + sot_norm * shots_ot_weight + pos_norm * possession_weight
    + avg_goals_for * 0.2,           # <- dublă numărare, confirmată, NEELIMINATĂ
    offensive_cap,
)
```

`avg_goals_for` intră de două ori: normalizat/capat prin `g_norm * goals_weight` (configurabil), și brut, necapat, cu pondere hardcodată `0.2` (invizibilă din configurare).

## 2. De ce bugul, empiric, ajută predicția

Testat pe 4849 de meciuri reale (walk-forward, 2025-02→2026-08), împărțind meciurile după dacă vreo echipă avea `avg_goals_for >= 2.0` (pragul de saturație al `g_norm`):

| Subgrup | % din total | Cu bug (accuracy) | Fără bug, fără compensare (accuracy) |
|---|---|---|---|
| Saturate (≥2.0) | 34.4% | 0.5392 | 0.5452 (mai bun **fără** bug) |
| Sub prag (<2.0) | 65.6% | 0.4711 | 0.4635 (mai bun **cu** bug) |

**Ipoteza inițială — că bugul ajută prin „bypass" de cap pentru echipe foarte ofensive — a fost testată și infirmată.** Beneficiul e concentrat exact acolo unde niciun cap nu e implicat: în cele 65.6% din meciuri sub prag, unde `g_norm` funcționează normal. Un candidat de „componentă separată" (bonus doar peste prag, testat explicit) a performat **mai slab** decât chiar eliminarea simplă a bugului (acc=0.4908 vs 0.4916) — confirmă că nu există un semnal ascuns distinct.

**Concluzia reală**: `goals_weight=0.45` pare subponderat pe întreg spectrul de date, nu doar la extreme. Golurile marcate recent ar merita, posibil, mai multă influență predictivă decât configurează azi această valoare — dar asta e o ipoteză de calibrare, nu o certitudine care justifică schimbarea imediată a formulei.

## 3. Formula candidat (propusă, NEAPLICATĂ)

Structural identică cu formula corectă, arhitectural curată — `avg_goals_for` ar apărea o singură dată, prin `g_norm * goals_weight`, capul `offensive_cap`/`g_norm` complet intacte:

```python
off_stat = min(
    g_norm * goals_weight + sot_norm * shots_ot_weight + pos_norm * possession_weight,
    offensive_cap,
)
```

Schimbarea propusă (dar **neaplicată**): `DEFAULT_WEIGHTS["goals_weight"]` (`oracle_engine.py`) și cheia globală `goals_weight` (`weights.json`) recalibrate de la `0.45` la **`0.75`**. Codul actual din producție rămâne neschimbat — vezi Status.

## 4. De ce `0.75` a fost candidatul preferat, nu `0.7167` (valoarea derivată din elasticitatea bugului)

Un sweep pe `goals_weight ∈ [0.45, 0.90]` (aceleași 4849 meciuri) arată un platou optim între 0.70-0.80:

| `goals_weight` | 0.45 | 0.60 | 0.70 | 0.7167 | **0.75** | 0.80 | 0.90 |
|---|---|---|---|---|---|---|---|
| accuracy | 0.4916 | 0.4952 | 0.4960 | 0.4962 | **0.4966** | 0.4958 | 0.4941 |

`0.75` e vârful empiric al sweep-ului (nu doar o valoare care replică artificial panta bugului) — ar fi o valoare rotundă din platoul optim, nu o constantă derivată mecanic dintr-un calcul de elasticitate. Rămâne un candidat pentru un viitor task de calibrare, nu o valoare adoptată.

## 5. Ce nu a fost și nu ar fi fost atins (scop deliberat restrâns, dacă s-ar aplica vreodată)

- **Ponderile `goals_weight` per-ligă** (`oracle_engine.py`, liniile 188-198, `weights.json::league_weights`) — neatinse. Sunt deja confirmate inerte (`ORACLE_ENGINE_AUDIT.md` §4.3, Pasul 1: `sample_count=0` pentru toate cele 11 ligi → `resolve_league_weights()` returnează azi 100% ponderile globale). Recalibrarea lor rămâne o decizie separată, condiționată de activarea `auto_recalibration_enabled` — neinclusă în acest task.
- `FEATURE_COLUMNS` (ML) — neatins, `avg_goals_for` din acest context e complet separat de feature-urile ML.
- `sot_norm`/`pos_norm`/`shots_ot_weight`/`possession_weight` — neatinse.

## 6. Rezultatele backtestului pe candidatul testat (`goals_weight=0.75`, fără termen duplicat) — informativ, NU a devenit baseline

Backtest identic metodologic cu cel din §2 (walk-forward, cod real de producție ca punct de plecare, 4849 meciuri), rulat pentru a evalua dacă acest candidat ar fi, cel puțin, la egalitate cu formula curentă — **rezultat informativ, nu a fost aplicat, formula de producție rămâne cea din §1**:

| Metrică | Formulă actuală (cu bug, live) | Candidat testat (`goals_weight=0.75`, fără termen duplicat) | Delta |
|---|---|---|---|
| Accuracy | 0.4945 | 0.4966 | +0.0021 |
| Brier Score | 0.6088 | 0.6089 | +0.0001 (statistic identic) |
| Log Loss | 1.0163 | 1.0164 | +0.0001 (statistic identic) |
| Calibrare (gap mediu / maxim) | 0.0065 / 0.0141 | 0.0103 / 0.0197 | ușor mai slabă, tot excelentă (<2pp) |
| Prediction Stability | — | 99.15% etichete identice, shift mediu 0.0053 | schimbare minimă |

Pe toate cele 5 dimensiuni cerute, candidatul testat a fost cel puțin la nivelul formulei actuale, cu accuracy vizibil mai bun. Acest rezultat **nu e suficient, singur**, pentru a schimba formula Oracle — devine input pentru FOLLOW-UP-P8-01, unde se va analiza suplimentar: dacă 0.75 e într-adevăr optim; dacă optimul diferă pe ligi; dacă e stabil în timp (rolling windows); dacă nu reprezintă overfitting pe perioada folosită (2025-02→2026-08).

## 7. Metodologie (transparență, limitări)

- Date: `match_history` (Supabase), 6000 rânduri chronologice (2025-02→2026-08), `avg_goals_for`/`avg_goals_against` reconstruite direct din rezultatele brute ale ultimelor `last_n_fixtures=5` meciuri (walk-forward, fără scurgere temporală) — nu din coloanele deja cache-uite `home_offensive_rating`, care conțin deja bugul și nu pot fi „de-contaminate" algebric.
- `avg_shots_on_target`/`avg_possession`: indisponibile istoric pentru majoritatea rândurilor → fallback identic cu cel din producție (`sot=avg_goals_for*0.45`, `possession=50.0`).
- ELO și H2H: cache-uite, reale, neatinse de acest bug.
- Regresie funcțională: `pytest tests/test_predictor_regression_suite.py` rulat pe candidatul testat în timpul investigației a arătat 18/61 scenarii cu drift față de golden snapshot — comportament **așteptat** dacă formula ar produce legitim alte valori. Golden-urile NU au fost regenerate — codul de producție nu a fost schimbat, deci suita rămâne verde față de implementarea actuală.
