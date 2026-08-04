"""
================================================================================
FOOTBALL ORACLE — Learning Core: adaptor League Weights Adaptive (v1)
================================================================================
Module: learning_core/algorithms/league_weights_adaptive.py

Adaptor subțire peste recalibration.recalibrate_weights() — logica pură de
auto-învățare (ajustare league_weights), deja existentă, neschimbată. Nu
reimplementează algoritmul de recalibrare, nu reimplementează replay-ul
cronologic — reutilizează exact sync/bootstrap_league_learning.run_bootstrap(),
care face deja acest replay (ELO/formă/H2H reconstruite din match_history,
xG recalculat prin feature_engine.calibrate_xg — identic motorului live),
peste toate cele 9 ligi din BOOTSTRAP_LEAGUES.

`fit()` apelează run_bootstrap(dry_run=True) — INTENȚIONAT, întotdeauna.
Un Challenger/o rulare de antrenare nu are voie să scrie în starea de
producție (model_weights, rândul citit live de oracle_engine.py) — vezi
North Star #1 ("shadow rămâne shadow până e dovedit, niciodată invers").
Rezultatul replay-ului rămâne doar în memorie, folosit exclusiv pentru
metricile raportate în TrainingRunResult/training_runs.

Decizie de scop explicită (ADR-028, Varianta A — confirmată explicit,
nu presupusă): acest algoritm NU participă la Challenger Framework
(shadow testing / promotion / champion loading). Motivul, descoperit prin
reconnaissance direct, nu presupus: întregul lanț
challenger_shadow → model_artifact_storage → promotion_service/champion_loader
e construit explicit peste XGBClassifier.save_model()/.load_model()/
.predict_proba() (vezi model_artifact_storage.py, header: "Demonstrează
DOAR că un model XGBoost antrenat poate fi persistat"). Un weights dict nu
are aceste metode — generalizarea acelui lanț pentru algoritmi non-artifact
ar fi o extindere de scope reală, nu o migrare recalibrare→Registry, și ar
necesita un ADR nou dedicat.

`participates_in_challenger_framework: False` din describe() e citit generic
de learning_core.continuous_learning._process_pair() (ADR-030) — previne
crearea automată a unui Challenger "zombie" (fără nicio cale spre evaluare
reală, fiindcă nimic nu scrie shadow_predictions pentru acest algoritm).

`predict(features)` nu produce probabilități reale — recalibrarea ajustează
doar ponderile consumate de motorul Poisson (oracle_engine.py), nu e ea
însăși un model de predicție 1X2. Există exclusiv pentru conformitate cu
Protocolul LearningAlgorithm (runtime_checkable), simetric cu celelalte
adaptoare — niciun cod real din Challenger Framework nu-l apelează, dat
fiind participates_in_challenger_framework=False.
================================================================================
"""
from __future__ import annotations

import uuid
from typing import Any

from learning_core.model_registry import TrainingRunResult


class LeagueWeightsAdaptiveAlgorithm:
    """Implementează LearningAlgorithm peste recalibration.recalibrate_weights(),
    via replay-ul cronologic deja existent (sync/bootstrap_league_learning.py)."""

    name = "league_weights_adaptive"
    version = "1"
    league_scope = "all"

    def fit(self, training_data: object = None) -> TrainingRunResult:
        """`training_data` e ignorat — replay-ul își extrage singur datele din
        Supabase (match_history), exact ca xgboost_v1.fit(). dry_run=True
        întotdeauna: niciun efect asupra model_weights de producție."""
        from sync.bootstrap_league_learning import run_bootstrap

        result = run_bootstrap(dry_run=True)
        processed = result.get("processed", 0)

        if processed == 0:
            return TrainingRunResult(
                training_run_id=str(uuid.uuid4()),
                status="insufficient_data",
                samples_used=0,
                walk_forward_metrics={},
                message="Niciun meci eligibil găsit în replay-ul cronologic (bootstrap_league_learning) — nimic de antrenat.",
            )

        return TrainingRunResult(
            training_run_id=str(uuid.uuid4()),
            status="trained",
            samples_used=processed,
            walk_forward_metrics={
                "recalibrated": result.get("recalibrated", 0),
                "stable": result.get("stable", 0),
                "leagues_with_data": result.get("leagues_with_data", 0),
                "leagues_total": result.get("leagues_total", 0),
                "elapsed_seconds": result.get("elapsed_seconds", 0),
            },
            message=(
                f"Replay cronologic (dry_run=True, fără scriere în model_weights) peste "
                f"{result.get('leagues_with_data', 0)}/{result.get('leagues_total', 0)} ligi, "
                f"cutoff {result.get('cutoff_date', '?')}."
            ),
        )

    def predict(self, features: dict) -> tuple[float, float, float, dict]:
        """Nu produce predicții reale — vezi header-ul modulului. Întoarce
        mereu rezultatul degradat (tipar identic cu xgboost_v1/production_champion
        când predicția nu e posibilă)."""
        return (0.0, 0.0, 0.0, {
            "error": (
                "league_weights_adaptive nu produce predicții independente — ajustează "
                "doar ponderile consumate de motorul Poisson din oracle_engine.py. Nu "
                "participă la Challenger Framework (ADR-028, Varianta A); acest predict() "
                "există exclusiv pentru conformitate cu Protocolul LearningAlgorithm."
            ),
        })

    def describe(self) -> dict:
        return {
            "algorithm_family": self.name,
            "algorithm_version": self.version,
            "wraps": "recalibration.recalibrate_weights via sync.bootstrap_league_learning.run_bootstrap(dry_run=True)",
            "participates_in_challenger_framework": False,
        }

    def get_trained_model(self) -> Any | None:
        """Vezi LearningAlgorithm.get_trained_model() (model_registry.py) pentru
        contractul complet. Niciodată un model real — un weights dict nu e
        compatibil cu backend-ul de persistență (XGBoost), consecvent cu
        participates_in_challenger_framework=False (ADR-028)."""
        return None

    def get_calibration_temperature(self) -> float | None:
        """Vezi LearningAlgorithm.get_calibration_temperature() (model_registry.py).
        Niciodată o calibrare reală — simetric cu get_trained_model()."""
        return None
