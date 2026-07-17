"""Teste pentru learning_core.training_runner — fără rețea, fără Supabase live."""
from pathlib import Path

import pytest

from learning_core import model_registry, storage
from learning_core.training_runner import run_training


class _DummyAlgorithm:
    name = "dummy_runner_test"
    version = "1"
    league_scope = "all"

    def fit(self, training_data):
        return model_registry.TrainingRunResult(
            training_run_id="dummy-run-id", status="trained", samples_used=5,
        )

    def predict(self, features):
        return (0.4, 0.3, 0.3, {})

    def describe(self):
        return {}


class _FailingAlgorithm:
    name = "failing_runner_test"
    version = "1"
    league_scope = "all"

    def fit(self, training_data):
        raise RuntimeError("antrenare eșuată intenționat, pentru test")

    def predict(self, features):
        return (0.0, 0.0, 0.0, {})

    def describe(self):
        return {}


@pytest.fixture(autouse=True)
def _reset_registry():
    model_registry._clear_registry_for_tests()
    yield
    model_registry._clear_registry_for_tests()


def test_run_training_success(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    model_registry.register(_DummyAlgorithm())

    report = run_training("dummy_runner_test", "1")

    assert report.algorithm_name == "dummy_runner_test"
    assert report.result.status == "trained"
    assert Path(report.saved_to).exists()


def test_run_training_unknown_algorithm_raises():
    with pytest.raises(KeyError):
        run_training("nu-exista", "1")


def test_run_training_propagates_fit_exception():
    model_registry.register(_FailingAlgorithm())
    with pytest.raises(RuntimeError):
        run_training("failing_runner_test", "1")
