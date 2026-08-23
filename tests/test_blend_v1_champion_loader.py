"""
Teste pentru learning_core.blend_v1_champion_loader — ADR-061.
Fără rețea — toate dependențele (supabase_client, model_artifact_storage,
calibration_artifact_storage) sunt monkeypatch-uite.

Mirror structural al tests/test_champion_loader.py, dar verifică explicit
DISTINCȚIA centrală a ADR-061: condiția 6 (versiune compatibilă) compară
față de BlendV1Algorithm.version, NU față de ml_predictor._ALGORITHM_VERSION
— chiar dacă azi cele două constante coincid ca valoare ("1"), testele includ
un scenariu în care ele DIVERG, ca gardă de regresie reală (nu doar
coincidență de valori).
"""
import numpy as np
import pytest

from learning_core import blend_v1_champion_loader as bcl
from learning_core.algorithms.blend_v1 import BlendV1Algorithm


def _valid_champion(training_run_id="run-blend-1"):
    return {"training_run_id": training_run_id, "algorithm_family": "blend_v1", "league_scope": "all"}


def _valid_training_run(algorithm_version=None, samples_used=5000):
    if algorithm_version is None:
        algorithm_version = BlendV1Algorithm.version
    return {
        "algorithm_version": algorithm_version, "samples_used": samples_used,
        "walk_forward_metrics": {"accuracy": 0.51, "log_loss": 1.04, "brier_score": 0.62},
        "created_at": "2026-08-04T14:46:39Z",
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
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: None,
    )


def test_returns_result_when_all_six_conditions_met(happy_path):
    result = bcl.load_blend_v1_champion_or_none("all")
    assert result is not None
    assert result.training_run_id == "run-blend-1"
    assert result.samples_used == 5000
    assert result.algorithm_version == BlendV1Algorithm.version
    assert result.accuracy == 0.51
    assert result.log_loss == 1.04
    assert result.trained_at == "2026-08-04T14:46:39Z"


def test_active_champion_looked_up_for_blend_v1_family(monkeypatch):
    """Gardă directă: familia interogată e "blend_v1", niciodată alta —
    trece prin lambda-ul care validează argumentul primit."""
    captured = {}

    def _capture(family, scope):
        captured["family"] = family
        captured["scope"] = scope
        return _valid_champion()

    monkeypatch.setattr("supabase_client.get_active_champion", _capture)
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: None)

    bcl.load_blend_v1_champion_or_none("all")
    assert captured == {"family": "blend_v1", "scope": "all"}


# ── Distincția centrală ADR-061: versiune verificată față de BlendV1Algorithm ──

def test_version_check_uses_blend_v1_algorithm_version_not_ml_predictor_constant(monkeypatch):
    """Gardă de regresie reală: chiar dacă ml_predictor._ALGORITHM_VERSION și
    BlendV1Algorithm.version diverg, Champion-ul blend_v1 trebuie validat
    exclusiv față de a doua. Simulează divergența explicit."""
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    # training_run marcat cu versiunea ml_predictor (diferită, simulat)
    monkeypatch.setattr(
        "supabase_client.get_training_run",
        lambda tid: _valid_training_run(algorithm_version="ml_predictor_version_diferita"),
    )
    monkeypatch.setattr("ml_predictor._ALGORITHM_VERSION", "ml_predictor_version_diferita", raising=False)

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe — versiunea nu se potriveste cu BlendV1Algorithm.version")

    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", _fail_if_called)

    # BlendV1Algorithm.version ("1") != "ml_predictor_version_diferita" -> None
    assert bcl.load_blend_v1_champion_or_none("all") is None


def test_version_check_accepts_when_matches_blend_v1_algorithm_version(happy_path):
    """Complementul testului de mai sus: cand training_run.algorithm_version
    == BlendV1Algorithm.version, Campionul e acceptat — indiferent de
    ml_predictor._ALGORITHM_VERSION."""
    result = bcl.load_blend_v1_champion_or_none("all")
    assert result is not None
    assert result.algorithm_version == BlendV1Algorithm.version


def test_returns_none_when_algorithm_version_mismatch(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr(
        "supabase_client.get_training_run",
        lambda tid: _valid_training_run(algorithm_version="0-legacy"),
    )

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe cu algorithm_version incompatibil")

    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", _fail_if_called)

    assert bcl.load_blend_v1_champion_or_none("all") is None


# ── Calibrare (ADR-049, Pasul 10b) ───────────────────────────────────────

def test_result_includes_temperature_when_calibration_available(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: 1.12,
    )

    result = bcl.load_blend_v1_champion_or_none("all")

    assert result is not None
    assert result.temperature == 1.12


def test_result_has_none_temperature_when_calibration_unavailable(happy_path):
    result = bcl.load_blend_v1_champion_or_none("all")
    assert result is not None
    assert result.temperature is None


def test_result_metadata_missing_gracefully_defaults_to_none(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr(
        "supabase_client.get_training_run",
        lambda tid: {"algorithm_version": BlendV1Algorithm.version, "samples_used": 207},
    )
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())

    result = bcl.load_blend_v1_champion_or_none("all")
    assert result is not None
    assert result.accuracy is None
    assert result.log_loss is None
    assert result.trained_at is None


# ── Restul celor 6 condiții ───────────────────────────────────────────────

def test_returns_none_when_no_active_champion(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: None)
    assert bcl.load_blend_v1_champion_or_none("all") is None


def test_returns_none_when_training_run_missing(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: None)
    assert bcl.load_blend_v1_champion_or_none("all") is None


def test_returns_none_when_artifact_missing(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: None)
    assert bcl.load_blend_v1_champion_or_none("all") is None


def test_returns_none_when_inference_fails(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda tid: _FakeModel(should_fail=True),
    )
    assert bcl.load_blend_v1_champion_or_none("all") is None


def test_exceptions_are_swallowed_not_propagated(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare neasteptata")

    monkeypatch.setattr("supabase_client.get_active_champion", _boom)
    assert bcl.load_blend_v1_champion_or_none("all") is None


# ── Izolare: nu reutilizează / nu modifică champion_loader.py existent ────

def test_does_not_import_or_call_xgboost_champion_loader():
    """Gardă structurală: blend_v1_champion_loader.py NU importă
    learning_core.champion_loader (RUNTIME_CONTRACT.md, FROZEN, scopat
    exclusiv la xgboost_v1/self.ml) — mecanism complet paralel, nu
    reutilizare, per ADR-061."""
    import ast
    import pathlib

    path = pathlib.Path(bcl.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[-1] != "champion_loader", (
                "blend_v1_champion_loader.py nu trebuie sa importe champion_loader.py"
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[-1] != "champion_loader"
