# HT_SCORE_ABLATION_2026-07-14.md — Football Oracle

**Status**: Test de ablație — metodologie identică cu `ml_predictor.MLPredictorEngine._walk_forward_validate` (expanding window, 5 folduri, aceiași hiperparametri XGBoost, aceeași umplere cu mediana globală înainte de split). Precedent metodologic: `REST_DAYS_VALIDATION.md`. Ablație **separată** de Faulturi (vezi `FOULS_DOMINANCE_ABLATION_2026-07-14.md`).

## Ipoteza testată

Golurile la pauză reale (HT Score, Task 2, ADR-011, populate pentru cele 5 ligi) — folosite ca feature derivat (`ht_goal_diff = avg_gol_pauză_acasă_recent - avg_gol_pauză_deplasare_recent`, medie glisantă ultimele 5 meciuri, walk-forward, zero scurgere temporală) — îmbunătățesc predicția 1X2 față de `FEATURE_COLUMNS` de producție curent (12 intrări, incl. `corner_dominance`/`card_diff` din ADR-012)?

## Date

Aceleași 5.253 meciuri ca ablația Faulturi. 4.868 rânduri (92,7%) au istoric real de gol-la-pauză pentru walk-forward; restul primesc `NaN`, umplut cu mediana globală.

## Rezultat

| Metrică | Baseline (12 features curente) | Extins (+`ht_goal_diff`) | Delta |
|---|---|---|---|
| Acuratețe medie | 0.4683 | 0.4719 | **+0.0036** |
| Log-loss mediu | 1.0690 | 1.0707 | **+0.0017** (mai slab) |
| Brier mediu | 0.6385 | 0.6394 | **+0.0009** (mai slab) |

Acuratețea crește (cel mai mare câștig dintre toate feature-urile testate până acum: corner/card, faulturi, HT score), dar log-loss și Brier **regresează** ambele — modelul devine mai puțin bine calibrat, chiar dacă alege mai des clasa corectă. Pattern clasic de overfitting/supraîncredere pe un semnal parțial (92,7% acoperire, restul NaN), consistent pe majoritatea foldurilor (nu doar unul izolat).

## Verdict

**RESPINS** — condiția explicită de promovare (`CLAUDE.md`: „Promovarea unui model cere dovadă statistică simultană pe metrici multiple — niciodată o singură metrică") nu e îndeplinită: doar acuratețea se îmbunătățește, log-loss și Brier regresează amândouă. Exact genul de rezultat pe care regula e concepută să respingă — o metrică bună nu e suficientă, oricât de tentantă (acuratețea e cea mai mare îmbunătățire văzută până acum).

Nu se implementează `ht_goal_diff` ca feature ML. Coloanele brute `home_ht_goals`/`away_ht_goals` rămân disponibile (ADR-011) și `avg_ht_goals` rămâne afișat informativ în Team DNA (Streamlit) și pe `TeamProfile`, exact ca `avg_fouls`/`avg_corners`/`avg_yellow_cards` înainte de propria lor promovare — fără nicio coloană derivată nouă în `match_history`, fără intrare în `FEATURE_COLUMNS`.

## Cum am relua, dacă totuși s-ar reîncerca

Nu propun implementare acum, dar dacă s-ar relua: (a) test cu un prag minim de acoperire mai mare (ex. doar meciuri cu istoric complet, nu fillna cu mediana); (b) feature binar/categoric (ex. "tendință de a marca devreme") în loc de diferență continuă, care ar putea reduce supraîncrederea; (c) interacțiune cu `corner_dominance` (echipele ofensive de la 0 minut ar putea coincide cu presiune ridicată = cornere multe), nu doar efect aditiv separat.
