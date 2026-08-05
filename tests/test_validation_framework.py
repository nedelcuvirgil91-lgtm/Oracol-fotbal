"""
Teste pentru Validation Framework (ADR-052) — validation_framework.py
(construcția rândului + persistare) și frontiera cu oracle_engine.py
(_log_validation_snapshot). Fără rețea — Supabase mockuit prin monkeypatch.

Invarianți verificați:
  1. Flag oprit (implicit) => zero apel spre validation_framework, zero scriere.
  2. Flag activ => validation_framework.save_snapshot(pred) apelat exact o dată.
  3. Rândul construit conține întotdeauna Oracle; ML/Blend doar dacă
     disponibile pe `pred` la momentul apelului.
  4. Excepție (în construcția rândului sau în scriere) => False, nu propagă.
  5. pred nu e mutat de acest modul (pur observațional).
  6. Nu afectează Oracle/ML/Blend — rulează DUPĂ ce toate trei sunt deja calculate.
"""
import inspect

import oracle_engine
import validation_framework
from oracle_engine import MatchPrediction


def _make_pred(**overrides) -> MatchPrediction:
    base = dict(
        fixture_id="fx-1", home_team="Home FC", away_team="Away FC",
        league="Test League", kickoff_utc="2026-07-14T18:00:00Z",
        kickoff_date="2026-07-14", season=2026,
        home_xg=1.4, away_xg=1.1,
        prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25,
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


# ── _build_snapshot_row ─────────────────────────────────────────────────────

def test_build_snapshot_row_always_contains_oracle():
    pred = _make_pred(prob_home_win=0.5, prob_draw=0.3, prob_away_win=0.2)
    row = validation_framework._build_snapshot_row(pred)
    assert row["oracle_prob_home"] == 0.5
    assert row["oracle_prob_draw"] == 0.3
    assert row["oracle_prob_away"] == 0.2
    assert row["fixture_id"] == "fx-1"


def test_build_snapshot_row_ml_available_true():
    pred = _make_pred(ml_engine_prediction={"available": True, "prob_home": 0.6, "prob_draw": 0.2, "prob_away": 0.2})
    row = validation_framework._build_snapshot_row(pred)
    assert row["ml_available"] is True
    assert (row["ml_prob_home"], row["ml_prob_draw"], row["ml_prob_away"]) == (0.6, 0.2, 0.2)


def test_build_snapshot_row_ml_unavailable_with_reason():
    pred = _make_pred(ml_engine_prediction={"available": False, "reason": "model_indisponibil"})
    row = validation_framework._build_snapshot_row(pred)
    assert row["ml_available"] is False
    assert row["ml_prob_home"] is None
    assert row["ml_prob_draw"] is None
    assert row["ml_prob_away"] is None


def test_build_snapshot_row_ml_none_flag_off():
    pred = _make_pred()  # ml_engine_prediction=None implicit
    row = validation_framework._build_snapshot_row(pred)
    assert row["ml_available"] is False
    assert row["ml_prob_home"] is None


def test_build_snapshot_row_blend_present():
    pred = _make_pred(blend_engine_prediction={"prob_home": 0.5, "prob_draw": 0.25, "prob_away": 0.25})
    row = validation_framework._build_snapshot_row(pred)
    assert row["blend_available"] is True
    assert (row["blend_prob_home"], row["blend_prob_draw"], row["blend_prob_away"]) == (0.5, 0.25, 0.25)


def test_build_snapshot_row_blend_absent():
    pred = _make_pred()  # blend_engine_prediction=None implicit
    row = validation_framework._build_snapshot_row(pred)
    assert row["blend_available"] is False
    assert row["blend_prob_home"] is None


# ── save_snapshot ────────────────────────────────────────────────────────────

def test_save_snapshot_calls_supabase_writer_with_built_row(monkeypatch):
    captured = {}

    def _fake_save(row):
        captured["row"] = row
        return True

    import supabase_client as sb
    monkeypatch.setattr(sb, "save_engine_comparison_snapshot", _fake_save)

    pred = _make_pred(prob_home_win=0.5, prob_draw=0.3, prob_away_win=0.2)
    result = validation_framework.save_snapshot(pred)

    assert result is True
    assert captured["row"]["oracle_prob_home"] == 0.5


def test_save_snapshot_returns_false_when_supabase_write_fails(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "save_engine_comparison_snapshot", lambda row: False)
    assert validation_framework.save_snapshot(_make_pred()) is False


def test_save_snapshot_swallows_unexpected_exception(monkeypatch):
    import supabase_client as sb

    def _boom(row):
        raise RuntimeError("eroare simulata")

    monkeypatch.setattr(sb, "save_engine_comparison_snapshot", _boom)
    assert validation_framework.save_snapshot(_make_pred()) is False


def test_save_snapshot_does_not_mutate_pred():
    pred = _make_pred(prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25)
    before = (pred.prob_home_win, pred.prob_draw, pred.prob_away_win,
              pred.ml_engine_prediction, pred.blend_engine_prediction)
    validation_framework.save_snapshot(pred)  # Supabase indisponibil in test => False, dar nu trebuie sa muteze pred
    after = (pred.prob_home_win, pred.prob_draw, pred.prob_away_win,
             pred.ml_engine_prediction, pred.blend_engine_prediction)
    assert before == after


# ── Frontiera oracle_engine.py <-> validation_framework.py ─────────────────

class _FakeEngine:
    _log_validation_snapshot = oracle_engine.FootballOracleEngine._log_validation_snapshot

    def __init__(self, config: dict):
        self.config = config


def test_validation_framework_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["validation_framework_enabled"] is False


def test_log_validation_snapshot_noop_when_flag_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(validation_framework, "save_snapshot", lambda pred: calls.append(pred) or True)

    engine = _FakeEngine(config={"validation_framework_enabled": False})
    result = engine._log_validation_snapshot(_make_pred())

    assert result is False
    assert calls == []


def test_log_validation_snapshot_calls_module_when_enabled(monkeypatch):
    calls = []
    monkeypatch.setattr(validation_framework, "save_snapshot", lambda pred: calls.append(pred) or True)

    engine = _FakeEngine(config={"validation_framework_enabled": True})
    pred = _make_pred()
    result = engine._log_validation_snapshot(pred)

    assert result is True
    assert calls == [pred]


def test_log_validation_snapshot_swallows_exception(monkeypatch):
    def _boom(pred):
        raise RuntimeError("eroare simulata in validation_framework")

    monkeypatch.setattr(validation_framework, "save_snapshot", _boom)
    engine = _FakeEngine(config={"validation_framework_enabled": True})
    assert engine._log_validation_snapshot(_make_pred()) is False


def test_log_validation_snapshot_called_exactly_once_in_evaluate_match():
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def _log_validation_snapshot(")
    call_count = source.count("self._log_validation_snapshot(")
    assert def_count == 1
    assert call_count == 1
