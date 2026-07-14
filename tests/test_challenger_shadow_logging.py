"""
Teste pentru Pasul 3 (Implementation Contract Learning Core) — shadow
logging pentru un Challenger activ, ADR-017. Fără rețea — toate
dependențele (challenger_manager, learning_core.challenger_shadow,
shadow_testing) sunt monkeypatch-uite.

Cele DOUĂ condiții impuse explicit de Chief Architect, verificate direct:
  1. Predicția servită (`pred`) e neschimbată, indiferent dacă flag-ul e
     activ sau nu, indiferent de ce se întâmplă în interiorul shadow logging
     (inclusiv excepții).
  2. Shadow e complet eliminabil printr-un singur flag — dezactivat
     (implicit), metoda face return imediat, ZERO import/apel suplimentar
     (verificat prin monkeypatch care ridică excepție dacă e atins).
"""
import copy
import inspect

import pytest

import oracle_engine
from oracle_engine import H2HRecord, MatchPrediction, TeamProfile


def _make_team_profile(name: str) -> TeamProfile:
    return TeamProfile(
        team_id="t1", team_name=name, matches_analysed=10,
        avg_goals_for=1.5, avg_goals_against=1.0, avg_shots_ot=4.0,
        avg_possession=50.0, offensive_rating=1.1, defensive_rating=0.9,
        form_results=["W", "D", "L"], form_score=0.5, standings_form="",
        elo_rating=1550, data_source="test", data_quality="real",
        data_quality_note="",
    )


def _make_pred(**overrides) -> MatchPrediction:
    base = dict(
        fixture_id="fx-1", home_team="Home FC", away_team="Away FC",
        league="Test League", kickoff_utc="2026-07-14T18:00:00Z",
        kickoff_date="2026-07-14", season=2026,
        home_xg=1.4, away_xg=1.1,
        prob_home_win=0.45, prob_draw=0.28, prob_away_win=0.27,
        top_scores=[], bk_home_odds=2.1, bk_draw_odds=3.3, bk_away_odds=3.6,
        bookmaker_name="test-bk",
        impl_home_pct=45.0, impl_draw_pct=28.0, impl_away_pct=27.0,
        edge_home_pct=0.0, edge_draw_pct=0.0, edge_away_pct=0.0,
        value_bets=[], weather_note="", weather_penalty=0.0,
        kelly_stakes={}, home_profile=None, away_profile=None, h2h=None,
        data_quality_home="real", data_quality_away="real",
        home_injury_report=None, away_injury_report=None, injury_note="",
        home_xg_pre_injury=1.4, away_xg_pre_injury=1.1,
    )
    base.update(overrides)
    return MatchPrediction(**base)


class _FakeEngine:
    """Instanță minimală, fără Supabase/API real — identic ca tipar cu
    FakeEngine din tests/test_oracle_engine_compat.py."""
    _build_ml_features = oracle_engine.FootballOracleEngine._build_ml_features
    _log_challenger_shadow = oracle_engine.FootballOracleEngine._log_challenger_shadow

    def __init__(self, config: dict):
        self.config = config


def _call_args():
    home_p = _make_team_profile("Home FC")
    away_p = _make_team_profile("Away FC")
    h2h = H2HRecord.empty("Home FC", "Away FC")
    return dict(
        pred=_make_pred(), home_p=home_p, away_p=away_p, h2h=h2h,
        home_xg=1.4, away_xg=1.1, ph=0.45, pd_=0.28, pa=0.27,
        mc={"mc_prob_home": 0.44, "mc_prob_draw": 0.29, "mc_prob_away": 0.27},
        weather_penalty=0.0,
    )


# ── Gating: flag oprit (implicit) ───────────────────────────────────────────

def test_challenger_shadow_logging_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["challenger_shadow_logging_enabled"] is False


def test_default_config_preserves_shadow_mode_key():
    """Regresie: noul flag nu trebuie sa elimine/schimbe shadow_mode_enabled,
    deja existent si folosit de un experiment separat."""
    assert oracle_engine.DEFAULT_CONFIG["shadow_mode_enabled"] is False


def test_log_challenger_shadow_returns_false_when_disabled(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("challenger_manager.get_active_challenger NU trebuie atins cand flag-ul e oprit")

    monkeypatch.setattr("learning_core.challenger_manager.get_active_challenger", _boom)

    engine = _FakeEngine(config={"challenger_shadow_logging_enabled": False})
    result = engine._log_challenger_shadow(**_call_args())
    assert result is False


def test_log_challenger_shadow_called_exactly_once_in_evaluate_match():
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def _log_challenger_shadow(")
    call_count = source.count("self._log_challenger_shadow(")
    assert def_count == 1
    assert call_count == 1


# ── Condiția 1: pred neschimbată, în orice scenariu ─────────────────────────

def test_pred_unchanged_when_flag_disabled():
    args = _call_args()
    pred_before = copy.deepcopy(args["pred"])

    engine = _FakeEngine(config={"challenger_shadow_logging_enabled": False})
    engine._log_challenger_shadow(**args)

    assert args["pred"] == pred_before


def test_pred_unchanged_when_flag_enabled_and_challenger_active(monkeypatch):
    args = _call_args()
    pred_before = copy.deepcopy(args["pred"])

    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-xyz"},
    )
    monkeypatch.setattr(
        "learning_core.challenger_shadow.predict_with_challenger",
        lambda features, run_id: (0.9, 0.05, 0.05),
    )
    logged_calls = []
    monkeypatch.setattr(
        "shadow_testing.log_shadow_prediction",
        lambda **kw: logged_calls.append(kw) or True,
    )

    engine = _FakeEngine(config={"challenger_shadow_logging_enabled": True})
    result = engine._log_challenger_shadow(**args)

    assert args["pred"] == pred_before, "pred nu trebuie modificat, indiferent de shadow logging"
    assert result is True
    assert len(logged_calls) == 2


def test_pred_unchanged_even_if_shadow_logging_raises(monkeypatch):
    args = _call_args()
    pred_before = copy.deepcopy(args["pred"])

    def _boom(*a, **kw):
        raise RuntimeError("eroare simulata in shadow logging")

    monkeypatch.setattr("learning_core.challenger_manager.get_active_challenger", _boom)

    engine = _FakeEngine(config={"challenger_shadow_logging_enabled": True})
    result = engine._log_challenger_shadow(**args)

    assert args["pred"] == pred_before
    assert result is False


# ── Comportament când flag-ul e activ ───────────────────────────────────────

def test_noop_when_no_active_challenger(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: None,
    )

    def _fail_if_called(**kw):
        raise AssertionError("shadow_testing.log_shadow_prediction nu trebuie apelat fara Challenger activ")

    monkeypatch.setattr("shadow_testing.log_shadow_prediction", _fail_if_called)

    engine = _FakeEngine(config={"challenger_shadow_logging_enabled": True})
    result = engine._log_challenger_shadow(**_call_args())
    assert result is False


def test_noop_when_artifact_unavailable(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-xyz"},
    )
    monkeypatch.setattr(
        "learning_core.challenger_shadow.predict_with_challenger",
        lambda features, run_id: None,
    )

    def _fail_if_called(**kw):
        raise AssertionError("shadow_testing.log_shadow_prediction nu trebuie apelat fara artefact valid")

    monkeypatch.setattr("shadow_testing.log_shadow_prediction", _fail_if_called)

    engine = _FakeEngine(config={"challenger_shadow_logging_enabled": True})
    result = engine._log_challenger_shadow(**_call_args())
    assert result is False


def test_logs_treatment_and_control_with_correct_groups(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-xyz"},
    )
    monkeypatch.setattr(
        "learning_core.challenger_shadow.predict_with_challenger",
        lambda features, run_id: (0.9, 0.05, 0.05),
    )
    logged_calls = []
    monkeypatch.setattr(
        "shadow_testing.log_shadow_prediction",
        lambda **kw: logged_calls.append(kw) or True,
    )

    engine = _FakeEngine(config={"challenger_shadow_logging_enabled": True})
    args = _call_args()
    result = engine._log_challenger_shadow(**args)

    assert result is True
    assert len(logged_calls) == 2
    groups = {c["experiment_group"] for c in logged_calls}
    assert groups == {"treatment", "control"}

    treatment = next(c for c in logged_calls if c["experiment_group"] == "treatment")
    assert treatment["prob_home"] == 0.9
    assert treatment["experiment_version"] == "run-xyz"

    control = next(c for c in logged_calls if c["experiment_group"] == "control")
    assert control["prob_home"] == args["pred"].prob_home_win
    assert control["prob_draw"] == args["pred"].prob_draw
    assert control["prob_away"] == args["pred"].prob_away_win


# ── Condiția 2: complet eliminabil printr-un singur flag ────────────────────

def test_flag_off_touches_zero_learning_core_modules(monkeypatch):
    """Cu flag-ul oprit, metoda nu trebuie sa importe/atinga NIMIC din
    learning_core sau shadow_testing — verificat prin module fabricate
    care ridica exceptie daca sunt atinse in vreun fel."""
    import sys

    class _PoisonModule:
        def __getattr__(self, name):
            raise AssertionError(f"modul atins desi flag-ul e oprit: {name}")

    monkeypatch.setitem(sys.modules, "shadow_testing", _PoisonModule())

    engine = _FakeEngine(config={"challenger_shadow_logging_enabled": False})
    result = engine._log_challenger_shadow(**_call_args())
    assert result is False
