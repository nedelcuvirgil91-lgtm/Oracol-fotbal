"""
================================================================================
FOOTBALL ORACLE — Learning Core: adaptor XGBoost (v1)
================================================================================
Module: learning_core/algorithms/xgboost_v1.py

Adaptor subțire peste ml_predictor.MLPredictorEngine, deja existent și
neschimbat — vezi LEARNING_CORE_ARCHITECTURE.md §3.1, §7 ("ml_predictor.py
... neschimbat"). Nu reimplementează walk-forward validation, antrenarea sau
predicția — doar le expune prin interfața comună LearningAlgorithm.

`features` la predict() are exact același format ca azi: un dict cu cheile
din ml_predictor.FEATURE_COLUMNS — niciun format nou introdus.
================================================================================
"""
from __future__ import annotations

import uuid

from learning_core.model_registry import TrainingRunResult
from ml_predictor import MIN_SAMPLES_TO_TRAIN, MLPredictorEngine


class XGBoostV1Algorithm:
    """Implementează LearningAlgorithm peste MLPredictorEngine existent."""

    name = "xgboost_v1"
    version = "1"
    league_scope = "all"

    def __init__(self) -> None:
        self._engine = MLPredictorEngine()

    def fit(self, training_data: object = None) -> TrainingRunResult:
        """`training_data` e ignorat la v0.1 — MLPredictorEngine.train() își
        extrage singur datele din Supabase (sb.get_training_data()), exact ca
        azi. Parametrul rămâne în semnătură pentru conformitate cu
        LearningAlgorithm — pregătit pentru Dataset Registry (etapă
        ulterioară), când antrenarea va primi un dataset_id versionat
        explicit, nu va mai citi direct din Supabase."""
        result = self._engine.train()
        return TrainingRunResult(
            training_run_id=str(uuid.uuid4()),
            status=result.status,
            samples_used=result.samples_used,
            walk_forward_metrics={
                "accuracy": result.accuracy,
                "log_loss": result.log_loss,
            },
            message=result.message,
        )

    def predict(self, features: dict) -> tuple[float, float, float, dict]:
        pred = self._engine.predict(features)
        if pred is None:
            return (0.0, 0.0, 0.0, {"error": "model netrenuit sau predicție eșuată"})
        metadata = {
            "confidence": pred.confidence,
            "model_version": pred.model_version,
            "samples_used": pred.samples_used,
        }
        return (pred.prob_home, pred.prob_draw, pred.prob_away, metadata)

    def describe(self) -> dict:
        return {
            "algorithm_family": self.name,
            "algorithm_version": self.version,
            "feature_columns": list(self._engine.feature_names),
            "is_trained": self._engine.is_trained,
            "min_samples_to_train": MIN_SAMPLES_TO_TRAIN,
        }
