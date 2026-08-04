"""
Teste pentru frontiera oracle_engine.py <-> blend_engine.py (ADR-051, Vision
Shift / ADR-052) — orchestrarea `_get_blend_engine_prediction()` +
instanțierea `self.blend`. Comportamentul intern al `BlendEngine` (strategii,
combinare, config) e testat separat, izolat, în tests/test_blend_engine.py.

Tipar identic tests/test_blend_challenger_shadow_logging.py: verifică exclusiv
frontiera, nu duplică testele modulului pur.

Invarianți verificați aici:
  1. Flag oprit (implicit) => None, zero apel spre self.blend.
  2. self.blend indisponibil (BLEND_ENGINE_MODULE_AVAILABLE=False la import,
     sau None explicit) => None, niciodată excepție.
  3. Flag activ + self.blend disponibil => construiește exact un
     EngineOutput("oracle", ...) din pred deja servit, apelează
     self.blend.predict() o singură dată.
  4. Orice excepție (inclusiv din interiorul self.blend.predict()) e prinsă
     local, niciodată propagată — degradare grațioasă (Regula #8).
  5. Apelat exact o dată în evaluate_match() (gardă structurală, ca la
     _log_blend_challenger_shadow).
"""
import inspect

import oracle_engine
from blend_engine import BlendEngine, EngineOutput
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


class _FakeEngine:
    """Instanță minimală, fără Supabase/API real — identic ca tipar cu
    _FakeEngine din tests/test_blend_challenger_shadow_logging.py."""
    _get_blend_engine_prediction = oracle_engine.FootballOracleEngine._get_blend_engine_prediction

    def __init__(self, config: dict, blend=None):
        self.config = config
        self.blend = blend


# ── Gating: flag oprit (implicit) ───────────────────────────────────────────

def test_blend_engine_display_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["blend_engine_display_enabled"] is False


def test_blend_engine_config_has_safe_defaults():
    cfg = oracle_engine.DEFAULT_CONFIG["blend_engine_config"]
    assert cfg == {"strategy": "weighted_average", "weights": {}}


def test_returns_none_when_flag_disabled_even_with_blend_available():
    engine = _FakeEngine(config={"blend_engine_display_enabled": False}, blend=BlendEngine())
    result = engine._get_blend_engine_prediction(_make_pred())
    assert result is None


def test_blend_predict_not_called_when_flag_disabled():
    class _BoomBlend:
        def predict(self, outputs):
            raise AssertionError("BlendEngine.predict() nu trebuie apelat cand flag-ul e oprit")

    engine = _FakeEngine(config={"blend_engine_display_enabled": False}, blend=_BoomBlend())
    result = engine._get_blend_engine_prediction(_make_pred())
    assert result is None


# ── Gating: self.blend indisponibil ─────────────────────────────────────────

def test_returns_none_when_blend_is_none_even_with_flag_enabled():
    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=None)
    result = engine._get_blend_engine_prediction(_make_pred())
    assert result is None


# ── Comportament normal: flag activ + self.blend disponibil ────────────────

def test_returns_blend_dict_built_from_pred_when_enabled():
    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=BlendEngine())
    pred = _make_pred(prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25)

    result = engine._get_blend_engine_prediction(pred)

    # cu un singur EngineOutput (oracle), BlendEngine.predict() returneaza
    # exact aceleasi probabilitati (medie cu un singur termen)
    assert result == {"prob_home": 0.46, "prob_draw": 0.29, "prob_away": 0.25}


def test_engine_output_constructed_with_engine_name_oracle():
    captured = {}

    class _CapturingBlend:
        def predict(self, outputs):
            captured["outputs"] = outputs
            return {"prob_home": 0.1, "prob_draw": 0.1, "prob_away": 0.8}

    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=_CapturingBlend())
    pred = _make_pred(prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25)
    engine._get_blend_engine_prediction(pred)

    assert len(captured["outputs"]) == 1
    output = captured["outputs"][0]
    assert isinstance(output, EngineOutput)
    assert output.engine == "oracle"
    assert (output.prob_home, output.prob_draw, output.prob_away) == (0.46, 0.29, 0.25)


def test_blend_predict_called_exactly_once_when_enabled():
    calls = []

    class _CountingBlend:
        def predict(self, outputs):
            calls.append(outputs)
            return {"prob_home": 0.4, "prob_draw": 0.3, "prob_away": 0.3}

    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=_CountingBlend())
    engine._get_blend_engine_prediction(_make_pred())

    assert len(calls) == 1


# ── Degradare grațioasă: nicio excepție propagată ───────────────────────────

def test_exception_in_blend_predict_is_swallowed_returns_none():
    class _BoomBlend:
        def predict(self, outputs):
            raise RuntimeError("eroare simulata in BlendEngine.predict()")

    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=_BoomBlend())
    result = engine._get_blend_engine_prediction(_make_pred())
    assert result is None


def test_blend_returning_none_is_passed_through_without_error():
    """BlendEngine.predict() intoarce None pe outputs gol — un caz legitim,
    nu o eroare (vezi blend_engine.py, docstring predict())."""
    class _EmptyBlend:
        def predict(self, outputs):
            return None

    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=_EmptyBlend())
    result = engine._get_blend_engine_prediction(_make_pred())
    assert result is None


# ── Gardă structurală: apelat exact o dată în evaluate_match() ─────────────

def test_get_blend_engine_prediction_called_exactly_once_in_evaluate_match():
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def _get_blend_engine_prediction(")
    call_count = source.count("self._get_blend_engine_prediction(")
    assert def_count == 1
    assert call_count == 1


# ── self.blend instanțiat corect în __init__ (izolat de rețea) ─────────────

def test_blend_engine_module_available_flag_matches_import():
    """BLEND_ENGINE_MODULE_AVAILABLE trebuie sa fie True in acest mediu de
    test (blend_engine.py exista si e importabil) — garda ca self.blend nu
    e silentios None din cauza unui import stricat."""
    assert oracle_engine.BLEND_ENGINE_MODULE_AVAILABLE is True


def test_blend_config_from_dict_used_for_self_blend_construction_source():
    """Verificare structurala: __init__ construieste self.blend din
    BlendConfig.from_dict(self.config.get("blend_engine_config")) — nu un
    BlendConfig() gol, nu un dict brut."""
    source = inspect.getsource(oracle_engine.FootballOracleEngine.__init__)
    assert 'BlendConfig.from_dict(self.config.get("blend_engine_config"))' in source
    assert "BLEND_ENGINE_MODULE_AVAILABLE" in source
