"""Teste pentru learning_core.algorithms.production_champion — fără rețea,
fără Supabase live. FootballOracleEngine() nu face niciun apel de rețea la
construcție (verificat: FootballOracleAPI.__init__ doar pregătește o sesiune
HTTP, nu execută cereri)."""
from learning_core import model_registry
from learning_core.algorithms.production_champion import ProductionChampionAdapter


def test_production_champion_conforms_to_protocol():
    algo = ProductionChampionAdapter()
    assert isinstance(algo, model_registry.LearningAlgorithm)
    assert algo.name == "production_champion"


def test_production_champion_fit_is_no_op():
    algo = ProductionChampionAdapter()
    result = algo.fit()
    assert result.status == "not_applicable"
    assert result.samples_used == 0


def test_production_champion_predict_invalid_match_returns_safe_default():
    algo = ProductionChampionAdapter()
    ph, pd, pa, meta = algo.predict({})
    assert (ph, pd, pa) == (0.0, 0.0, 0.0)
    assert "error" in meta


def test_production_champion_describe():
    algo = ProductionChampionAdapter()
    d = algo.describe()
    assert d["algorithm_family"] == "production_champion"
    assert d["wraps"] == "oracle_engine.FootballOracleEngine.evaluate_match"
