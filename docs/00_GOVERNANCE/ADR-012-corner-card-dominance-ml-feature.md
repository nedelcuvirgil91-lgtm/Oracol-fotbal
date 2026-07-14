# ADR-012 — Corner/Card Dominance ca feature ML activ

**Status**: Accepted
**Affects**: schema `match_history` (extindere aditivă), `ml_predictor.FEATURE_COLUMNS`
**Authority**: Principal Software Architect

---

## Context

`docs/03_ENGINE/CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md` a demonstrat, prin test de ablație walk-forward pe 5.253 meciuri reale, că `corner_dominance` și `card_diff` (medii glisante reale, ultimele 5 meciuri, derivate din datele populate prin Task 2/ADR-011) îmbunătățesc simultan acuratețea, log-loss și Brier score față de `FEATURE_COLUMNS` actual — condiția explicită de promovare din `CLAUDE.md`.

## Decision

1. **Schema `match_history` se extinde aditiv, cu 4 coloane noi** (medie reală, nu diferență — diferența se calculează la citire, nu se stochează redundant):
   - `home_corner_avg_recent`, `away_corner_avg_recent` (numeric)
   - `home_card_avg_recent`, `away_card_avg_recent` (numeric)

2. **`ml_predictor.FEATURE_COLUMNS` se extinde cu 2 intrări derivate**: `corner_dominance = home_corner_avg_recent - away_corner_avg_recent`, `card_diff = away_card_avg_recent - home_card_avg_recent` — calculate în `_fetch_training_dataframe()`, nu stocate ca atare.

3. **Backfill non-destructiv**, identic tipar cu `ShotsTracker` (`sync/backfill_features.py`), walk-forward, zero scurgere temporală.

4. **Predicții live** (`oracle_engine._build_ml_features()`): aceeași derivare, din același `TeamProfile` extins deja cu `avg_corners`/`avg_fouls`/`avg_yellow_cards` (Task 3).

## Rationale

Primul feature promovat la `FEATURE_COLUMNS` prin dovadă de ablație de la ELO/Formă/H2H — precedent metodologic direct din `REST_DAYS_VALIDATION.md`, aplicat de această dată cu rezultat pozitiv, nu negativ.

## Consequences

- `FEATURE_COLUMNS` are acum 12 intrări (10 existente + 2 noi).
- Orice re-antrenare a modelului de producție după acest ADR va folosi automat noile feature-uri.
- Rândurile de antrenare fără istoric real de cornere/cartonașe primesc `NaN` pentru cele 2 coloane derivate — XGBoost gestionează nativ (missing-value split), nu se aproximează.

## Addendum — aliniere implementare (audit data leakage, 2026-07-14)

`ml_predictor.train()` conținea, până la această dată, o linie moștenită dinaintea acestui ADR (`fillna(df[FEATURE_COLUMNS].median())`) care contrazicea direct decizia de mai sus — impută inclusiv `corner_dominance`/`card_diff` cu mediana globală, în loc să le lase `NaN`. Găsită la un audit de data leakage (mediana era calculată pe tot setul deja sortat cronologic, deci "vedea" segmente viitoare la fold-urile timpurii ale walk-forward validation — o scurgere distinctă de cea de etichete). Corectată: imputarea a fost eliminată complet pentru toate cele 13 coloane din `FEATURE_COLUMNS` (nu doar cele 2 de aici), atât în `train()` cât și în `predict()` — implementarea e acum aliniată cu decizia originală a acestui ADR. Vezi și ADR-013, addendum identic.
