"""Teste pentru learning_core.algorithms.xgboost_v1 — fără rețea, fără
Supabase live (MLPredictorEngine() neconectat rămâne is_trained=False)."""
import pytest

import ml_predictor
from learning_core import champion_comparison, model_registry, storage
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


# ── fit() — trasabilitate training_run_id (audit final ADR-051/052) ────────
# Gol descoperit: fit() genera un uuid.uuid4() propriu, disjunct de rândul
# deja persistat intern de MLPredictorEngine.train() — training_runner.py
# scria apoi un AL DOILEA rând, cu id diferit, pentru aceeași tentativă de
# antrenare. Testele de mai jos antrenează REAL (date sintetice, storage
# izolat) ca să verifice că fit() refolosește exact id-ul intern.

_FEATURE_ROW_TEMPLATE = {
    "home_offensive_rating": 1.1, "home_defensive_rating": 0.9,
    "away_offensive_rating": 1.0, "away_defensive_rating": 1.0,
    "home_form_score": 0.5, "away_form_score": 0.5,
    "home_elo": 1500, "away_elo": 1500,
    "h2h_modifier": 0.0, "h2h_meetings": 0,
    "home_corner_avg_recent": 5.0, "away_corner_avg_recent": 4.5,
    "home_card_avg_recent": 1.5, "away_card_avg_recent": 2.0,
    "home_foul_avg_recent": 11.0, "away_foul_avg_recent": 10.0,
}
_RESULTS_CYCLE = ["H", "D", "A"]


def _synthetic_rows(n: int = 40) -> list[dict]:
    rows = []
    for i in range(n):
        row = dict(_FEATURE_ROW_TEMPLATE)
        row["home_elo"] = 1500 + (i % 5) * 10
        row["away_elo"] = 1500 - (i % 5) * 10
        row["actual_result"] = _RESULTS_CYCLE[i % 3]
        row["kickoff_date"] = f"2026-01-{(i % 28) + 1:02d}"
        rows.append(row)
    return rows


@pytest.fixture
def isolated_fit(tmp_path, monkeypatch):
    """Storage local izolat + Supabase complet mockuit — mirror exact al
    fixture-ului din tests/test_ml_predictor_training_run_recording.py,
    reutilizat aici pentru fit() (nu doar train() direct)."""
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion", lambda *a, **kw: None)

    algo = XGBoostV1Algorithm()
    monkeypatch.setattr(ml_predictor.sb, "is_available", lambda: True)
    monkeypatch.setattr(ml_predictor.sb, "get_training_data", lambda only_with_results=True: _synthetic_rows())
    monkeypatch.setattr(ml_predictor.sb, "save_ml_status", lambda **kw: True)
    return algo


def test_xgboost_adapter_fit_reuses_engine_internal_training_run_id(isolated_fit):
    algo = isolated_fit
    result = algo.fit()

    assert result.status == "trained"
    assert algo._engine.last_record_run_id is not None
    assert result.training_run_id == algo._engine.last_record_run_id
    assert result.training_run_id == algo._engine.last_training_run_id


def test_xgboost_adapter_fit_result_persisted_exactly_once(isolated_fit):
    """Dovadă directă că nu mai există dublă scriere: id-ul întors de fit()
    corespunde unui SINGUR rând deja persistat de train() intern."""
    algo = isolated_fit
    result = algo.fit()

    rows = storage.list_training_runs()
    matching = [r for r in rows if r["training_run_id"] == result.training_run_id]
    assert len(matching) == 1


def test_xgboost_adapter_fit_walk_forward_metrics_includes_brier_score(isolated_fit):
    result = isolated_fit.fit()
    assert result.status == "trained"
    assert "brier_score" in result.walk_forward_metrics
    assert result.walk_forward_metrics["brier_score"] is not None
