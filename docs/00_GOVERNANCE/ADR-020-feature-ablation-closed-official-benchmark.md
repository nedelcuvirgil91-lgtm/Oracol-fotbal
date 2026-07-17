# ADR-020 — Studiu de ablație închis, FEATURE_COLUMNS neschimbat, benchmark oficial stabilit

**Status**: Decis
**Affects**: `ml_predictor.FEATURE_COLUMNS`, orice optimizare viitoare a modelului ML
**Authority**: Principal Software Architect

---

## Context

După închiderea Learning Core (ADR-019) și eliminarea unei scurgeri reale de informație din preprocesare (imputare cu mediană globală în `ml_predictor.train()`/`predict()`, corectată — vezi addendum-urile din ADR-012/ADR-013), s-a stabilit un benchmark oficial curat, validat pe infrastructură reală (53.409 meciuri, walk-forward, 5 folduri):

```
Accuracy   : 0.4868
Log Loss   : 1.0253
Brier Score: 0.6145
```

Pe baza acestui benchmark, s-a rulat un audit complet de calitate a modelului, în trei etape, toate contra infrastructurii reale de producție, exclusiv read-only (workflow-uri temporare `workflow_dispatch`, șterse imediat după rulare):

1. **Audit de feature importance** — gain importance (model final) + permutation importance (calculată pe segmentul de validare al fiecărui fold walk-forward, nu pe train, 10 repetiții/fold, medie+deviație standard între folduri) + matrice de corelații Pearson, pentru toate cele 13 coloane din `FEATURE_COLUMNS`. Rezultat: 3 `CRITICAL` (`home_elo`, `away_elo`, `away_offensive_rating`), 4 `KEEP`, 6 `ABLATION CANDIDATE` (`h2h_modifier`, `home_form_score`, `corner_dominance`, `foul_diff`, `h2h_meetings`, `card_diff`). Nicio pereche de corelație cu |r| > 0.90.

2. **Studiu de ablație** — 6 experimente independente (o singură feature eliminată per experiment, niciodată cumulativ), comparate cu benchmark-ul oficial:

   | Feature eliminată | Δ Accuracy | Δ Log Loss | Δ Brier | Semnal |
   |---|---|---|---|---|
   | card_diff | −0.0005 | −0.0001 | −0.0001 | fără degradare |
   | h2h_meetings | +0.0009 | −0.0004 | −0.0003 | fără degradare (îmbunătățire pe toate 3) |
   | foul_diff | −0.0002 | +0.0000 | +0.0000 | fără degradare (neutru) |
   | corner_dominance | −0.0004 | +0.0003 | +0.0001 | fără degradare |
   | home_form_score | −0.0014 | +0.0006 | +0.0003 | degradare semnalată |
   | h2h_modifier | −0.0007 | +0.0007 | +0.0003 | fără degradare (cel mai slab semnal Log Loss din lot) |

   Redistribuire gain importance minimă în toate experimentele (mișcări de maxim 2 poziții, exclusiv între feature-uri deja slabe) — nicio dovadă de compensare structurală între feature-uri.

## Decision

**Nu se elimină nicio feature din `FEATURE_COLUMNS`.** În particular, se păstrează explicit `h2h_meetings`, `card_diff`, `foul_diff` — deși nu aduc un câștig demonstrat de performanță, motivul păstrării NU e performanța, ci:

1. Nu produc degradare semnificativă a benchmark-ului oficial.
2. Nu introduc data leakage (confirmat la auditul de leakage anterior).
3. Nu produc cost operațional relevant (timp de antrenare neschimbat semnificativ, ~6s per experiment de ablație).
4. Pot deveni utile în viitoare versiuni ale modelului (feature engineering extins — arbitri, disciplină, pressing, Understat).
5. Costul păstrării lor e practic zero.

**Principiu arhitectural, aplicabil de acum înainte**: nu se elimină o feature doar pentru că e „neutră" la permutation importance. Eliminarea unei feature din `FEATURE_COLUMNS` cere cel puțin una dintre următoarele, demonstrată explicit, nu presupusă:

- produce degradare măsurabilă a benchmark-ului oficial;
- introduce data leakage;
- e structural greșită (calculată incorect, scurgere temporală, etc.);
- are cost operațional semnificativ;
- împiedică dezvoltarea arhitecturii.

`home_form_score` (singura cu degradare semnalată peste prag) și `h2h_modifier` (sub prag, dar cel mai slab semnal Log Loss din lot, cu discrepanță reală gain-vs-permutation) rămân de asemenea neschimbate — investigația nu găsește motiv suficient pentru eliminare, conform principiului de mai sus (fiind „doar" neutre/slabe, nu îndeplinesc niciuna dintre cele 5 condiții).

**Studiul de ablație pe aceste 6 feature-uri se închide definitiv.** Nu se mai investește timp în ablația lor. O eventuală ablație cumulativă (toate 6 eliminate simultan, pentru a verifica compensare reciprocă) rămâne o investigație separată, viitoare, neprogramată azi.

## Rationale

Un feature neutru nu e un feature dăunător. Eliminarea lui ar reduce complexitatea cu zero câștig demonstrat de performanță, în schimbul pierderii unei opțiuni ieftine (feature deja calculată, testată, fără cost) pentru extensii viitoare ale feature engineering-ului. Costul unei decizii greșite de eliminare (a rescrie/reintroduce feature-ul mai târziu, cu tot procesul de validare aferent) depășește cu mult costul păstrării lui azi.

## Consequences

- **Benchmark-ul oficial (Accuracy 0.4868 / Log Loss 1.0253 / Brier 0.6145, walk-forward, 53.409 meciuri, fără leakage cunoscut) devine baseline-ul permanent al proiectului.** Orice modificare viitoare asupra `FEATURE_COLUMNS` — adăugare sau eliminare — necesită dovadă experimentală (test de ablație/adăugare walk-forward, pe date reale) că rezultatul depășește acest benchmark, conform disciplinei deja stabilite în `CLAUDE.md` („Feature nou în FEATURE_COLUMNS doar cu dovadă de ablație").
- `ml_predictor.FEATURE_COLUMNS` rămâne neschimbat (13 intrări).
- Atenția proiectului se mută de la infrastructura Learning Core (închisă, ADR-019) și de la calitatea feature-urilor existente (închisă, acest ADR) către: îmbunătățirea ratingurilor ELO/ofensiv/defensiv, feature engineering nou (xG/Understat/context meci), tuning hyperparametri XGBoost, calibrarea probabilităților, noi surse de date.
- Niciun cod nou, nicio migrare, zero impact asupra producției — acest ADR e pur decizional, consemnează concluzia unei investigații deja executate.
