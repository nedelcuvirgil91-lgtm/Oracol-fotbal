"""
Teste pentru learning_core.local_model_cache — fix „aplicația pornește
foarte greu". Fără rețea — toate dependențele (supabase_client,
model_artifact_storage, calibration_artifact_storage) sunt monkeypatch-uite.

Tipar identic tests/test_champion_loader.py, cu o diferență structurală
esențială: sursa e list_recent_training_runs() (o listă, cel mai recent
primul), nu un singur rând — testat explicit fallback-ul pe al doilea
candidat cand primul nu are artefact.
"""
import numpy as np
import pytest

from learning_core import local_model_cache as lmc


def _valid_run(training_run_id="run-1", algorithm_version="1", status="trained", samples_used=5000):
    return {
        "training_run_id": training_run_id, "status": status,
        "algorithm_version": algorithm_version, "samples_used": samples_used,
        "walk_forward_metrics": {"accuracy": 0.51, "log_loss": 1.01, "brier_score": 0.61},
        "created_at": "2026-08-01T12:00:00Z",
    }


class _FakeModel:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail

    def predict_proba(self, X):
        if self.should_fail:
            raise RuntimeError("inferenta a esuat")
        return np.array([[0.4, 0.3, 0.3]])


@pytest.fixture
def happy_path(monkeypatch):
    monkeypatch.setattr("supabase_client.list_recent_training_runs", lambda family, scope, limit=10: [_valid_run()])
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: None)


def test_returns_result_when_latest_run_is_valid(happy_path):
    result = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert result is not None
    assert result.training_run_id == "run-1"
    assert result.samples_used == 5000
    assert result.algorithm_version == "1"
    assert result.accuracy == 0.51
    assert result.log_loss == 1.01
    assert result.trained_at == "2026-08-01T12:00:00Z"


def test_returns_none_when_no_training_run_ever(monkeypatch):
    monkeypatch.setattr("supabase_client.list_recent_training_runs", lambda family, scope, limit=10: [])
    assert lmc.load_latest_trained_model_or_none("xgboost_v1", "all") is None


def test_skips_non_trained_status(monkeypatch):
    monkeypatch.setattr(
        "supabase_client.list_recent_training_runs",
        lambda family, scope, limit=10: [_valid_run(status="error"), _valid_run(training_run_id="run-2")],
    )
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: None)

    result = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert result is not None
    assert result.training_run_id == "run-2"


def test_skips_algorithm_version_mismatch(monkeypatch):
    monkeypatch.setattr(
        "supabase_client.list_recent_training_runs",
        lambda family, scope, limit=10: [_valid_run(algorithm_version="0-legacy")],
    )

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe cu algorithm_version incompatibil")

    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", _fail_if_called)

    assert lmc.load_latest_trained_model_or_none("xgboost_v1", "all") is None


def test_falls_back_to_second_candidate_when_first_has_no_artifact(monkeypatch):
    """Ancora robustă: primul rand (cel mai recent) poate să nu aibă
    artefact persistat (ex. un retrain manual care nu salvează artefact) —
    trebuie să se cadă grațios pe următorul cel mai recent cu artefact
    valid, nu se declară cache-ul indisponibil."""
    monkeypatch.setattr(
        "supabase_client.list_recent_training_runs",
        lambda family, scope, limit=10: [
            _valid_run(training_run_id="run-no-artifact"),
            _valid_run(training_run_id="run-with-artifact"),
        ],
    )

    def _load(tid):
        return _FakeModel() if tid == "run-with-artifact" else None

    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", _load)
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: None)

    result = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert result is not None
    assert result.training_run_id == "run-with-artifact"


def test_falls_back_to_second_candidate_when_first_inference_fails(monkeypatch):
    monkeypatch.setattr(
        "supabase_client.list_recent_training_runs",
        lambda family, scope, limit=10: [
            _valid_run(training_run_id="run-bad-model"),
            _valid_run(training_run_id="run-good-model"),
        ],
    )

    def _load(tid):
        return _FakeModel(should_fail=True) if tid == "run-bad-model" else _FakeModel()

    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", _load)
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: None)

    result = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert result is not None
    assert result.training_run_id == "run-good-model"


def test_returns_none_when_no_candidate_has_valid_artifact(monkeypatch):
    monkeypatch.setattr(
        "supabase_client.list_recent_training_runs",
        lambda family, scope, limit=10: [_valid_run(training_run_id="run-1"), _valid_run(training_run_id="run-2")],
    )
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: None)

    assert lmc.load_latest_trained_model_or_none("xgboost_v1", "all") is None


def test_result_includes_temperature_when_calibration_available(monkeypatch):
    monkeypatch.setattr("supabase_client.list_recent_training_runs", lambda family, scope, limit=10: [_valid_run()])
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: 1.42)

    result = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert result is not None
    assert result.temperature == 1.42


def test_result_has_none_temperature_when_calibration_unavailable(happy_path):
    result = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert result is not None
    assert result.temperature is None


def test_exceptions_are_swallowed_not_propagated(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare neasteptata")

    monkeypatch.setattr("supabase_client.list_recent_training_runs", _boom)
    assert lmc.load_latest_trained_model_or_none("xgboost_v1", "all") is None


def test_module_has_single_known_importer():
    """local_model_cache e folosit doar de oracle_engine.py (_resolve_local_cache)
    si de propriul test — tipar identic champion_loader.py."""
    import ast
    import pathlib

    ALLOWED_IMPORTERS = {"oracle_engine.py"}

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if ".git" in path.parts:
            continue
        if path.name in ("local_model_cache.py", "test_local_model_cache.py", "test_champion_diagnostic_probe.py"):
            continue
        if path.name in ALLOWED_IMPORTERS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[-1] == "local_model_cache" for alias in node.names):
                    offenders.append(str(path.relative_to(root)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[-1] == "local_model_cache" or any(
                    alias.name == "local_model_cache" for alias in node.names
                ):
                    offenders.append(str(path.relative_to(root)))

    assert offenders == [], f"local_model_cache e importat in afara scopului asteptat: {offenders}"
