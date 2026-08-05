"""
Teste pentru frontiera oracle_engine.py <-> ml_predictor.py (ADR-051, Phase 1)
— orchestrarea `_get_ml_engine_prediction()`. Mirror structural exact al
tests/test_blend_engine_orchestration.py (aceeași frontieră, al doilea motor
independent). Comportamentul intern al `MLPredictorEngine.predict()` e
testat separat, izolat, în tests/test_ml_predictor.py (dacă există).

Invarianți verificați aici (per PHASE1_IMPLEMENTATION_BLUEPRINT.md §7):
  1. Flag oprit (implicit) => None, zero apel spre self.ml.predict().
  2. self.ml is None (flag activ) => {"available": False, "reason": "model_indisponibil"}.
  3. self.ml.is_trained == False (flag activ) => idem #2.
  4. self.ml.predict() întoarce None (predicție eșuată pt acest meci) =>
     {"available": False, "reason": "predictie_esuata"}.
  5. self.ml.predict() întoarce MLPrediction valid => dict cu probabilitățile
     transportate exact.
  6. Excepție internă neprevăzută => None, nu propagă.
  7. Nicio mutație a lui `pred` — wrapper-ul e strict read-only.
  8. Izolare completă față de flag-ul Blend (independență reciprocă).
  9. Gardă structurală: zero referință la champion_loader/load_champion_or_none
     în corpul metodei — self.ml e deja rezolvat o singură dată, la
     construcția procesului, niciodată re-rezolvat aici.
"""
import inspect

import oracle_engine
from ml_predictor import MLPrediction
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


def _make_mc() -> dict:
    return {"mc_prob_home": 0.42, "mc_prob_draw": 0.28, "mc_prob_away": 0.30}


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


class _FakeMLPredictor:
    """Dublură minimală pentru self.ml — nu instanțiază MLPredictorEngine
    real (ar cere Supabase/XGBoost antrenat)."""
    def __init__(self, is_trained: bool, predict_result=None, predict_raises: Exception | None = None):
        self.is_trained = is_trained
        self._predict_result = predict_result
        self._predict_raises = predict_raises
        self.predict_calls = 0

    def predict(self, features: dict):
        self.predict_calls += 1
        if self._predict_raises is not None:
            raise self._predict_raises
        return self._predict_result


class _FakeEngine:
    """Instanță minimală, fără Supabase/API real — identic ca tipar cu
    _FakeEngine din tests/test_blend_engine_orchestration.py."""
    _get_ml_engine_prediction = oracle_engine.FootballOracleEngine._get_ml_engine_prediction
    _build_ml_features = oracle_engine.FootballOracleEngine._build_ml_features

    def __init__(self, config: dict, ml=None):
        self.config = config
        self.ml = ml


def _call(engine, pred=None):
    pred = pred or _make_pred()
    home_p = _make_team_profile("Home FC")
    away_p = _make_team_profile("Away FC")
    return engine._get_ml_engine_prediction(
        pred, home_p, away_p, None, pred.home_xg, pred.away_xg,
        pred.prob_home_win, pred.prob_draw, pred.prob_away_win, _make_mc(), 0.0,
    )


# ── Gating: flag oprit (implicit) ───────────────────────────────────────────

def test_ml_engine_display_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["ml_engine_display_enabled"] is False


def test_returns_none_when_flag_disabled_even_with_ml_available():
    ml = _FakeMLPredictor(is_trained=True, predict_result=MLPrediction(
        prob_home=0.5, prob_draw=0.3, prob_away=0.2, confidence=0.5, model_version=1, samples_used=100,
    ))
    engine = _FakeEngine(config={"ml_engine_display_enabled": False}, ml=ml)
    result = _call(engine)
    assert result is None


def test_ml_predict_not_called_when_flag_disabled():
    ml = _FakeMLPredictor(is_trained=True)
    engine = _FakeEngine(config={"ml_engine_display_enabled": False}, ml=ml)
    _call(engine)
    assert ml.predict_calls == 0


# ── Gating: self.ml indisponibil/netrenuit (flag activ) ────────────────────

def test_returns_reason_dict_when_ml_is_none_with_flag_enabled():
    engine = _FakeEngine(config={"ml_engine_display_enabled": True}, ml=None)
    result = _call(engine)
    assert result == {"available": False, "reason": "model_indisponibil"}


def test_returns_reason_dict_when_ml_not_trained_with_flag_enabled():
    ml = _FakeMLPredictor(is_trained=False)
    engine = _FakeEngine(config={"ml_engine_display_enabled": True}, ml=ml)
    result = _call(engine)
    assert result == {"available": False, "reason": "model_indisponibil"}


# ── Predicție eșuată pt acest meci specific ─────────────────────────────────

def test_returns_reason_dict_when_ml_predict_returns_none():
    ml = _FakeMLPredictor(is_trained=True, predict_result=None)
    engine = _FakeEngine(config={"ml_engine_display_enabled": True}, ml=ml)
    result = _call(engine)
    assert result == {"available": False, "reason": "predictie_esuata"}
    assert ml.predict_calls == 1


# ── Comportament normal: flag activ + self.ml antrenat ─────────────────────

def test_returns_available_dict_with_probabilities_when_enabled():
    ml = _FakeMLPredictor(is_trained=True, predict_result=MLPrediction(
        prob_home=0.55, prob_draw=0.25, prob_away=0.20, confidence=0.55, model_version=3, samples_used=5000,
    ))
    engine = _FakeEngine(config={"ml_engine_display_enabled": True}, ml=ml)
    result = _call(engine)
    assert result == {"available": True, "prob_home": 0.55, "prob_draw": 0.25, "prob_away": 0.20}


def test_ml_predict_called_exactly_once_when_enabled():
    ml = _FakeMLPredictor(is_trained=True, predict_result=MLPrediction(
        prob_home=0.4, prob_draw=0.3, prob_away=0.3, confidence=0.4, model_version=1, samples_used=100,
    ))
    engine = _FakeEngine(config={"ml_engine_display_enabled": True}, ml=ml)
    _call(engine)
    assert ml.predict_calls == 1


# ── Degradare grațioasă: nicio excepție propagată ───────────────────────────

def test_exception_in_ml_predict_is_swallowed_returns_none():
    ml = _FakeMLPredictor(is_trained=True, predict_raises=RuntimeError("eroare simulata"))
    engine = _FakeEngine(config={"ml_engine_display_enabled": True}, ml=ml)
    result = _call(engine)
    assert result is None


# ── Read-only: pred nu e mutat de wrapper ───────────────────────────────────

def test_pred_is_not_mutated_by_ml_engine_wrapper():
    ml = _FakeMLPredictor(is_trained=True, predict_result=MLPrediction(
        prob_home=0.6, prob_draw=0.2, prob_away=0.2, confidence=0.6, model_version=1, samples_used=100,
    ))
    engine = _FakeEngine(config={"ml_engine_display_enabled": True}, ml=ml)
    pred = _make_pred(prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25)
    before = (pred.prob_home_win, pred.prob_draw, pred.prob_away_win, pred.blend_engine_prediction)

    _call(engine, pred=pred)

    after = (pred.prob_home_win, pred.prob_draw, pred.prob_away_win, pred.blend_engine_prediction)
    assert before == after


# ── Izolare față de flag-ul Blend ───────────────────────────────────────────

def test_ml_engine_flag_independent_of_blend_flag():
    ml = _FakeMLPredictor(is_trained=True, predict_result=MLPrediction(
        prob_home=0.5, prob_draw=0.3, prob_away=0.2, confidence=0.5, model_version=1, samples_used=100,
    ))
    # blend_engine_display_enabled explicit oprit — ml_engine_display_enabled
    # trebuie sa functioneze independent de valoarea lui.
    engine = _FakeEngine(
        config={"ml_engine_display_enabled": True, "blend_engine_display_enabled": False}, ml=ml,
    )
    result = _call(engine)
    assert result == {"available": True, "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}


# ── Gardă structurală: zero re-rezolvare Champion, apel unic în evaluate_match ──

def test_get_ml_engine_prediction_called_exactly_once_in_evaluate_match():
    source = inspect.getsource(oracle_engine)
    def_count = source.count("def _get_ml_engine_prediction(")
    call_count = source.count("self._get_ml_engine_prediction(")
    assert def_count == 1
    assert call_count == 1


def test_get_ml_engine_prediction_never_reresolves_champion():
    """Invariant RUNTIME_CONTRACT.md (Pasul 7B) — un singur apel
    champion_loader.load_champion_or_none() per proces, exclusiv din
    _resolve_champion(). Wrapper-ul ML nu trebuie sa importe/apeleze
    champion_loader in niciun fel — verificat pe COD EXECUTABIL (docstring-ul
    documenteaza deliberat invariantul in proza, deci mentioneaza numele)."""
    method = oracle_engine.FootballOracleEngine._get_ml_engine_prediction
    body_only = inspect.getsource(method).replace(inspect.getdoc(method) or "", "")
    assert "champion_loader." not in body_only
    assert "load_champion_or_none(" not in body_only


def test_ml_engine_prediction_independent_of_ml_blending_enabled():
    """_get_ml_engine_prediction nu citeste ml_blending_enabled (legacy) —
    cele doua cai raman complet independente. Verificat pe COD EXECUTABIL."""
    method = oracle_engine.FootballOracleEngine._get_ml_engine_prediction
    body_only = inspect.getsource(method).replace(inspect.getdoc(method) or "", "")
    assert 'get("ml_blending_enabled"' not in body_only
