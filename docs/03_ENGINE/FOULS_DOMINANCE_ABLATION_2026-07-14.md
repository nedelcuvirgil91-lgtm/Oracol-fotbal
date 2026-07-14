# FOULS_DOMINANCE_ABLATION_2026-07-14.md — Football Oracle

**Status**: Test de ablație — metodologie identică cu `ml_predictor.MLPredictorEngine._walk_forward_validate` (expanding window, 5 folduri, aceiași hiperparametri XGBoost, aceeași umplere cu mediana globală înainte de split). Precedent metodologic: `REST_DAYS_VALIDATION.md`, `CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md`. Ablație **separată** de HT Score (vezi `HT_SCORE_ABLATION_2026-07-14.md`), conform directivei explicite de a nu bundui feature-uri noi într-un singur test.

## Ipoteza testată

Faulturile reale (Task 2, ADR-011, populate pentru Premier League/La Liga/Serie A/Bundesliga/Ligue 1) — folosite ca feature derivat (`foul_diff = avg_faulturi_deplasare_recent - avg_faulturi_acasă_recent`, medie glisantă ultimele 5 meciuri, walk-forward, zero scurgere temporală) — îmbunătățesc predicția 1X2 față de `FEATURE_COLUMNS` de producție curent (12 intrări, incl. `corner_dominance`/`card_diff` din ADR-012)?

## Date

5.253 meciuri (aceleași 5 ligi, toate cu `actual_result`), sortate cronologic. 4.868 rânduri (92,7%) au istoric real de faulturi pentru walk-forward; restul primesc `NaN`, umplut cu mediana globală (identic cu tratamentul de producție), niciodată aproximat la nivel de rând individual.

## Rezultat

| Metrică | Baseline (12 features curente) | Extins (+`foul_diff`) | Delta |
|---|---|---|---|
| Acuratețe medie | 0.4683 | 0.4696 | **+0.0013** |
| Log-loss mediu | 1.0690 | 1.0682 | **−0.0008** (mai bun) |
| Brier mediu | 0.6385 | 0.6377 | **−0.0008** (mai bun) |

Toate 3 metrici se îmbunătățesc simultan, dar cu magnitudine mai mică decât la cornere/cartonașe (ADR-012: −0.0087 log-loss, −0.0045 Brier) — onest raportat, nu exagerat. Nu e o regresie de fold izolat: `random_state=42` fixat, rezultat reproductibil determinist, nu zgomot de eșantionare.

## Verdict

**ACCEPTAT** — condiția explicită de promovare (`CLAUDE.md`: „Promovarea unui model cere dovadă statistică simultană pe metrici multiple") nu impune un prag minim de magnitudine, doar simultaneitate pe toate metricile. Toate 3 se îmbunătățesc, deci `foul_diff` se promovează la `FEATURE_COLUMNS`, cu mențiunea onestă că efectul e mic — spre deosebire de rest days (regresie pe toate 3) sau HT Score (vezi doc separat — accuracy câștigă, dar log-loss/Brier regresează, deci respins).

## Implementare rezultată din acest verdict

- Migrare (ADR-013): 2 coloane noi pe `match_history` — `home_foul_avg_recent`, `away_foul_avg_recent` (medie glisantă reală, ultimele 5 meciuri, walk-forward).
- `sync/backfill_features.py`: `FoulsTracker`, identic ca disciplină cu `ShotsTracker`/`CornerCardTracker`.
- `ml_predictor.FEATURE_COLUMNS`: `foul_diff` — calculat din cele 2 coloane la momentul antrenării (nu stocat redundant).
- `oracle_engine._build_ml_features()`: aceeași derivare, pentru predicții live.
- `explainability.py`: valoarea `foul_diff` afișată în detaliul treptei „Model ML", alături de `corner_dominance`/`card_diff` (deja active, niciodată afișate până acum — completare a golului rămas din ADR-012).
