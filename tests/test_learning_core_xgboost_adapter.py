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
