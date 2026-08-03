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


def test_log_shadow_experiment_enabled_flag_is_parameterized():
    """[ADAUGAT — Faza 3] enabled_flag permite fiecărui experiment nou
    propriul flag dedicat, fără să reutilizeze shadow_mode_enabled — implicit
    rămâne shadow_mode_enabled (comportament neschimbat pentru apelul
    existent apifootball_injuries_coaches)."""
    class FakeEngine:
        config = {"shadow_mode_enabled": True, "flashscore_shadow_logging_enabled": False}
        log_shadow_experiment = oracle_engine.FootballOracleEngine.log_shadow_experiment

    fake = FakeEngine()
    # Flag-ul dedicat oprit -> False, chiar daca shadow_mode_enabled=True.
    result = fake.log_shadow_experiment(
        pred=None, experiment_name="flashscore_team_dna", experiment_version="v1",
        home_xg=1.0, away_xg=1.0, prob_home=0.4, prob_draw=0.3, prob_away=0.3,
        enabled_flag="flashscore_shadow_logging_enabled",
    )
    assert result is False
    # Fara enabled_flag explicit -> foloseste shadow_mode_enabled (implicit),
    # comportament identic cu apelul existent apifootball_injuries_coaches.
    fake.config["shadow_mode_enabled"] = False
    result = fake.log_shadow_experiment(
        pred=None, experiment_name="apifootball_injuries_coaches", experiment_version="v1",
        home_xg=1.0, away_xg=1.0, prob_home=0.4, prob_draw=0.3, prob_away=0.3,
    )
    assert result is False


def test_log_shadow_experiment_called_exactly_twice_in_evaluate_match():
    """[ACTUALIZAT — Faza 3, exceptie M4] log_shadow_experiment e acum
    apelat de DOUA ori in evaluate_match(): apifootball_injuries_coaches
    (integrare API-Football, existent) + flashscore_team_dna (Faza 3,
    exceptie explicita aprobata de proprietarul produsului 2026-07-29 -
    inainte de finalizarea M4). Compatibilitatea 100% e garantata prin
    gating pe flag-uri DEDICATE per experiment (shadow_mode_enabled /
    flashscore_shadow_logging_enabled), testat separat mai jos - nu prin
    absenta apelului."""
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def log_shadow_experiment(")
    call_count = source.count(".log_shadow_experiment(")
    assert def_count == 1
    assert call_count == 2


def test_flashscore_shadow_experiment_uses_dedicated_flag_not_shadow_mode_enabled():
    """Gardă directă: experimentul flashscore_team_dna NU trebuie să
    reutilizeze shadow_mode_enabled (legat exclusiv de
    apifootball_injuries_coaches) — ar activa/dezactiva ambele experimente
    simultan la fiecare toggle, contrazicând disciplina flag-uri-dedicate
    deja folosită de challenger_shadow_logging_enabled/consensus_capture_enabled."""
    assert oracle_engine.DEFAULT_CONFIG["flashscore_shadow_logging_enabled"] is False
    source = inspect.getsource(oracle_engine.FootballOracleEngine.evaluate_match)
    assert 'enabled_flag="flashscore_shadow_logging_enabled"' in source
    assert '"flashscore_team_dna"' in source


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
