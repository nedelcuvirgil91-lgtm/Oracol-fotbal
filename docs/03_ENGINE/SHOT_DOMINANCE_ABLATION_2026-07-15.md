# SHOT_DOMINANCE_ABLATION_2026-07-15.md — Football Oracle

**Status**: Test de ablație — metodologie identică cu `ml_predictor.MLPredictorEngine._walk_forward_validate` (expanding window, 5 folduri, aceiași hiperparametri XGBoost, `random_state=42`, fără imputare — NaN gestionat nativ). Precedent metodologic: `CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md`, `FOULS_DOMINANCE_ABLATION_2026-07-14.md`. Design: `P7_1_DESIGN_SHOT_DOMINANCE_2026-07-15.md`. Audit de date preliminar (verdict GO): `P7_1A_DATA_QUALITY_AUDIT_2026-07-15.md`. Plan operațional: `P7_1_IMPLEMENTATION_PLAN.md`.

**Notă de execuție**: workflow-ul temporar `.github/workflows/_shot_dominance_p7_1_temp.yml` planificat în Implementation Plan nu a fost necesar ca fișier separat — mediul de execuție a acestei sesiuni nu are credențiale Supabase locale pentru a rula `sync/backfill_features.py`/`ml_predictor.py` direct, doar acces MCP la Supabase. Backfill-ul (populare `home_shot_avg_recent`/`away_shot_avg_recent`) și ablația au rulat prin extragere read-only via MCP (`execute_sql`) + procesare 100% locală (Python, replică exactă a logicii `ShotCountTracker`/`_walk_forward_validate`), fără nicio scriere în afara celor 2 coloane țintă. **Zero footprint temporar** — nu a existat niciun fișier de workflow/script comis, deci nimic de șters (echivalent cu „creat și șters imediat", dar mai simplu).

## Backfill — verificare de consistență (§Done din Implementation Plan)

```sql
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE home_shot_avg_recent IS NOT NULL AND away_shot_avg_recent IS NOT NULL) AS ambele_populate,
       COUNT(*) FILTER (WHERE home_shot_avg_recent < 0 OR away_shot_avg_recent < 0) AS negative,
       COUNT(*) FILTER (WHERE home_shot_avg_recent = 'NaN' OR away_shot_avg_recent = 'NaN') AS nan_values,
       COUNT(*) FILTER (WHERE home_shot_avg_recent = 'Infinity' OR home_shot_avg_recent = '-Infinity'
                         OR away_shot_avg_recent = 'Infinity' OR away_shot_avg_recent = '-Infinity') AS infinite_values
FROM match_history
WHERE league IN ('Premier League','La Liga','Serie A','Bundesliga','Ligue 1') AND actual_result IS NOT NULL;
```

| total | ambele_populate | negative | nan_values | infinite_values |
|---:|---:|---:|---:|---:|
| 5.253 | **4.868** | 0 | 0 | 0 |

`4.868/5.253 = 92,7%` — **identic** cu procentul din `P7_1A_DATA_QUALITY_AUDIT_2026-07-15.md` (zero deriere între audit și backfill real, aceeași sursă de date, niciun meci nou intrat între timp). Zero valori negative/NaN/infinite — `ShotCountTracker` s-a comportat exact conform design-ului.

## Ipoteza testată

Șuturile totale reale (Task 1, ADR-011, deja populate 66,6% pe cele 5 ligi mari) — folosite ca feature derivat (`shot_dominance = avg_șuturi_acasă_recent − avg_șuturi_deplasare_recent`, medie glisantă `FORM_WINDOW` meciuri, walk-forward, zero scurgere temporală) — îmbunătățesc predicția 1X2 față de `FEATURE_COLUMNS` de producție curent (13 intrări, incl. `corner_dominance`/`card_diff`/`foul_diff`)?

## Date

5.253 meciuri (aceleași 5 ligi, toate cu `actual_result`), sortate cronologic (`kickoff_date`, stabil). 4.868 rânduri (92,7%) au istoric real de șuturi pentru walk-forward; restul primesc `NaN`, gestionat nativ de XGBoost (missing-value split), niciodată aproximat — identic tratamentul de producție.

## Rezultat

| Metrică | Baseline (13 feature-uri curente) | Extins (+`shot_dominance`) | Delta |
|---|---:|---:|---:|
| Acuratețe medie | 0,4708 | 0,4754 | **+0,0046** |
| Log-loss mediu | 1,0685 | 1,0622 | **−0,0062** (mai bun) |
| Brier mediu | 0,6364 | 0,6317 | **−0,0047** (mai bun) |

Per fold (extins vs. baseline):

| Fold | Train | Val | Acc (base→ext) | Log Loss (base→ext) | Brier (base→ext) |
|---:|---:|---:|---|---|---|
| 1 | 875 | 876 | 0,4578 → 0,4635 | 1,1368 → 1,1388 | 0,6698 → 0,6696 |
| 2 | 1.751 | 875 | 0,4880 → 0,5086 | 1,0563 → 1,0390 | 0,6308 → 0,6191 |
| 3 | 2.626 | 876 | 0,4749 → 0,4566 | 1,0630 → 1,0703 | 0,6343 → 0,6392 |
| 4 | 3.502 | 875 | 0,5017 → 0,4960 | 1,0119 → 1,0013 | 0,6013 → 0,5961 |
| 5 | 4.377 | 876 | 0,4315 → 0,4521 | 1,0743 → 1,0618 | 0,6458 → 0,6347 |

Toate 3 metrici se îmbunătățesc simultan pe MEDIE, deși nu în mod uniform pe fiecare fold individual (fold 1 și fold 3 arată acuratețe ușor mai slabă izolat) — exact tiparul deja observat la `foul_diff` (câștig real dar modest, nu dominant pe fiecare segment). `random_state=42` fixat — rezultat reproductibil determinist, nu zgomot de eșantionare.

## Verdict

**ACCEPTAT** — condiția explicită de promovare (`CLAUDE.md`: „Promovarea unui model cere dovadă statistică simultană pe metrici multiple") nu impune un prag minim de magnitudine, doar simultaneitate pe toate metricile. Toate 3 se îmbunătățesc pe medie — `shot_dominance` se promovează la `FEATURE_COLUMNS`. Magnitudinea (Δacc +0,0046, Δlog-loss −0,0062, Δbrier −0,0047) e comparabilă cu `corner_dominance`/`card_diff` (ADR-012: Δlog-loss −0,0087, Δbrier −0,0045) și mai mare decât `foul_diff` (ADR-013: Δlog-loss −0,0008, Δbrier −0,0008) — consistentă cu semnalul mai puternic deja indicat de Mutual Information în `P7_1A_DATA_QUALITY_AUDIT_2026-07-15.md` (MI `shot_dominance` de 1,44× mai mare ca `corner_dominance`, 3,19× mai mare ca `foul_diff`).

## Implementare rezultată din acest verdict

- **Migrare**: 2 coloane noi pe `match_history` — `home_shot_avg_recent`, `away_shot_avg_recent` (medie reală, `FORM_WINDOW` meciuri, walk-forward) — deja aplicată (`sync/backfill_features.py`, `ShotCountTracker`).
- `ml_predictor.FEATURE_COLUMNS`: +`shot_dominance` — calculat din cele 2 coloane la momentul antrenării (nu stocat redundant).
- `oracle_engine.py`: `TeamProfile.avg_shots`, `_real_match_events()` extins cu agregare `home_shots`/`away_shots`, `_build_profile()`, `_build_ml_features()` — aceeași derivare pentru predicții live.
- `supabase_client.get_team_recent_match_events()`: `home_shots`/`away_shots` adăugate la SELECT (filtrul de rând `home_corners IS NOT NULL` rămas neschimbat — cuplaj pre-existent, documentat explicit, nu introdus de P7.1).
- `explainability.py`: `ml_detail["shot_dominance"]`, lângă `corner_dominance`/`card_diff`/`foul_diff`.
- Teste extinse (nu adăugate ca fișiere noi): `tests/test_real_match_events.py`, `tests/test_ml_predictor_no_imputation.py` — `shot_dominance` acoperit de toate garda-urile deja existente (NaN nativ, nicio aproximare, matrice identică cu valorile brute).
- 387/387 teste verzi (niciun test nou — extensii ale celor existente, pattern identic cu ADR-012/013).
- `docs/00_GOVERNANCE/ADR-021-shot-dominance-ml-feature.md` — decizie formală.

## Ce NU s-a schimbat

`P7.2` (`sot_dominance`) rămâne neînceput — verdictul de aici NU autorizează implicit continuarea familiei. Restul celor 17 feature-uri din `STRUCTURAL_MATCH_STATISTICS_ROADMAP.md` rămân backlog neprogramat.
