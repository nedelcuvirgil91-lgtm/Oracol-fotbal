"""Teste pentru learning_core.challenger_runner — fără rețea, fără Supabase live."""
import pytest

from learning_core import model_registry
from learning_core.bootstrap import register_default_algorithms
from learning_core.challenger_runner import run_challenger


class _AlgoA:
    name = "algo_a"
    version = "1"
    league_scope = "all"

    def fit(self, training_data):
        raise NotImplementedError

    def predict(self, features):
        return (0.5, 0.3, 0.2, {"source": "a"})

    def describe(self):
        return {}


class _AlgoB:
    name = "algo_b"
    version = "1"
    league_scope = "all"

    def fit(self, training_data):
        raise NotImplementedError

    def predict(self, features):
        return (0.4, 0.35, 0.25, {"source": "b"})

    def describe(self):
        return {}


class _CrashingAlgo:
    """Simulează un algoritm oarecare al cărui predict() aruncă o excepție
    neașteptată — testează cerința "orice algoritm din Model Registry"."""
    name = "crashing_algo"
    version = "1"
    league_scope = "all"

    def fit(self, training_data):
        raise NotImplementedError

    def predict(self, features):
        raise RuntimeError("boom")

    def describe(self):
        return {}


@pytest.fixture(autouse=True)
def _reset_registry():
    model_registry._clear_registry_for_tests()
    yield
    model_registry._clear_registry_for_tests()


def test_run_challenger_computes_delta():
    model_registry.register(_AlgoA())
    model_registry.register(_AlgoB())

    result = run_challenger("algo_b", "1", {}, champion_name="algo_a", champion_version="1")

    assert result.champion.algorithm_name == "algo_a"
    assert result.challenger.algorithm_name == "algo_b"
    assert result.probability_delta["home"] == pytest.approx(-0.1)
    assert result.probability_delta["draw"] == pytest.approx(0.05)
    assert result.probability_delta["away"] == pytest.approx(0.05)


def test_run_challenger_unknown_algorithm_raises():
    model_registry.register(_AlgoA())
    with pytest.raises(KeyError):
        run_challenger("nu-exista", "1", {}, champion_name="algo_a", champion_version="1")


def test_run_challenger_unknown_champion_raises():
    model_registry.register(_AlgoB())
    with pytest.raises(KeyError):
        run_challenger("algo_b", "1", {}, champion_name="nu-exista", champion_version="1")


def test_run_challenger_handles_predict_exception_gracefully():
    model_registry.register(_AlgoA())
    model_registry.register(_CrashingAlgo())

    result = run_challenger("crashing_algo", "1", {}, champion_name="algo_a", champion_version="1")

    assert result.challenger.prob_home == 0.0
    assert result.challenger.prob_draw == 0.0
    assert result.challenger.prob_away == 0.0
    assert "error" in result.challenger.metadata
    # campionul, neafectat de eșecul challenger-ului
    assert result.champion.prob_home == 0.5


def test_run_challenger_default_champion_is_production_champion():
    """Integrare cu algoritmii reali din bootstrap — demonstrează și
    gestionarea discrepanței de format `features` (vezi header-ul modulului):
    ambele adaptoare degradează controlat pe input gol/incompatibil, fără
    să oprească comparația.

    Injectează un engine fals în production_champion — evită construcția
    reală a FootballOracleEngine (cost de rețea la validarea cheilor API,
    vezi production_champion.py) — dar reproduce exact eroarea reală
    (KeyError la context de meci incomplet)."""
    register_default_algorithms()
    champion = model_registry.get("production_champion", "1")

    class _FakeEngine:
        def evaluate_match(self, match):
            return match["home_team"]

    champion._engine = _FakeEngine()

    result = run_challenger("xgboost_v1", "1", {})

    assert result.champion.algorithm_name == "production_champion"
    assert result.challenger.algorithm_name == "xgboost_v1"
    assert "error" in result.champion.metadata
    assert "error" in result.challenger.metadata
