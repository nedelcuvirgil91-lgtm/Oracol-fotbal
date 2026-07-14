# ADR-015 — Istoric de rulări de antrenare + comparare cu Campionul activ

**Status**: Implementat
**Affects**: schema Supabase (`training_runs`, `model_champions`), `ml_predictor.py`, `learning_core/storage.py`
**Authority**: Principal Software Architect, aprobat explicit de proprietarul produsului

---

## Context

Un audit cap-coadă al lanțului de învățare continuă (2026-07-14) a confirmat, verigă cu verigă, cu dovadă din cod, că „Comparare model nou vs. activ" (veriga #9) era imposibilă structural: `ml_model_status` e un singur rând fix (`id=1`), suprascris de fiecare `train()` — metricile unei rulări anterioare dispar ireversibil înainte ca vreo comparație să poată exista. `training_runs`/`model_champions` erau deja proiectate (`database/migrations/002_learning_core.sql`, `docs/04_LEARNING_CORE/LEARNING_CORE_ARCHITECTURE.md`), dar migrarea purta un gate explicit de neaplicare până la aprobare separată.

Aprobarea a fost condiționată de o justificare punctuală (necesitate/verigă reparată/de ce nu există deja/impact/reversibilitate/ordine logică) — vezi discuția din sesiune, nu repetată aici.

## Decision

1. **Migrarea `002_learning_core.sql` aplicată** — `training_runs` (istoric append-only per rulare) + `model_champions` (pointer campion activ, index unic parțial pe `superseded_at IS NULL`). 100% aditivă, RLS activ, nicio tabelă existentă atinsă.

2. **`ml_predictor.MLPredictorEngine.train()` înregistrează fiecare rulare** — la toate cele 4 puncte de return (`trained`/`insufficient_data`/`error`/`unavailable`), prin `learning_core.storage.save_training_run()` (extins să scrie și remote, best-effort — local rămâne garantat). Decizie explicită de a atinge `ml_predictor.py` direct (nu doar adaptorul `XGBoostV1Algorithm.fit()`), fiindcă fluxul real de producție (`run_daily.py`, `oracle_engine.py`) apelează `train()` direct, ocolind Learning Core — o înregistrare doar în adaptor n-ar fi văzut niciodată rulările reale.

3. **`learning_core/champion_comparison.py` (nou)** — compară metricile (`accuracy`, `log_loss`, `brier_score`) noii rulări cu cele ale campionului activ (`model_champions` + `training_runs`), dacă există. Pur informativ — loghează, nu decide.

4. **Explicit, ce NU face acest ADR**: nu promovează, nu face rollback, nu schimbă Predictorul activ, nu schimbă comportamentul de producție. `model_champions` rămâne gol până la o decizie separată de promovare (manuală sau, per CLAUDE.md, cu ADR dedicat pentru `auto_promotion_enabled`).

## Rationale

Fără istoric, „comparare/promotion/rollback" nu au ce compara. Aceasta e infrastructura minimă, aditivă, care face acele verigi POSIBILE — nu le implementează pe toate simultan.

## Consequences

- Fiecare `train()` real (Streamlit cold-start, `run_daily.py` Pasul 6/6, `weekly.yml`) produce acum un rând nou, permanent, în `training_runs` — istoricul complet de antrenări devine, pentru prima dată, trasabil (Regula #9 din CLAUDE.md — „orice rezultat trasabil complet").
- `ml_model_status` rămâne neschimbat — consumatorii lui existenți (`status_summary()`, UI) nu sunt atinși.
- Eșecul scrierii remote (Supabase indisponibil) nu afectează niciodată `MLTrainingResult` întors apelantului — verificat explicit prin test (`test_predictor_result_contract_unaffected_by_recording_failure`).
- `model_champions` rămâne gol până la prima promovare — o decizie viitoare, separată, nu implicită.
