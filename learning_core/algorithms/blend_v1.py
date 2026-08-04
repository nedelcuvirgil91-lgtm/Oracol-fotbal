"""
================================================================================
FOOTBALL ORACLE — Learning Core: adaptor Blend (v1)
================================================================================
Module: learning_core/algorithms/blend_v1.py

Adaptor subțire, tipar identic `xgboost_v1.py` (Pasul 13, derivat din
ADR-050/`docs/00_GOVERNANCE/ADR-050-challenger-framework-compound-algorithms.md`,
ACCEPTED). Antrenează propriul submodel ML (`MLPredictorEngine`), independent
de orice Challenger `xgboost_v1` existent — nicio cuplare nouă între
Challenger-i de familii diferite (Implementation Plan Pasul 13, §2.1).

`get_trained_model()` întoarce submodelul ML — identic `xgboost_v1`,
încadrat exact în contractul `LearningAlgorithm` existent, fără nicio
extindere (rezolvă explicit întrebarea lăsată deschisă în ADR-050 §6.1:
niciun „contract suplimentar" nu e necesar). Componenta Oracle a Blend-ului
nu e antrenată aici — e configurație deja versionată separat
(`model_weights`/`model_config`), neatinsă de acest adaptor.

`predict(features)` NU e apelat de fluxul de shadow al Pasului 13
(`learning_core/blend_challenger_shadow.py` reconstruiește inferența direct
din artefacte, decizie de execuție motivată în Implementation Plan §2.3) —
implementat totuși pentru conformitate cu Protocolul (`runtime_checkable`),
tipar identic `league_weights_adaptive.predict()`: neutilizat de calea
reală, doar conformitate structurală. Întoarce probabilitățile ML brute
(fără blend cu Oracle).
================================================================================
"""
from __future__ import annotations

import uuid
from typing import Any

from learning_core.model_registry import TrainingRunResult
from ml_predictor import MIN_SAMPLES_TO_TRAIN, MLPredictorEngine


class BlendV1Algorithm:
    """Implementează LearningAlgorithm peste un MLPredictorEngine propriu —
    submodelul ML al unui Challenger Blend. Componenta Oracle nu e parte a
    acestui adaptor (vezi header-ul modulului)."""

    name = "blend_v1"
    version = "1"
    league_scope = "all"

    def __init__(self) -> None:
        self._engine = MLPredictorEngine()

    def fit(self, training_data: object = None) -> TrainingRunResult:
        """`training_data` ignorat — identic `XGBoostV1Algorithm.fit()`,
        `MLPredictorEngine.train()` își extrage singur datele din Supabase."""
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
        """NU e folosit de calea reală de shadow (Pasul 13 §2.3) — probabilități
        ML brute, fără blend cu Oracle. Prezent EXCLUSIV pentru conformitate
        cu Protocolul LearningAlgorithm. Calea reală: blend_challenger_shadow.py."""
        # NOT the production path — exists only to satisfy the
        # LearningAlgorithm protocol. Real inference: blend_challenger_shadow.py.
        pred = self._engine.predict(features)
        if pred is None:
            return (0.0, 0.0, 0.0, {"error": "model netrenuit sau predicție eșuată"})
        metadata = {
            "confidence": pred.confidence,
            "model_version": pred.model_version,
            "samples_used": pred.samples_used,
            "note": "probabilități ML brute, neutilizate de calea reală de shadow (blend calculat separat)",
        }
        return (pred.prob_home, pred.prob_draw, pred.prob_away, metadata)

    def describe(self) -> dict:
        return {
            "algorithm_family": self.name,
            "algorithm_version": self.version,
            "feature_columns": list(self._engine.feature_names),
            "is_trained": self._engine.is_trained,
            "min_samples_to_train": MIN_SAMPLES_TO_TRAIN,
            "wraps": "MLPredictorEngine (submodel ML) + Oracle (config, neantrenat) — blend calculat în afara acestui adaptor",
        }

    def get_trained_model(self) -> Any | None:
        """Vezi LearningAlgorithm.get_trained_model() (model_registry.py) pentru
        contractul complet. Submodelul ML al Blend-ului — identic
        `XGBoostV1Algorithm.get_trained_model()`, fără nicio extindere de
        contract (ADR-050 §6.1)."""
        return self._engine.model if self._engine.is_trained else None

    def get_calibration_temperature(self) -> float | None:
        """Vezi LearningAlgorithm.get_calibration_temperature() (model_registry.py).
        Calibrarea submodelului ML — reutilizează exact mecanismul ADR-049/
        Pasul 10a, neschimbat."""
        return self._engine.temperature
