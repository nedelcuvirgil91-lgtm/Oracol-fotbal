"""Teste pentru learning_core.algorithms.xgboost_v1 — fără rețea, fără
Supabase live (MLPredictorEngine() neconectat rămâne is_trained=False)."""
from learning_core import model_registry
from learning_core.algorithms.xgboost_v1 import XGBoostV1Algorithm


def test_xgboost_adapter_conforms_to_protocol():
    algo = XGBoostV1Algorithm()
    assert isinstance(algo, model_registry.LearningAlgorithm)
    assert algo.name == "xgboost_v1"


def test_xgboost_adapter_predict_untrained_returns_safe_default():
    algo = XGBoostV1Algorithm()
    ph, pd, pa, meta = algo.predict({})
    assert (ph, pd, pa) == (0.0, 0.0, 0.0)
    assert "error" in meta


def test_xgboost_adapter_describe():
    algo = XGBoostV1Algorithm()
    d = algo.describe()
    assert d["algorithm_family"] == "xgboost_v1"
    assert d["is_trained"] is False
    assert d["min_samples_to_train"] == 30


def test_xgboost_adapter_get_trained_model_untrained_returns_none():
    algo = XGBoostV1Algorithm()
    assert algo.get_trained_model() is None


def test_xgboost_adapter_get_trained_model_after_training_returns_model():
    algo = XGBoostV1Algorithm()
    sentinel_model = object()
    algo._engine.model = sentinel_model
    algo._engine.is_trained = True
    assert algo.get_trained_model() is sentinel_model


def test_xgboost_adapter_get_trained_model_repeated_calls_return_same_instance():
    """Contract de identitate (ADR-048, Pasul 9 Implementation Plan §1):
    apeluri repetate intre doua fit() intorc aceeasi instanta."""
    algo = XGBoostV1Algorithm()
    sentinel_model = object()
    algo._engine.model = sentinel_model
    algo._engine.is_trained = True
    first = algo.get_trained_model()
    second = algo.get_trained_model()
    assert first is second is sentinel_model


def test_xgboost_adapter_get_calibration_temperature_untrained_returns_none():
    algo = XGBoostV1Algorithm()
    assert algo.get_calibration_temperature() is None


def test_xgboost_adapter_get_calibration_temperature_after_fitting():
    algo = XGBoostV1Algorithm()
    algo._engine.temperature = 1.42
    assert algo.get_calibration_temperature() == 1.42
