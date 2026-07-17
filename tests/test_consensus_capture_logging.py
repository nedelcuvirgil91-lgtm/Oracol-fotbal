"""
Teste pentru ADR-033, Faza 1 — frontiera oracle_engine.py <->
learning_core.consensus_capture (adapter). Fără rețea.

Mirror direct al tests/test_challenger_shadow_logging.py — aceleași două
condiții impuse (pred neschimbată, complet eliminabil printr-un flag),
verificate identic pentru noul adapter.
"""
import ast
import copy
import inspect
import pathlib

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
        raw_predictions=[
            {"family": "rule_based", "engine": "oracle_protocol", "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2},
            {"family": "ml", "engine": "xgboost_v1", "prob_home": 0.55, "prob_draw": 0.25, "prob_away": 0.2},
        ],
    )
    base.update(overrides)
    return MatchPrediction(**base)


class _FakeEngine:
    """Instanță minimală, fără Supabase/API real — identic ca tipar cu
    _FakeEngine din tests/test_challenger_shadow_logging.py."""
    _log_consensus_capture = oracle_engine.FootballOracleEngine._log_consensus_capture

    def __init__(self, config: dict):
        self.config = config


# ── Gating: flag oprit (implicit) ───────────────────────────────────────────

def test_consensus_capture_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["consensus_capture_enabled"] is False


def test_default_config_preserves_challenger_shadow_key():
    """Regresie: noul flag nu trebuie sa elimine/schimbe
    challenger_shadow_logging_enabled, deja existent."""
    assert oracle_engine.DEFAULT_CONFIG["challenger_shadow_logging_enabled"] is False


def test_log_consensus_capture_returns_false_when_disabled(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("adapterul NU trebuie atins cand flag-ul e oprit")

    monkeypatch.setattr("learning_core.consensus_capture.capture_raw_predictions", _boom)

    engine = _FakeEngine(config={"consensus_capture_enabled": False})
    result = engine._log_consensus_capture(_make_pred())
    assert result is False


def test_log_consensus_capture_called_exactly_once_in_evaluate_match():
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def _log_consensus_capture(")
    call_count = source.count("self._log_consensus_capture(")
    assert def_count == 1
    assert call_count == 1


def test_oracle_engine_never_imports_consensus_validation_directly():
    """oracle_engine.py nu are voie sa importe
    learning_core.consensus_validation (Faza 2, T1) — cele doua faze
    comunica exclusiv prin tabela persistata, niciodata prin apel direct."""
    tree = ast.parse(
        pathlib.Path(oracle_engine.__file__).read_text(encoding="utf-8"),
        filename=oracle_engine.__file__,
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1] == "consensus_validation" or any(
                a.name == "consensus_validation" for a in node.names
            ):
                raise AssertionError(
                    "oracle_engine.py importă consensus_validation direct — "
                    "Faza 1 (serving) și Faza 2 (T1) trebuie să rămână complet separate"
                )
        elif isinstance(node, ast.Import):
            if any(alias.name.split(".")[-1] == "consensus_validation" for alias in node.names):
                raise AssertionError("oracle_engine.py importă consensus_validation direct")


# ── Condiția 1: pred neschimbată, în orice scenariu ─────────────────────────

def test_pred_unchanged_when_flag_disabled():
    pred = _make_pred()
    pred_before = copy.deepcopy(pred)

    engine = _FakeEngine(config={"consensus_capture_enabled": False})
    engine._log_consensus_capture(pred)

    assert pred == pred_before


def test_pred_unchanged_when_flag_enabled_and_adapter_succeeds(monkeypatch):
    pred = _make_pred()
    pred_before = copy.deepcopy(pred)

    monkeypatch.setattr("learning_core.consensus_capture.capture_raw_predictions", lambda **kw: True)

    engine = _FakeEngine(config={"consensus_capture_enabled": True})
    result = engine._log_consensus_capture(pred)

    assert pred == pred_before, "pred nu trebuie modificat, indiferent de captura"
    assert result is True


def test_pred_unchanged_even_if_adapter_raises(monkeypatch):
    """Fail-open: o exceptie in adapter nu trebuie sa propage catre
    evaluate_match() si nu trebuie sa afecteze pred."""
    pred = _make_pred()
    pred_before = copy.deepcopy(pred)

    def _boom(**kw):
        raise RuntimeError("eroare simulata in adapter (ex. Supabase indisponibil)")

    monkeypatch.setattr("learning_core.consensus_capture.capture_raw_predictions", _boom)

    engine = _FakeEngine(config={"consensus_capture_enabled": True})
    result = engine._log_consensus_capture(pred)

    assert pred == pred_before
    assert result is False


def test_adapter_receives_correct_arguments(monkeypatch):
    captured = {}

    def _capture(**kw):
        captured.update(kw)
        return True

    monkeypatch.setattr("learning_core.consensus_capture.capture_raw_predictions", _capture)

    engine = _FakeEngine(config={"consensus_capture_enabled": True})
    pred = _make_pred()
    engine._log_consensus_capture(pred)

    assert captured["fixture_id"] == pred.fixture_id
    assert captured["raw_predictions"] == pred.raw_predictions
    assert captured["league"] == pred.league
    assert captured["home_team"] == pred.home_team
    assert captured["away_team"] == pred.away_team
    assert captured["kickoff_date"] == pred.kickoff_date


# ── Condiția 2: complet eliminabil printr-un singur flag ────────────────────

def test_flag_off_touches_zero_learning_core_modules(monkeypatch):
    import sys

    class _PoisonModule:
        def __getattr__(self, name):
            raise AssertionError(f"modul atins desi flag-ul e oprit: {name}")

    monkeypatch.setitem(sys.modules, "learning_core.consensus_capture", _PoisonModule())

    engine = _FakeEngine(config={"consensus_capture_enabled": False})
    result = engine._log_consensus_capture(_make_pred())
    assert result is False
