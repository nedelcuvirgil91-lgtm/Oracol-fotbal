# ADR-004 — Bucla de învățare continuă

## Status
Parțial implementat (`sync_results.py`/`run_daily.py` există; recalibrarea
automată per-meci descoperită ca incompatibilă cu restul arhitecturii,
dezactivare planificată printr-un feature flag, neimplementată încă).

## Context

`sync/sync_results.py`, rulat zilnic (GitHub Actions, 03:00 UTC), apela
necondiționat `recalibrate_weights()` + `save_weights()` pentru fiecare meci
cu predicție live salvată — fără nicio poartă de eșantion suficient sau
validare pe benchmark. Asta contrazicea direct concluziile ulterioare ale
proiectului (recalibrarea trebuie validată pe eșantioane mari, apoi prin
shadow testing, apoi promovare manuală). Un audit a demonstrat, cu dovezi
directe din Supabase, că acest mecanism nu apucase încă să ruleze cu date
reale (`sample_count=0` peste tot) — dar codul rămânea, gata să ruleze
exact așa data viitoare.

Același audit a descoperit cauza reală pentru care `sample_count` rămânea
0: singurele meciuri cu predicție live salvată erau din `World Cup 2026`,
ligă absentă din `COMPETITION_TO_LEAGUE` (reparat, vezi ADR-001) — deci
rezultatele lor nu ajungeau niciodată în `match_history`.

## Decizie — ordinea corectă a buclei

```
fixtures → results → match_history → ELO → formă → standings
    → shadow evaluation → experiment_registry
    → ML retraining (dacă e cazul) → recalibrare (manuală, validată)
```

Nu:

```
rezultat nou → recalibrate_weights() → weights.json   (fluxul vechi, incompatibil)
```

Recalibrarea automată per-meci se dezactivează printr-un feature flag
explicit (`auto_recalibration_enabled: false` în `model_config`), nu prin
ștergerea sau comentarea codului — păstrează codul ca referință/opțiune,
elimină comportamentul implicit.

## Principii permanente (memorate, aplicabile la orice modificare viitoare)

- Niciun meci nou nu rămâne neimportat — recuperare automată dacă un job
  eșuează (nu doar fereastra de "ieri"; verificare de gap-uri).
- Toate feature-urile (ELO, formă, standings) se recalculează incremental
  după fiecare actualizare de rezultate.
- Recalibrarea nu se declanșează de frecvența meciurilor, ci de un prag
  configurabil (`minimum_matches_for_evaluation`, per ligă) + validare
  statistică simultană pe Brier, Log-loss și Accuracy.
- Orice feature/provider nou se adaugă fără rescrierea pipeline-ului
  (vezi ADR-001 pentru mapări, ADR-003 pentru surse de date).

## Consecințe

- Un meci nou nu mai poate "dispărea" silențios din buclă fără ca
  `verify_league_coverage()` (ADR-001) să semnaleze problema.
- Recalibrarea devine o decizie informată (raport din
  `experiment_registry`), nu un efect secundar automat al sincronizării
  zilnice.
