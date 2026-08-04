"""Teste pentru learning_core.model_registry — fără rețea, fără Supabase live."""
import pytest

from learning_core import model_registry


@pytest.fixture(autouse=True)
def _reset_registry():
    model_registry._clear_registry_for_tests()
    yield
    model_registry._clear_registry_for_tests()


class _DummyAlgorithm:
    name = "dummy"
    version = "1"
    league_scope = "all"

    def fit(self, training_data):
        return model_registry.TrainingRunResult(
            training_run_id="test-run", status="trained", samples_used=10,
        )

    def predict(self, features):
        return (0.4, 0.3, 0.3, {})

    def describe(self):
        return {"algorithm_family": self.name}

    def get_trained_model(self):
        return None


def test_register_and_get():
    algo = _DummyAlgorithm()
    model_registry.register(algo)
    fetched = model_registry.get("dummy", "1")
    assert fetched is algo


def test_get_unknown_raises():
    with pytest.raises(KeyError):
        model_registry.get("nu-exista", "1")


def test_register_duplicate_raises():
    model_registry.register(_DummyAlgorithm())
    with pytest.raises(ValueError):
        model_registry.register(_DummyAlgorithm())


def test_list_available():
    model_registry.register(_DummyAlgorithm())
    assert model_registry.list_available() == [("dummy", "1")]


def test_dummy_conforms_to_protocol():
    algo = _DummyAlgorithm()
    assert isinstance(algo, model_registry.LearningAlgorithm)
