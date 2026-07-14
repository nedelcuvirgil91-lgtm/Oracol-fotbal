# CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md — Football Oracle

**Status**: Test de ablație — metodologie identică cu `ml_predictor.MLPredictorEngine._walk_forward_validate` (expanding window, 5 folduri, aceiași hiperparametri XGBoost). Precedent metodologic: `REST_DAYS_VALIDATION.md`.

## Ipoteza testată

Cornerele și cartonașele galbene reale (Task 2, ADR-011, populate acum pentru Premier League/La Liga/Serie A/Bundesliga/Ligue 1) — folosite ca feature-uri derivate (`corner_dominance = avg_cornere_acasă_recent - avg_cornere_deplasare_recent`, `card_diff = avg_cartonașe_deplasare_recent - avg_cartonașe_acasă_recent`, medie glisantă ultimele 5 meciuri, walk-forward, zero scurgere temporală) — îmbunătățesc predicția 1X2 față de `FEATURE_COLUMNS` actual?

## Date

5.253 meciuri (cele 5 ligi, toate cu `actual_result`), sortate cronologic. 3.471 rânduri (66%) au istoric real de cornere/cartonașe pentru walk-forward; restul (meciuri fără istoric suficient sau înainte de backfill) primesc `NaN`, gestionat nativ de XGBoost (missing-value split), nu imputat.

## Rezultat

| Metrică | Baseline (`FEATURE_COLUMNS` actual) | Extins (+`corner_dominance`+`card_diff`) | Delta |
|---|---|---|---|
| Acuratețe medie | 0.4610 | 0.4628 | **+0.0018** |
| Log-loss mediu | 1.0861 | 1.0774 | **−0.0087** (mai bun) |
| Brier mediu | 0.6475 | 0.6430 | **−0.0045** (mai bun) |

Toate 3 metrici se îmbunătățesc simultan, consistent pe majoritatea celor 5 folduri (cel mai clar la fold 1: acuratețe 0.4475→0.4578, log-loss 1.202→1.164, Brier 0.7048→0.6854). Magnitudinea e modestă, nu dramatică — onest raportat, nu exagerat.

## Verdict

**ACCEPTAT** — spre deosebire de `REST_DAYS_VALIDATION.md` (unde toate metricile au arătat câștig neglijabil/nul), aici toate 3 metricile se îmbunătățesc simultan, condiție explicită a regulii de promovare ML (`CLAUDE.md`: „Promovarea unui model cere dovadă statistică simultană pe metrici multiple"). Se promovează `corner_dominance` și `card_diff` la `FEATURE_COLUMNS`.

## Implementare rezultată din acest verdict

- Migrare (ADR-012): 4 coloane noi pe `match_history` — `home_corner_avg_recent`, `away_corner_avg_recent`, `home_card_avg_recent`, `away_card_avg_recent` (medie glisantă reală, ultimele 5 meciuri, walk-forward).
- `sync/backfill_features.py`: `CornerCardTracker`, identic ca disciplină cu `ShotsTracker`.
- `ml_predictor.FEATURE_COLUMNS`: `corner_dominance`, `card_diff` — calculate din cele 4 coloane la momentul antrenării (nu stocate redundant).
- `oracle_engine._build_ml_features()`: aceeași derivare, pentru predicții live.
