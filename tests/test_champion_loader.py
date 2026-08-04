"""
Teste pentru learning_core.champion_loader — Pasul 6, Architecture Gate 6.
Fără rețea — toate dependențele (supabase_client, model_artifact_storage)
sunt monkeypatch-uite.

Verifică toate cele 6 condiții din RUNTIME_CONTRACT.md, inclusiv cea nouă
(algorithm_version compatibil, adăugată la Architecture Gate 6).
"""
import numpy as np
import pytest

from learning_core import champion_loader as cl


def _valid_champion(training_run_id="run-1"):
    return {"training_run_id": training_run_id, "algorithm_family": "xgboost_v1", "league_scope": "all"}


def _valid_training_run(algorithm_version="1", samples_used=5000):
    return {
        "algorithm_version": algorithm_version, "samples_used": samples_used,
        "walk_forward_metrics": {"accuracy": 0.51, "log_loss": 1.01, "brier_score": 0.61},
        "created_at": "2026-07-14T12:00:00Z",
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
    result = cl.load_champion_or_none("xgboost_v1", "all")
    assert result is not None
    assert result.training_run_id == "run-1"
    assert result.samples_used == 5000
    assert result.algorithm_version == "1"
    assert result.accuracy == 0.51
    assert result.log_loss == 1.01
    assert result.trained_at == "2026-07-14T12:00:00Z"


def test_result_metadata_missing_gracefully_defaults_to_none(monkeypatch):
    """Daca walk_forward_metrics/created_at lipsesc din training_run (randuri
    vechi/incomplete), rezultatul tot se construieste, cu None, nu eroare."""
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr(
        "supabase_client.get_training_run",
        lambda tid: {"algorithm_version": "1", "samples_used": 100},
    )
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())

    result = cl.load_champion_or_none("xgboost_v1", "all")
    assert result is not None
    assert result.accuracy is None
    assert result.log_loss is None
    assert result.trained_at is None


# ── Calibrare (ADR-049, Pasul 10b) ───────────────────────────────────────

def test_result_includes_temperature_when_calibration_available(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr(
        "learning_core.calibration_artifact_storage.load_calibration_artifact", lambda tid: 1.37,
    )

    result = cl.load_champion_or_none("xgboost_v1", "all")

    assert result is not None
    assert result.temperature == 1.37


def test_result_has_none_temperature_when_calibration_unavailable(happy_path):
    """Degradare grațioasă (ADR-049 §8/§9): fără calibrare disponibilă,
    Champion-ul TOT se consideră utilizabil — doar `temperature` e None,
    nu invalidează niciuna dintre cele 6 condiții de utilizabilitate."""
    result = cl.load_champion_or_none("xgboost_v1", "all")

    assert result is not None
    assert result.temperature is None


def test_unexpected_calibration_exception_is_swallowed_by_outer_guard(monkeypatch):
    """load_calibration_artifact() nu ridica niciodata exceptie in mod
    normal (contract testat exhaustiv la Pasul 10a) -- acest test acopera
    defensiv scenariul unei incalcari a acelui contract. champion_loader.py
    NU adauga un try/except dedicat pentru apelul de calibrare (decizie
    explicita, Implementation Plan 10b §2.1) -- o exceptie neasteptata aici
    e prinsa de garda existenta a intregii functii, care intoarce None
    pentru TOT rezultatul, nu un ChampionLoadResult partial cu temperature
    lipsa. Comportament acceptat: o incalcare de contract la calibrare
    degradeaza intreg Champion-ul la indisponibil, nu doar calibrarea.

    [PRECIZARE — review Pasul 10b] Acest caz NU poate aparea in
    implementarea normala — load_calibration_artifact() nu ridica
    niciodata exceptie (contract testat exhaustiv la Pasul 10a, orice esec
    intoarce None). Testul e strict defensiv, pentru o incalcare
    ipotetica a acelui contract, NU un flux normal de degradare gratioasa
    (acela e acoperit de test_result_has_none_temperature_when_calibration_unavailable,
    unde load_calibration_artifact() intoarce None, nu ridica exceptie)."""
    def _boom(tid):
        raise RuntimeError("eroare neasteptata in calibration_artifact_storage")

    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact", _boom)

    assert cl.load_champion_or_none("xgboost_v1", "all") is None


def test_returns_none_when_no_active_champion(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: None)
    assert cl.load_champion_or_none("xgboost_v1", "all") is None


def test_returns_none_when_training_run_missing(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: None)
    assert cl.load_champion_or_none("xgboost_v1", "all") is None


def test_returns_none_when_algorithm_version_mismatch(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run(algorithm_version="0-legacy"))

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe cu algorithm_version incompatibil")

    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", _fail_if_called)

    assert cl.load_champion_or_none("xgboost_v1", "all") is None


def test_returns_none_when_artifact_missing(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: None)
    assert cl.load_champion_or_none("xgboost_v1", "all") is None


def test_returns_none_when_inference_fails(monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda family, scope: _valid_champion())
    monkeypatch.setattr("supabase_client.get_training_run", lambda tid: _valid_training_run())
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda tid: _FakeModel(should_fail=True),
    )
    assert cl.load_champion_or_none("xgboost_v1", "all") is None


def test_exceptions_are_swallowed_not_propagated(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare neasteptata")

    monkeypatch.setattr("supabase_client.get_active_champion", _boom)
    assert cl.load_champion_or_none("xgboost_v1", "all") is None


def test_module_has_single_known_importer():
    """champion_loader e folosit doar de oracle_engine.py (diagnostic,
    Pasul 6, self.ml neatins) si de propriul test."""
    import ast
    import pathlib

    ALLOWED_IMPORTERS = {"oracle_engine.py"}

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if ".git" in path.parts:
            continue
        if path.name in ("champion_loader.py", "test_champion_loader.py", "test_champion_diagnostic_probe.py"):
            continue
        if path.name in ALLOWED_IMPORTERS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[-1] == "champion_loader" for alias in node.names):
                    offenders.append(str(path.relative_to(root)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[-1] == "champion_loader" or any(
                    alias.name == "champion_loader" for alias in node.names
                ):
                    offenders.append(str(path.relative_to(root)))

    assert offenders == [], f"champion_loader e importat in afara scopului Pasului 6: {offenders}"
