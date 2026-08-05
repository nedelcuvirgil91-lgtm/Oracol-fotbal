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

from typing import Any

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
        explicit, nu va mai citi direct din Supabase.

        [CORECTAT — audit final ADR-051/052] training_run_id refolosește
        self._engine.last_record_run_id — id-ul EXACT al rândului deja
        persistat intern de MLPredictorEngine.train() (prin
        ml_predictor._record_training_run(), apelat necondiționat, pe orice
        status). Înainte se genera aici un uuid.uuid4() nou, disjunct de
        acel rând — training_runner.run_training() persista apoi un AL
        DOILEA rând, cu id diferit, pentru aceeași tentativă reală de
        antrenare (gol descoperit la audit, nu presupus). Acum ambele
        scrieri (aici + train()) convin asupra aceluiași id — vezi
        learning_core/storage.save_training_run(), care a devenit idempotent
        exact pentru acest caz."""
        result = self._engine.train()
        return TrainingRunResult(
            training_run_id=self._engine.last_record_run_id,
            status=result.status,
            samples_used=result.samples_used,
            walk_forward_metrics={
                "accuracy": result.accuracy,
                "log_loss": result.log_loss,
                "brier_score": result.brier_score,
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

    def get_trained_model(self) -> Any | None:
        """Vezi LearningAlgorithm.get_trained_model() (model_registry.py) pentru
        contractul complet. self._engine.model e populat de MLPredictorEngine.train()
        la fit() reușit — vezi ml_predictor.py, self.model/self.is_trained."""
        return self._engine.model if self._engine.is_trained else None

    def get_calibration_temperature(self) -> float | None:
        """Vezi LearningAlgorithm.get_calibration_temperature() (model_registry.py).
        self._engine.temperature e populat de MLPredictorEngine.train() —
        None dacă fitting-ul calibrării a eșuat (ADR-049 §9)."""
        return self._engine.temperature
