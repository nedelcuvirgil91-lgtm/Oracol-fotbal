# ADR-021 — Șuturi totale (`shot_dominance`) ca feature ML activ

**Status**: Accepted
**Affects**: schema `match_history` (extindere aditivă), `ml_predictor.FEATURE_COLUMNS`, `oracle_engine.TeamProfile`/`_build_ml_features`, `supabase_client.get_team_recent_match_events`, `explainability.py`
**Authority**: Principal Software Architect

---

## Context

`docs/03_ENGINE/SHOT_DOMINANCE_ABLATION_2026-07-15.md` a demonstrat, prin test de ablație walk-forward pe 5.253 meciuri reale, că `shot_dominance` (diferență de medii glisante reale de șuturi totale, `FORM_WINDOW` meciuri, derivate din datele populate prin `ShotCountTracker`) îmbunătățește simultan acuratețea, log-loss și Brier score față de `FEATURE_COLUMNS` actual (13 intrări, incl. `corner_dominance`/`card_diff` din ADR-012, `foul_diff` din ADR-013) — condiția explicită de promovare din `CLAUDE.md`.

Precondiții îndeplinite, în ordine (`P7_1_IMPLEMENTATION_PLAN.md`):
1. Design (`P7_1_DESIGN_SHOT_DOMINANCE_2026-07-15.md`) — definiție exactă, evitare leakage, plan de ablație.
2. Audit de calitate a datelor (`P7_1A_DATA_QUALITY_AUDIT_2026-07-15.md`) — verdict GO: coverage 92,7%, distribuție cu răspândire reală, nicio corelație ≥0,9 cu feature existent, Mutual Information mai mare decât `corner_dominance`/`foul_diff`.
3. Implementation Plan aprobat, cu 2 ajustări (fereastră parțială explicit documentată, sanity check post-backfill).
4. Implementare infrastructură (`ShotCountTracker`, migrare, wiring `backfill_features.py`) — inert pentru producție.
5. Backfill pe producție — verificat: 4.868/5.253 (92,7%), zero valori negative/NaN/infinite.
6. Ablație oficială — toate 3 metrici îmbunătățite simultan.

## Decision

1. **Schema `match_history` s-a extins aditiv, cu 2 coloane noi** (deja aplicate): `home_shot_avg_recent`, `away_shot_avg_recent` (numeric) — medie reală, nu diferență.

2. **`ml_predictor.FEATURE_COLUMNS` se extinde cu 1 intrare derivată**: `shot_dominance = home_shot_avg_recent - away_shot_avg_recent` — calculată în `_fetch_training_dataframe()`, nu stocată ca atare.

3. **Backfill non-destructiv**, identic tipar cu `ShotsTracker`/`CornerCardTracker`/`FoulsTracker` (`sync/backfill_features.py`, clasă nouă `ShotCountTracker`, distinctă deliberat de `ShotsTracker` existent care calculează de fapt `shots_on_target`), walk-forward, zero scurgere temporală.

4. **Predicții live** (`oracle_engine._build_ml_features()`): aceeași derivare, din `TeamProfile.avg_shots` (nou), populat de `_build_profile()` din `_real_match_events()` extins cu agregare `home_shots`/`away_shots`.

5. **Explainability** (`explainability.py`): treapta „Model ML" din cascadă își extinde `detail` cu `shot_dominance`, lângă `corner_dominance`/`card_diff`/`foul_diff`.

## Rationale

Al patrulea feature promovat la `FEATURE_COLUMNS` prin dovadă de ablație, respectând explicit disciplina „un singur feature nou pe rundă" impusă de Chief Architect pentru familia „Structural Match Statistics" (spre deosebire de implementarea simultană a tuturor celor 17 feature-uri propuse în `STRUCTURAL_MATCH_STATISTICS_ROADMAP.md`). Precedent metodologic direct din `CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md`/`FOULS_DOMINANCE_ABLATION_2026-07-14.md`. Magnitudinea câștigului (Δlog-loss −0,0062, Δbrier −0,0047) e comparabilă cu `corner_dominance`/`card_diff`, mai mare decât `foul_diff` — consistentă cu semnalul de Mutual Information mai puternic identificat în auditul preliminar.

## Consequences

- `ml_predictor.FEATURE_COLUMNS` are acum 14 intrări (13 existente + `shot_dominance`).
- `sync/backfill_features.FEATURE_COLUMNS` (target de backfill) are acum 18 intrări (16 existente + cele 2 coloane brute de șuturi).
- Orice re-antrenare a modelului de producție după acest ADR va folosi automat noul feature.
- Rândurile de antrenare fără istoric real de șuturi primesc `NaN` pentru `shot_dominance` — XGBoost gestionează nativ (missing-value split), nu se aproximează.
- Calea live (`_real_match_events`) moștenește un cuplaj pre-existent: filtrul de rând rămâne `home_corners IS NOT NULL`, deci `avg_shots` se calculează doar din rândurile care au ȘI cornere populate — limitare cunoscută, documentată explicit în `supabase_client.get_team_recent_match_events()`, NU introdusă de acest ADR, NU rezolvată aici (schimbarea filtrului de rând ar atinge comportamentul deja validat prin ablație al `corner_dominance`/`foul_diff` — risc scos explicit din scopul P7.1).
- **P7.2 (`sot_dominance`) rămâne neînceput** — acest ADR NU autorizează implicit continuarea familiei „Structural Match Statistics". Verdictul P7.2 necesită propriul plan de ablație, separat, pornit doar la aprobare explicită.
- Restul celor 17 feature-uri din `STRUCTURAL_MATCH_STATISTICS_ROADMAP.md` (`shot_accuracy`, `finishing_efficiency`, `opponent_shot_pressure` etc.) rămân backlog neprogramat.
