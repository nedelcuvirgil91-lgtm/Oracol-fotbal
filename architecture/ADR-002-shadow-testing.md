# ADR-002 — Shadow testing separat de producție

## Status
Acceptat, în curs de implementare (tabele Supabase, apoi hook în oracle_engine.py).

## Context

Feature-uri noi (injuries, coaches, player statistics, referee etc.) provin
din date exclusiv live — nu există echivalent istoric în dataset-ul Kaggle
folosit pentru replay/backfill. Nu pot fi validate prin metodologia de
benchmark deja folosită (Brier/Log-loss/Accuracy pe cele 760 de meciuri
Premier League istorice). Regula strictă a proiectului ("doar beneficiu
măsurabil sau bug real, nu se implementează") ar bloca definitiv orice
feature din această categorie, fără o cale alternativă de validare.

## Decizie

Feature-urile exclusiv live se validează diferit — excepție explicită,
memorată ca regulă permanentă:
1. Documentare a raționamentului tehnic + literatură, la momentul implementării.
2. Shadow-logging obligatoriu la lansare — predicția de producție (baseline)
   ȘI varianta experimentală se salvează ambele, per meci real.
3. Comparație Brier/Log-loss/Accuracy pe fereastra live acumulată (nu pe
   istoric), odată ce sunt suficiente meciuri noi.

Producția nu e niciodată afectată de un experiment activ:

```
producție (weights.json / model_config)
        \
         \
      shadow experiment (shadow_predictions)
              ↓
      comparație statistică (experiment_registry)
              ↓
      promovare — DOAR manuală
```

### `shadow_predictions` — log brut, per meci, per etapă de procesare

Un rând per `(fixture_id, experiment_name, experiment_version,
experiment_group, processing_stage)` — permite mai multe experimente
simultane, comparație între versiuni, și vizibilitate asupra fiecărei etape
(`baseline` → `after_injuries` → `after_coaches` → ... → `final`).
`feature_metadata` (JSONB) conține atât date brute (ex. `missing_players`,
`coach_days`) cât și contribuțiile calculate (`injury_penalty`) — permite
atribuire retrospectivă ("de ce a câștigat acest experiment") fără
recalculare.

### `experiment_registry` — agregare, nu duplicare a log-ului brut

Rollup per `(experiment_name, experiment_version, league_scope)`: metrici
brute + delta față de baseline, semnificație statistică (per metrică,
individual), status (`insufficient_data` → `monitoring` →
`candidate_for_promotion` / `rejected` → `promoted` → `deprecated`).
`baseline_model_version` salvat explicit — un candidat comparat cu v2.2 nu
trebuie confundat cu unul comparat cu v2.4.

### Regula de promovare

`candidate_for_promotion` doar dacă toate trei metrici (Brier, Log-loss,
Accuracy) sunt **simultan** semnificativ mai bune (test statistic
configurabil — `StatisticsEngine`, vezi mai jos). Nicio scriere automată în
`weights.json`/`model_config`/pipeline de producție — promovarea reală
(`promoted_at`, `promoted_by`) e întotdeauna manuală.

### `StatisticsEngine` — interfață uniformă

```python
STATISTICAL_TESTS: dict[str, StatisticalTest] = {
    "paired_bootstrap": ..., "paired_permutation": ..., "wilcoxon": ...,
    # viitor: "mcnemar", "diebold_mariano", "bayesian" — fără schimbare de logică
}
```

## Consecințe

- Niciun feature live nu poate ajunge în producție fără o fereastră de
  validare reală acumulată — elimină riscul de a repeta greșeala găsită la
  recalibrarea automată per-meci (deja dezactivată, vezi ADR-004).
- Cost: tabele Supabase suplimentare, un pic de disciplină de logging la
  fiecare experiment nou — acceptat ca preț al siguranței pe termen lung.
