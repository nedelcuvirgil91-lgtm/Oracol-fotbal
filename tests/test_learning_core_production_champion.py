"""Teste pentru learning_core.algorithms.production_champion — fără rețea,
fără Supabase live.

IMPORTANT: FootballOracleEngine() NU e sigur de construit implicit în teste —
declanșează, prin FootballOracleAPI._validate_api_keys(), o încercare reală
de apel de rețea (descoperit la verificare directă, vezi commit-ul care a
introdus lazy loading în ProductionChampionAdapter). Aceste teste evită
construcția reală a engine-ului acolo unde nu e strict necesară pentru ce se
testează — injectează un obiect fals doar pentru testul care are nevoie de
comportamentul de eroare al evaluate_match()."""
from learning_core import model_registry
from learning_core.algorithms.production_champion import ProductionChampionAdapter


def test_production_champion_conforms_to_protocol():
    algo = ProductionChampionAdapter()
    assert isinstance(algo, model_registry.LearningAlgorithm)
    assert algo.name == "production_champion"


def test_production_champion_constructor_does_not_build_engine():
    """Constructorul rămâne ieftin — engine-ul real (cu costul lui de rețea)
    se construiește doar la prima utilizare efectivă, nu la instanțiere."""
    algo = ProductionChampionAdapter()
    assert algo._engine is None


def test_production_champion_fit_is_no_op():
    algo = ProductionChampionAdapter()
    result = algo.fit()
    assert result.status == "not_applicable"
    assert result.samples_used == 0
    assert algo._engine is None  # fit() nu atinge deloc engine-ul


def test_production_champion_predict_invalid_match_returns_safe_default():
    """Injectează un engine fals care reproduce exact eroarea reală
    (KeyError la match["home_team"] lipsă) — testează gestionarea erorii din
    adaptor, fără să construiască FootballOracleEngine real."""
    algo = ProductionChampionAdapter()

    class _FakeEngineMissingKey:
        def evaluate_match(self, match):
            return match["home_team"]  # provoacă exact KeyError-ul real pt {}

    algo._engine = _FakeEngineMissingKey()
    ph, pd, pa, meta = algo.predict({})
    assert (ph, pd, pa) == (0.0, 0.0, 0.0)
    assert "error" in meta


def test_production_champion_describe_does_not_construct_engine():
    algo = ProductionChampionAdapter()
    d = algo.describe()
    assert d["algorithm_family"] == "production_champion"
    assert d["wraps"] == "oracle_engine.FootballOracleEngine.evaluate_match"
    assert d["engine_constructed"] is False
    assert algo._engine is None


def test_production_champion_get_trained_model_always_none():
    """Niciodata un model real — fit() e no-op (ADR-048, Pasul 9)."""
    algo = ProductionChampionAdapter()
    assert algo.get_trained_model() is None
    algo.fit()
    assert algo.get_trained_model() is None
