"""
Teste pentru frontiera oracle_engine.py <-> learning_core.blend_v1_champion_loader
+ learning_core.blend_challenger_shadow (ADR-061) —
_get_blend_v1_champion_prediction().

Tipar identic tests/test_blend_engine_orchestration.py: verifică exclusiv
frontiera (gating, orchestrare, degradare grațioasă), nu duplică testele
modulelor pure (deja acoperite de test_blend_v1_champion_loader.py și
test_blend_challenger_shadow.py).

Invarianți verificați aici:
  1. Flag oprit (implicit) => None, zero apel spre loader/predict.
  2. Flag activ + niciun Campion promovat/utilizabil => {"available": False,
     "reason": "champion_indisponibil"}.
  3. Flag activ + Campion disponibil dar predict_with_blend_challenger
     eșuează (None) => {"available": False, "reason": "predictie_esuata"}.
  4. Flag activ + succes complet => {"available": True, "prob_home"/
     "prob_draw"/"prob_away": ...}.
  5. Orice excepție neprevăzută e prinsă local, niciodată propagată.
  6. Apelat exact o dată în evaluate_match() (gardă structurală).
  7. Câmpul nou (blend_v1_champion_prediction) e SEPARAT/DISTINCT de
     blend_engine_prediction — nu se confundă, nici structural, nici ca
     valoare implicită.
"""
import inspect

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
        league="Test League", kickoff_utc="2026-08-23T18:00:00Z",
        kickoff_date="2026-08-23", season=2026,
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


class _FakeChampion:
    def __init__(self, training_run_id="run-blend-champ-1"):
        self.training_run_id = training_run_id


class _FakeEngine:
    """Instanță minimală, fără Supabase/API real — identic ca tipar cu
    _FakeEngine din tests/test_blend_engine_orchestration.py."""
    _get_blend_v1_champion_prediction = oracle_engine.FootballOracleEngine._get_blend_v1_champion_prediction
    _build_ml_features = oracle_engine.FootballOracleEngine._build_ml_features

    def __init__(self, config: dict):
        self.config = config


_CALL_ARGS = dict(
    home_p=_make_team_profile("Home FC"), away_p=_make_team_profile("Away FC"),
    h2h=None, home_xg=1.4, away_xg=1.1, ph=0.46, pd_=0.29, pa=0.25,
    mc={"mc_prob_home": 0.45, "mc_prob_draw": 0.28, "mc_prob_away": 0.27}, weather_penalty=0.0,
)


# ── Gating: flag oprit (implicit) ───────────────────────────────────────────

def test_blend_v1_champion_display_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["blend_v1_champion_display_enabled"] is False


def test_returns_none_when_flag_disabled(monkeypatch):
    """[CORECTAT — verificat prin test de mutatie] O varianta initiala a
    acestui test folosea un mock care ridica AssertionError daca e apelat —
    dar acel AssertionError e prins de except-ul general din
    _get_blend_v1_champion_prediction() si transformat tot in None, deci
    testul trecea "din intamplare" chiar si dupa ce garda de flag era
    eliminata din cod (mutatie confirmata local: testul a ramas verde fara
    garda). Fix: numarator de apeluri explicit, verificat direct — singura
    garda care detecteaza real mutatia."""
    calls = []

    def _count_calls(*a, **kw):
        calls.append(1)
        return None

    monkeypatch.setattr(
        "learning_core.blend_v1_champion_loader.load_blend_v1_champion_or_none", _count_calls,
    )
    engine = _FakeEngine(config={"blend_v1_champion_display_enabled": False})
    result = engine._get_blend_v1_champion_prediction(_make_pred(), **_CALL_ARGS)
    assert result is None
    assert len(calls) == 0, "load_blend_v1_champion_or_none nu trebuie apelat cand flag-ul e oprit"


# ── Gating: niciun Campion utilizabil ───────────────────────────────────────

def test_returns_unavailable_dict_when_no_champion(monkeypatch):
    monkeypatch.setattr(
        "learning_core.blend_v1_champion_loader.load_blend_v1_champion_or_none",
        lambda league_scope: None,
    )

    def _fail_if_called(*a, **kw):
        raise AssertionError("predict_with_blend_challenger nu trebuie apelat fara Campion")

    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.predict_with_blend_challenger", _fail_if_called,
    )

    engine = _FakeEngine(config={"blend_v1_champion_display_enabled": True})
    result = engine._get_blend_v1_champion_prediction(_make_pred(), **_CALL_ARGS)
    assert result == {"available": False, "reason": "champion_indisponibil"}


# ── Predicție eșuată ─────────────────────────────────────────────────────

def test_returns_unavailable_dict_when_prediction_fails(monkeypatch):
    monkeypatch.setattr(
        "learning_core.blend_v1_champion_loader.load_blend_v1_champion_or_none",
        lambda league_scope: _FakeChampion(),
    )
    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.predict_with_blend_challenger",
        lambda oracle_probs, features, training_run_id: None,
    )

    engine = _FakeEngine(config={"blend_v1_champion_display_enabled": True})
    result = engine._get_blend_v1_champion_prediction(_make_pred(), **_CALL_ARGS)
    assert result == {"available": False, "reason": "predictie_esuata"}


# ── Comportament normal: flag activ + Campion disponibil ────────────────────

def test_returns_available_dict_on_success(monkeypatch):
    monkeypatch.setattr(
        "learning_core.blend_v1_champion_loader.load_blend_v1_champion_or_none",
        lambda league_scope: _FakeChampion(training_run_id="run-blend-champ-1"),
    )
    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.predict_with_blend_challenger",
        lambda oracle_probs, features, training_run_id: (0.51, 0.27, 0.22),
    )

    engine = _FakeEngine(config={"blend_v1_champion_display_enabled": True})
    result = engine._get_blend_v1_champion_prediction(_make_pred(), **_CALL_ARGS)
    assert result == {"available": True, "prob_home": 0.51, "prob_draw": 0.27, "prob_away": 0.22}


def test_predict_called_with_pred_probs_and_champion_training_run_id(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "learning_core.blend_v1_champion_loader.load_blend_v1_champion_or_none",
        lambda league_scope: _FakeChampion(training_run_id="run-xyz"),
    )

    def _capture(oracle_probs, features, training_run_id):
        captured["oracle_probs"] = oracle_probs
        captured["training_run_id"] = training_run_id
        captured["features"] = features
        return (0.4, 0.3, 0.3)

    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.predict_with_blend_challenger", _capture,
    )

    engine = _FakeEngine(config={"blend_v1_champion_display_enabled": True})
    pred = _make_pred(prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25)
    engine._get_blend_v1_champion_prediction(pred, **_CALL_ARGS)

    assert captured["oracle_probs"] == (0.46, 0.29, 0.25)
    assert captured["training_run_id"] == "run-xyz"
    assert isinstance(captured["features"], dict)
    assert "home_elo" in captured["features"]  # ml_predictor.FEATURE_COLUMNS


def test_predict_called_exactly_once_when_enabled(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "learning_core.blend_v1_champion_loader.load_blend_v1_champion_or_none",
        lambda league_scope: _FakeChampion(),
    )

    def _counting(oracle_probs, features, training_run_id):
        calls.append(1)
        return (0.4, 0.3, 0.3)

    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.predict_with_blend_challenger", _counting,
    )

    engine = _FakeEngine(config={"blend_v1_champion_display_enabled": True})
    engine._get_blend_v1_champion_prediction(_make_pred(), **_CALL_ARGS)

    assert len(calls) == 1


# ── Degradare grațioasă: nicio excepție propagată ───────────────────────────

def test_exception_in_loader_is_swallowed_returns_none(monkeypatch):
    def _boom(league_scope):
        raise RuntimeError("eroare simulata in loader")

    monkeypatch.setattr(
        "learning_core.blend_v1_champion_loader.load_blend_v1_champion_or_none", _boom,
    )
    engine = _FakeEngine(config={"blend_v1_champion_display_enabled": True})
    result = engine._get_blend_v1_champion_prediction(_make_pred(), **_CALL_ARGS)
    assert result is None


def test_exception_in_predict_is_swallowed_returns_none(monkeypatch):
    monkeypatch.setattr(
        "learning_core.blend_v1_champion_loader.load_blend_v1_champion_or_none",
        lambda league_scope: _FakeChampion(),
    )

    def _boom(oracle_probs, features, training_run_id):
        raise RuntimeError("eroare simulata in predict_with_blend_challenger")

    monkeypatch.setattr(
        "learning_core.blend_challenger_shadow.predict_with_blend_challenger", _boom,
    )

    engine = _FakeEngine(config={"blend_v1_champion_display_enabled": True})
    result = engine._get_blend_v1_champion_prediction(_make_pred(), **_CALL_ARGS)
    assert result is None


# ── Gardă structurală: apelat exact o dată în evaluate_match() ─────────────

def test_get_blend_v1_champion_prediction_called_exactly_once_in_evaluate_match():
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def _get_blend_v1_champion_prediction(")
    call_count = source.count("self._get_blend_v1_champion_prediction(")
    assert def_count == 1
    assert call_count == 1


# ── Distincție de blend_engine_prediction (motorul static) ─────────────────

def test_blend_v1_champion_prediction_field_is_separate_from_blend_engine_prediction():
    """Gardă structurală directă pe ADR-061: cele două câmpuri sunt
    dataclass fields DISTINCTE pe MatchPrediction, ambele None implicit,
    populate de metode diferite — niciodată același obiect/aceeași sursă."""
    pred = _make_pred()
    assert hasattr(pred, "blend_engine_prediction")
    assert hasattr(pred, "blend_v1_champion_prediction")
    assert pred.blend_engine_prediction is None
    assert pred.blend_v1_champion_prediction is None

    pred.blend_v1_champion_prediction = {"available": True, "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}
    # setarea unuia nu afecteaza celalalt
    assert pred.blend_engine_prediction is None
