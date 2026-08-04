"""
Teste pentru Pasul 13 (derivat din ADR-050) — shadow logging pentru un
Challenger de tip Blend activ. Tipar identic
tests/test_challenger_shadow_logging.py, dar pentru
`oracle_engine._log_blend_challenger_shadow()` /
`learning_core.blend_challenger_shadow`.

Acest fișier testează exclusiv FRONTIERA oracle_engine.py <->
learning_core.blend_challenger_shadow — comportamentul intern al
adapterului e testat separat, în tests/test_blend_challenger_shadow.py.

Condițiile impuse de ADR-050 §7.1 (Invariant arhitectural), verificate
direct:
  1. Predicția servită (`pred`) e neschimbată, indiferent dacă flag-ul e
     activ sau nu, indiferent de ce se întâmplă în interiorul shadow
     logging (inclusiv excepții) — shadow rămâne strict read-only.
  2. Shadow e complet eliminabil printr-un singur flag
     (blend_challenger_shadow_logging_enabled) — dezactivat (implicit),
     metoda face return imediat, ZERO import/apel suplimentar.

Plus garda structurală cerută explicit de Implementation Plan Pasul 13 §5:
`learning_core/challenger_shadow.py` (calea Challenger-ului xgboost_v1)
rămâne neatins — semnăturile publice sunt identice cu cele de dinainte de
acest pas, și niciun modul nou nu îl importă.
"""
import ast
import copy
import inspect
import pathlib

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
    _FakeEngine din tests/test_challenger_shadow_logging.py."""
    _build_ml_features = oracle_engine.FootballOracleEngine._build_ml_features
    _log_blend_challenger_shadow = oracle_engine.FootballOracleEngine._log_blend_challenger_shadow

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

def test_blend_challenger_shadow_logging_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["blend_challenger_shadow_logging_enabled"] is False


def test_default_config_preserves_xgboost_challenger_shadow_key():
    """Regresie: noul flag dedicat NU trebuie sa elimine/schimbe
    challenger_shadow_logging_enabled, care ramane exclusiv pentru
    Challenger-ul xgboost_v1 (ADR-050 §4)."""
    assert oracle_engine.DEFAULT_CONFIG["challenger_shadow_logging_enabled"] is False


def test_log_blend_challenger_shadow_returns_false_when_disabled(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError("adapterul Blend NU trebuie atins cand flag-ul e oprit")

    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.log_shadow_for_active_blend_challenger", _boom,
    )

    engine = _FakeEngine(config={"blend_challenger_shadow_logging_enabled": False})
    result = engine._log_blend_challenger_shadow(**_call_args())
    assert result is False


def test_log_blend_challenger_shadow_called_exactly_once_in_evaluate_match():
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def _log_blend_challenger_shadow(")
    call_count = source.count("self._log_blend_challenger_shadow(")
    assert def_count == 1
    assert call_count == 1


# ── Condiția 1: pred neschimbată, în orice scenariu ─────────────────────────

def test_pred_unchanged_when_flag_disabled():
    args = _call_args()
    pred_before = copy.deepcopy(args["pred"])

    engine = _FakeEngine(config={"blend_challenger_shadow_logging_enabled": False})
    engine._log_blend_challenger_shadow(**args)

    assert args["pred"] == pred_before


def test_pred_unchanged_when_flag_enabled_and_adapter_succeeds(monkeypatch):
    args = _call_args()
    pred_before = copy.deepcopy(args["pred"])

    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.log_shadow_for_active_blend_challenger",
        lambda **kw: True,
    )

    engine = _FakeEngine(config={"blend_challenger_shadow_logging_enabled": True})
    result = engine._log_blend_challenger_shadow(**args)

    assert args["pred"] == pred_before, "pred nu trebuie modificat, indiferent de shadow logging"
    assert result is True


def test_pred_unchanged_even_if_adapter_raises(monkeypatch):
    args = _call_args()
    pred_before = copy.deepcopy(args["pred"])

    def _boom(**kw):
        raise RuntimeError("eroare simulata in adapter Blend")

    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.log_shadow_for_active_blend_challenger", _boom,
    )

    engine = _FakeEngine(config={"blend_challenger_shadow_logging_enabled": True})
    result = engine._log_blend_challenger_shadow(**args)

    assert args["pred"] == pred_before
    assert result is False


def test_adapter_receives_correct_arguments(monkeypatch):
    captured = {}

    def _capture(**kw):
        captured.update(kw)
        return True

    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.log_shadow_for_active_blend_challenger", _capture,
    )

    engine = _FakeEngine(config={"blend_challenger_shadow_logging_enabled": True})
    args = _call_args()
    engine._log_blend_challenger_shadow(**args)

    assert captured["league_scope"] == "all"
    assert captured["fixture_id"] == args["pred"].fixture_id
    assert captured["oracle_probs"] == (
        args["pred"].prob_home_win, args["pred"].prob_draw, args["pred"].prob_away_win,
    )
    assert "home_offensive_rating" in captured["features"]
    assert "home_elo" in captured["features"]


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

    engine = _FakeEngine(config={"blend_challenger_shadow_logging_enabled": False})
    result = engine._log_blend_challenger_shadow(**_call_args())
    assert result is False


# ── Gardă structurală (Implementation Plan Pasul 13 §5): calea xgboost_v1
# rămâne neatinsă ────────────────────────────────────────────────────────

_CHALLENGER_SHADOW_PATH = pathlib.Path(
    __file__
).resolve().parent.parent / "learning_core" / "challenger_shadow.py"


def _public_function_signatures(path: pathlib.Path) -> dict[str, list[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sigs = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            args = [a.arg for a in node.args.args]
            sigs[node.name] = args
    return sigs


def test_challenger_shadow_public_signatures_unchanged():
    """learning_core/challenger_shadow.py (Challenger-ul xgboost_v1) nu e
    modificat de Pasul 13 — semnăturile funcțiilor publice rămân exact cele
    dinainte de introducerea Blend-ului (ADR-050 §4: comportament
    neschimbat)."""
    sigs = _public_function_signatures(_CHALLENGER_SHADOW_PATH)
    assert sigs["predict_with_challenger"] == ["features", "training_run_id"]
    assert sigs["log_shadow_for_active_challenger"] == [
        "algorithm_family", "league_scope", "features",
        "fixture_id", "home_xg", "away_xg",
        "control_prob_home", "control_prob_draw", "control_prob_away",
        "league", "home_team", "away_team", "kickoff_date",
    ]


def test_blend_challenger_shadow_module_does_not_import_challenger_shadow():
    """Cele două module de shadow (xgboost_v1 vs blend_v1) rămân complet
    separate (Implementation Plan Pasul 13 §1/§2.2/§3) — niciuna nu
    importă cealaltă."""
    import learning_core.blend_challenger_shadow as blend_shadow_mod

    tree = ast.parse(
        pathlib.Path(blend_shadow_mod.__file__).read_text(encoding="utf-8"),
        filename=blend_shadow_mod.__file__,
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[-1] == "challenger_shadow" or any(
                a.name == "challenger_shadow" for a in node.names
            ):
                pytest.fail("blend_challenger_shadow.py importă challenger_shadow.py — cele două căi trebuie să rămână separate")
        elif isinstance(node, ast.Import):
            if any(alias.name.split(".")[-1] == "challenger_shadow" for alias in node.names):
                pytest.fail("blend_challenger_shadow.py importă challenger_shadow.py")
