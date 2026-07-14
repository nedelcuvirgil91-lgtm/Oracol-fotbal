# ADR-013 — Faulturi (`foul_diff`) ca feature ML activ

**Status**: Accepted
**Affects**: schema `match_history` (extindere aditivă), `ml_predictor.FEATURE_COLUMNS`, `explainability.py`
**Authority**: Principal Software Architect

---

## Context

`docs/03_ENGINE/FOULS_DOMINANCE_ABLATION_2026-07-14.md` a demonstrat, prin test de ablație walk-forward pe 5.253 meciuri reale, că `foul_diff` (diferență de medii glisante reale de faulturi, ultimele 5 meciuri, derivate din datele populate prin Task 2/ADR-011) îmbunătățește simultan acuratețea, log-loss și Brier score față de `FEATURE_COLUMNS` actual (care deja include `corner_dominance`/`card_diff` din ADR-012) — condiția explicită de promovare din `CLAUDE.md`. Magnitudinea e mică, raportată onest ca atare, dar simultaneitatea pe toate 3 metrici e regula, nu magnitudinea.

Testat în paralel, dar SEPARAT (test independent, nu bundle), `ht_goal_diff` (HT Score) a fost **respins** — vezi `docs/03_ENGINE/HT_SCORE_ABLATION_2026-07-14.md`: acuratețea crește, dar log-loss și Brier regresează, deci nu îndeplinește regula de simultaneitate.

## Decision

1. **Schema `match_history` se extinde aditiv, cu 2 coloane noi**:
   - `home_foul_avg_recent`, `away_foul_avg_recent` (numeric) — medie reală, nu diferență.

2. **`ml_predictor.FEATURE_COLUMNS` se extinde cu 1 intrare derivată**: `foul_diff = away_foul_avg_recent - home_foul_avg_recent` — calculată în `_fetch_training_dataframe()`, nu stocată ca atare.

3. **Backfill non-destructiv**, identic tipar cu `ShotsTracker`/`CornerCardTracker` (`sync/backfill_features.py`), walk-forward, zero scurgere temporală.

4. **Predicții live** (`oracle_engine._build_ml_features()`): aceeași derivare, din același `TeamProfile` extins deja cu `avg_fouls` (Task 3, deja existent — doar neconectat la ML până acum).

5. **Explainability** (`explainability.py`): treapta „Model ML" din cascadă își extinde `detail` cu valorile brute `corner_dominance`, `card_diff` și `foul_diff` folosite efectiv de model — completează golul rămas din ADR-012 (aceste feature-uri erau active în model dar niciodată afișate în explicație).

## Rationale

Al doilea feature promovat la `FEATURE_COLUMNS` prin dovadă de ablație de la corner/card dominance — precedent metodologic direct din `CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md`. Testat separat de HT Score, conform directivei explicite de a nu combina evaluări — permite o decizie curată per feature (unul acceptat, unul respins, în același sprint).

## Consequences

- `ml_predictor.FEATURE_COLUMNS` are acum 13 intrări (12 existente + `foul_diff`).
- `sync/backfill_features.FEATURE_COLUMNS` (target de backfill) are acum 16 intrări (14 existente + cele 2 coloane brute de faulturi).
- Orice re-antrenare a modelului de producție după acest ADR va folosi automat noul feature.
- Rândurile de antrenare fără istoric real de faulturi primesc `NaN` pentru `foul_diff` — XGBoost gestionează nativ (missing-value split), nu se aproximează.
- `ht_goal_diff` NU se implementează — rămâne respins per `HT_SCORE_ABLATION_2026-07-14.md`. Coloanele brute `home_ht_goals`/`away_ht_goals` (ADR-011) și `avg_ht_goals` (informativ, `TeamProfile`) rămân neschimbate, fără nicio coloană derivată nouă.
