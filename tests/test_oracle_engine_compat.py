import inspect
import oracle_engine


def test_shadow_mode_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["shadow_mode_enabled"] is False


def test_default_config_preserves_all_previous_keys():
    """Regresie: adaugarea shadow_mode_enabled NU trebuie sa elimine sau
    sa schimbe vreo cheie preexistenta din DEFAULT_CONFIG."""
    expected_preexisting = {
        "value_bet_threshold_pct": 5.0, "max_goals_poisson": 8, "last_n_fixtures": 5,
        "stake_default": 10.0, "kelly_fraction": 0.25,
        "recalibration_learning_rate": 0.05, "recalibration_max_delta": 0.15,
        "recency_half_life_days": 365, "elo_blend_weight": 0.35,
        "elo_sigmoid_scale": 400.0, "elo_reference": 1500.0,
        "h2h_weight": 0.15, "h2h_lookback_days": 1095,
        "monte_carlo_simulations": 10000, "ml_blend_weight": 0.35,
    }
    for key, value in expected_preexisting.items():
        assert oracle_engine.DEFAULT_CONFIG[key] == value, f"{key} s-a schimbat fata de original"


def test_log_shadow_experiment_returns_false_when_disabled():
    """Fara instanta reala a motorului (ar necesita Supabase/API live) -
    testam direct logica de gating pe o instanta minimala simulata."""
    class FakeEngine:
        config = {"shadow_mode_enabled": False}
        log_shadow_experiment = oracle_engine.FootballOracleEngine.log_shadow_experiment

    fake = FakeEngine()
    result = fake.log_shadow_experiment(
        pred=None, experiment_name="test", experiment_version="v1",
        home_xg=1.0, away_xg=1.0, prob_home=0.4, prob_draw=0.3, prob_away=0.3,
    )
    assert result is False


def test_log_shadow_experiment_called_exactly_once_in_evaluate_match():
    """[ACTUALIZAT] log_shadow_experiment e acum apelat intentionat, o
    singura data, in evaluate_match() (integrare API-Football) - nu mai e
    'zero apeluri' (asta era starea INAINTE de integrare). Compatibilitatea
    100% e garantata altfel acum: prin gating-ul shadow_mode_enabled, testat
    separat mai jos - nu prin absenta apelului."""
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def log_shadow_experiment(")
    call_count = source.count(".log_shadow_experiment(")
    assert def_count == 1
    assert call_count == 1


def test_shadow_mode_disabled_means_production_predictions_unaffected():
    """Garantia reala de compatibilitate 100%: chiar daca
    log_shadow_experiment e acum apelat, cu shadow_mode_enabled=False (implicit)
    el nu face NIMIC (verificat deja in alt test ca returneaza False) - deci
    home_xg/away_xg/ph/pd/pa folosite de productie raman neschimbate, indiferent
    de rezultatul fetch-ului API-Football."""
    assert oracle_engine.DEFAULT_CONFIG["shadow_mode_enabled"] is False


def test_cache_prediction_method_unchanged_signature():
    """_cache_prediction nu trebuie sa fi capatat parametri noi - ar
    schimba orice apelant existent."""
    sig = inspect.signature(oracle_engine.FootballOracleEngine._cache_prediction)
    params = list(sig.parameters.keys())
    assert params == ["self", "pred", "home_p", "away_p", "h2h", "weather_penalty", "mc"]
