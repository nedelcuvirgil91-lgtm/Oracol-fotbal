"""
Teste pentru learning_core.algorithms.league_weights_adaptive (ADR-028) —
fără rețea, fără Supabase live. run_bootstrap() e monkeypatch-uit direct
(mecanica lui proprie e deja acoperită de suita bootstrap_league_learning).
"""
from learning_core import model_registry
from learning_core.algorithms.league_weights_adaptive import LeagueWeightsAdaptiveAlgorithm


def test_adapter_conforms_to_protocol():
    algo = LeagueWeightsAdaptiveAlgorithm()
    assert isinstance(algo, model_registry.LearningAlgorithm)
    assert algo.name == "league_weights_adaptive"
    assert algo.league_scope == "all"


def test_describe_opts_out_of_challenger_framework():
    """[ADR-028, Varianta A] Flag citit generic de continuous_learning.py —
    previne crearea unui Challenger 'zombie' fara cale spre evaluare reala."""
    d = LeagueWeightsAdaptiveAlgorithm().describe()
    assert d["algorithm_family"] == "league_weights_adaptive"
    assert d["participates_in_challenger_framework"] is False


def test_predict_never_produces_real_probabilities():
    """Recalibrarea ajusteaza doar ponderi, nu e un model de predictie 1X2 —
    predict() exista exclusiv pentru conformitate cu Protocolul."""
    ph, pd, pa, meta = LeagueWeightsAdaptiveAlgorithm().predict({"orice": "feature"})
    assert (ph, pd, pa) == (0.0, 0.0, 0.0)
    assert "error" in meta


def test_fit_delegates_to_bootstrap_with_dry_run_always_true(monkeypatch):
    """Garanția centrală ceruta explicit: fit() nu are voie sa scrie in
    model_weights de productie - dry_run=True, indiferent de argumente."""
    captured = {}

    def fake_run_bootstrap(**kwargs):
        captured.update(kwargs)
        return {
            "processed": 1200, "recalibrated": 300, "stable": 900,
            "leagues_with_data": 9, "leagues_total": 9,
            "elapsed_seconds": 4.2, "cutoff_date": "2021-07-01",
        }

    import sync.bootstrap_league_learning as bll
    monkeypatch.setattr(bll, "run_bootstrap", fake_run_bootstrap)

    result = LeagueWeightsAdaptiveAlgorithm().fit(None)

    assert captured.get("dry_run") is True
    assert result.status == "trained"
    assert result.samples_used == 1200
    assert result.walk_forward_metrics["leagues_with_data"] == 9
    assert result.training_run_id


def test_fit_zero_matches_processed_returns_insufficient_data(monkeypatch):
    def fake_run_bootstrap(**kwargs):
        return {"processed": 0, "recalibrated": 0, "stable": 0,
                "leagues_with_data": 0, "leagues_total": 9}

    import sync.bootstrap_league_learning as bll
    monkeypatch.setattr(bll, "run_bootstrap", fake_run_bootstrap)

    result = LeagueWeightsAdaptiveAlgorithm().fit(None)

    assert result.status == "insufficient_data"
    assert result.samples_used == 0


def test_registrable_in_model_registry():
    model_registry._clear_registry_for_tests()
    try:
        model_registry.register(LeagueWeightsAdaptiveAlgorithm())
        fetched = model_registry.get("league_weights_adaptive", "1")
        assert fetched.name == "league_weights_adaptive"
        assert ("league_weights_adaptive", "1") in model_registry.list_available()
    finally:
        model_registry._clear_registry_for_tests()
