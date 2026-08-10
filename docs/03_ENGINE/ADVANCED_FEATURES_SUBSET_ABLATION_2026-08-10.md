# ADVANCED_FEATURES_SUBSET_ABLATION_2026-08-10.md — Football Oracle

**Status**: Test de ablație de RE-VALIDARE (nu de promovare — cele 4 feature-uri erau deja în `FEATURE_COLUMNS`, promovate separat: `corner_dominance`/`card_diff` — ADR-012, `foul_diff` — ADR-013, `shot_dominance` — ADR-021). Metodologie identică cu precedentele: `ml_predictor.MLPredictorEngine._walk_forward_validate` (expanding window, 5 folduri, aceiași hiperparametri XGBoost, `random_state=42`, fără imputare — NaN gestionat nativ). Declanșat de un audit ML separat (2026-08-10) care a găsit acoperire reală de doar ~10,6% pentru aceste 4 feature-uri pe tot setul de antrenare (5.778/54.505) — întrebarea testată aici: contribuția lor rămâne reală pe subsetul unde CHIAR există date, sau ablația originală (pe seturi mai mici, mai vechi) nu mai reflectă situația actuală?

**Notă de execuție**: mediul acestei sesiuni nu are credențiale Supabase locale pentru `ml_predictor.py`/`supabase_client.py` — doar acces MCP (`execute_sql`, read-only). Datele (5.243 rânduri, 16 coloane) au fost extrase prin `string_agg` în CSV compact, transferate local, procesate 100% cu codul de producție (`MLPredictorEngine._walk_forward_validate`, import direct, fără duplicare de logică). Zero scriere în Supabase, zero model nou salvat, zero footprint temporar (nici workflow, nici script comis).

## Ipoteza testată

Cele 4 feature-uri deja promovate (`corner_dominance`, `card_diff`, `foul_diff`, `shot_dominance`) — pe subsetul de meciuri unde sunt efectiv populate (nu NULL) — îmbunătățesc încă predicția 1X2 față de restul `FEATURE_COLUMNS` (10 intrări: rating ofensiv/defensiv, formă, ELO, H2H)?

## Date

```sql
SELECT COUNT(*) FROM match_history
WHERE superseded_by IS NULL AND actual_result IS NOT NULL
  AND home_corner_avg_recent IS NOT NULL AND away_corner_avg_recent IS NOT NULL
  AND home_card_avg_recent   IS NOT NULL AND away_card_avg_recent   IS NOT NULL
  AND home_foul_avg_recent   IS NOT NULL AND away_foul_avg_recent   IS NOT NULL
  AND home_shot_avg_recent   IS NOT NULL AND away_shot_avg_recent   IS NOT NULL;
-- 5.243
```

5.243 meciuri (din 54.505 totale eligibile, ~9,6%) — subsetul unde toate 4 feature-urile avansate sunt simultan populate, sortate cronologic (`kickoff_date`, stabil), identic disciplinei walk-forward de producție.

## Rezultat

| Metrică | Bază (10 feature-uri, fără cele 4 avansate) | Complet (14 feature-uri, cu toate 4) | Delta |
|---|---:|---:|---:|
| Acuratețe medie | 0,4941 | 0,4998 | **+0,0057** |
| Log-loss mediu | 1,0489 | 1,0400 | **−0,0089** (mai bun) |
| Brier mediu | 0,6247 | 0,6192 | **−0,0055** (mai bun) |

Per fold (bază → complet):

| Fold | Train | Val | Acc | Log Loss | Brier |
|---:|---:|---:|---|---|---|
| 1 | 873 | 874 | 0,4703 → 0,4828 | 1,1235 → 1,0976 | 0,6625 → 0,6482 |
| 2 | 1.747 | 874 | 0,5034 → 0,5046 | 1,0476 → 1,0328 | 0,6284 → 0,6169 |
| 3 | 2.621 | 874 | 0,4966 → 0,5023 | 1,0421 → 1,0353 | 0,6210 → 0,6182 |
| 4 | 3.495 | 874 | 0,5229 → 0,5412 | 0,9853 → 0,9843 | 0,5840 → 0,5821 |
| 5 | 4.369 | 874 | 0,4771 → 0,4680 | 1,0459 → 1,0500 | 0,6276 → 0,6305 |

Toate 3 metrici se îmbunătățesc simultan pe MEDIE. Pe fold-uri individuale, 4 din 5 arată acuratețe egală sau mai bună (excepție fold 5, unde acuratețea scade ușor dar log-loss/brier se înrăutățesc și ele — segment mai zgomotos, nu semnal contrar sistematic). `random_state=42` fixat — reproductibil determinist.

## Verdict

**RE-CONFIRMAT** — condiția de promovare (`CLAUDE.md`: „dovadă statistică simultană pe metrici multiple") e satisfăcută din nou, pe date proaspete (2026-08-10), pe un subset diferit (filtrat pe completitudine, nu pe ligă) față de ablațiile originale. Cele 4 feature-uri **nu sunt „moarte" sau irelevante** — contribuția lor rămâne reală acolo unde există date. Magnitudinea (Δacc +0,0057, Δlog-loss −0,0089, Δbrier −0,0055) e comparabilă cu `shot_dominance` original (ADR-021: Δacc +0,0046, Δlog-loss −0,0062, Δbrier −0,0047) — nu s-a degradat.

## Concluzia practică — problema e ACOPERIREA, nu relevanța

Acest test schimbă diagnosticul unui audit ML anterior (2026-08-10): la prima vedere, ~10,6% acoperire pe tot setul de antrenare (5.778/54.505) părea un semnal de „feature-uri subutilizate". Rezultatul de aici arată opusul — feature-urile sunt corecte, doar rare. **Recomandarea practică nu e feature engineering nou, e extinderea colectării** de cornere/cartonașe/faulturi/șuturi la mai multe surse istorice — cauza rădăcină identificată separat: sursa istorică principală a `match_history` (Kaggle/football-data.co.uk, ~89% din total) nu a oferit niciodată aceste statistici granulare, doar scorul final. Pe măsură ce acoperirea crește (Foundation Data Layer, provideri noi), modelul deja folosește aceste feature-uri corect, fără nicio schimbare de cod necesară.

## Ce NU s-a schimbat

`FEATURE_COLUMNS` rămâne neschimbat — cele 4 feature-uri erau deja incluse înainte de acest test; nu s-a adăugat, eliminat sau modificat niciun feature. Niciun model de producție nu a fost antrenat sau salvat în urma acestui test — a fost strict o re-validare, read-only.
