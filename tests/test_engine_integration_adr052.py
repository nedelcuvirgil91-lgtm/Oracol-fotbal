"""
Teste pentru integrarea completă Oracle-ML-Blend (ADR-052, derivat din
ADR-051) — Blend consumă acum Oracle ȘI ML (dacă disponibil), fără nicio
schimbare a algoritmului Blend (`WeightedAverageStrategy`, `blend_engine.py`
neatins). Mirror structural `tests/test_blend_engine_orchestration.py`
(aceeași frontieră, testată acum pe a doua dimensiune: numărul de
EngineOutput construite).

Invarianți verificați aici:
  1. ML disponibil (pred.ml_engine_prediction["available"]=True) => Blend
     primește 2 EngineOutput (oracle + ml), rezultatul reflectă combinarea.
  2. ML indisponibil ({"available": False, ...}) => Blend primește tot 1
     EngineOutput (oracle) — comportament identic cu dinainte de ADR-052.
  3. ML absent (pred.ml_engine_prediction is None — flag oprit) => idem,
     1 EngineOutput — regresie explicită.
  4. Algoritmul Blend (WeightedAverageStrategy) NU e atins — verificat prin
     faptul că blend_engine.py nu apare în diff (verificare structurală,
     nu doar comportamentală).
  5. pred.ml_engine_prediction e calculat ÎNAINTE de
     pred.blend_engine_prediction în evaluate_match() (ordine, nu doar
     valoare) — gardă structurală prin inspect.getsource().
"""
import inspect

import oracle_engine
from blend_engine import BlendEngine, EngineOutput
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


class _FakeEngine:
    _get_blend_engine_prediction = oracle_engine.FootballOracleEngine._get_blend_engine_prediction

    def __init__(self, config: dict, blend=None):
        self.config = config
        self.blend = blend


# ── ML disponibil -> 2 EngineOutput, combinare reală ────────────────────────

def test_blend_includes_ml_engine_output_when_available():
    captured = {}

    class _CapturingBlend:
        def predict(self, outputs):
            captured["outputs"] = outputs
            return {"prob_home": 0.5, "prob_draw": 0.28, "prob_away": 0.22}

    pred = _make_pred(
        prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25,
        ml_engine_prediction={"available": True, "prob_home": 0.60, "prob_draw": 0.22, "prob_away": 0.18},
    )
    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=_CapturingBlend())
    engine._get_blend_engine_prediction(pred)

    outputs = captured["outputs"]
    assert len(outputs) == 2
    names = {o.engine for o in outputs}
    assert names == {"oracle", "ml"}
    ml_output = next(o for o in outputs if o.engine == "ml")
    assert (ml_output.prob_home, ml_output.prob_draw, ml_output.prob_away) == (0.60, 0.22, 0.18)


def test_blend_result_reflects_real_combination_with_ml():
    """Cu BlendEngine real (WeightedAverageStrategy, neschimbat) — media a
    doi termeni, nu mai byte-identic cu Oracle singur."""
    pred = _make_pred(
        prob_home_win=0.40, prob_draw=0.30, prob_away_win=0.30,
        ml_engine_prediction={"available": True, "prob_home": 0.60, "prob_draw": 0.20, "prob_away": 0.20},
    )
    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=BlendEngine())
    result = engine._get_blend_engine_prediction(pred)

    # medie ponderata (implicit, ponderi egale/neutre) a (0.40,0.30,0.30) si (0.60,0.20,0.20)
    assert result["prob_home"] == 0.5
    assert result["prob_draw"] == 0.25
    assert result["prob_away"] == 0.25
    # NU mai e byte-identic cu Oracle singur (dovada ca ML chiar a intrat in calcul)
    assert (result["prob_home"], result["prob_draw"], result["prob_away"]) != (0.40, 0.30, 0.30)


# ── ML indisponibil/absent -> tot 1 EngineOutput, regresie explicita ───────

def test_blend_excludes_ml_when_unavailable_with_reason():
    captured = {}

    class _CapturingBlend:
        def predict(self, outputs):
            captured["outputs"] = outputs
            return {"prob_home": 0.46, "prob_draw": 0.29, "prob_away": 0.25}

    pred = _make_pred(
        prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25,
        ml_engine_prediction={"available": False, "reason": "model_indisponibil"},
    )
    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=_CapturingBlend())
    engine._get_blend_engine_prediction(pred)

    assert len(captured["outputs"]) == 1
    assert captured["outputs"][0].engine == "oracle"


def test_blend_excludes_ml_when_none_flag_off_regression():
    """pred.ml_engine_prediction=None (valoarea implicita a campului, cazul
    ml_engine_display_enabled=False) -> comportament identic cu dinainte de
    ADR-052, un singur EngineOutput."""
    captured = {}

    class _CapturingBlend:
        def predict(self, outputs):
            captured["outputs"] = outputs
            return {"prob_home": 0.46, "prob_draw": 0.29, "prob_away": 0.25}

    pred = _make_pred(prob_home_win=0.46, prob_draw=0.29, prob_away_win=0.25)  # ml_engine_prediction=None implicit
    engine = _FakeEngine(config={"blend_engine_display_enabled": True}, blend=_CapturingBlend())
    result = engine._get_blend_engine_prediction(pred)

    assert len(captured["outputs"]) == 1
    assert result == {"prob_home": 0.46, "prob_draw": 0.29, "prob_away": 0.25}


def test_blend_flag_off_still_returns_none_regardless_of_ml():
    pred = _make_pred(ml_engine_prediction={"available": True, "prob_home": 0.6, "prob_draw": 0.2, "prob_away": 0.2})
    engine = _FakeEngine(config={"blend_engine_display_enabled": False}, blend=BlendEngine())
    assert engine._get_blend_engine_prediction(pred) is None


# ── Algoritmul Blend nu e atins ──────────────────────────────────────────────

def test_blend_engine_module_has_no_ml_specific_code():
    """blend_engine.py ramane exact cum era — generic pe lista, fara nicio
    referinta la "ml"/"oracle" hardcodata drept caz special in algoritm."""
    import blend_engine
    source = inspect.getsource(blend_engine)
    assert "WeightedAverageStrategy" in source
    # combine() ramane generic — nu itereaza dupa engine=="ml" sau altceva
    combine_source = inspect.getsource(blend_engine.WeightedAverageStrategy.combine)
    assert '"ml"' not in combine_source
    assert '"oracle"' not in combine_source


# ── Ordine: ml_engine_prediction calculat inaintea blend_engine_prediction ──

def test_ml_engine_prediction_computed_before_blend_in_evaluate_match_source():
    """De la eliminarea blend-ului legacy in-place (ADR-051/052), ML e
    calculat DEVREME în evaluate_match() — variabila locală
    `ml_engine_prediction` (folosită și pentru raw_predictions, ADR-031) e
    populată prin self._get_ml_engine_prediction(), apoi transmisă direct la
    construcția `pred` (kwarg `ml_engine_prediction=ml_engine_prediction`).
    Blend rămâne calculat DUPĂ, pe `pred` deja construit — gardă structurală
    pe ordinea reală, nu doar pe valoare."""
    source = inspect.getsource(oracle_engine.FootballOracleEngine.evaluate_match)
    ml_pos = source.index("ml_engine_prediction = self._get_ml_engine_prediction(")
    construct_pos = source.index("ml_engine_prediction=ml_engine_prediction,")
    blend_pos = source.index("pred.blend_engine_prediction = self._get_blend_engine_prediction(pred)")
    assert ml_pos < construct_pos < blend_pos, (
        "ml_engine_prediction trebuie calculat si asignat pe pred INAINTE de "
        "pred.blend_engine_prediction, altfel Blend nu poate include ML"
    )
