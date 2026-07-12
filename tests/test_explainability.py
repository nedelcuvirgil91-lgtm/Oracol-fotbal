"""Teste pentru explainability.py.

Invariant central verificat: ultima treaptă a cascadei produse de
explain_prediction() trebuie să coincidă EXACT (în limita rotunjirii la 4
zecimale) cu probabilitatea reală calculată independent, folosind aceleași
funcții pure din feature_engine.py — exact secvența din
oracle_engine.evaluate_match(), reconstruită manual aici ca sursă de adevăr
separată. Fără rețea, fără Supabase — toate datele sunt construite direct.
"""
from __future__ import annotations

from feature_engine import (
    calibrate_xg,
    compute_team_offdef_rating,
    elo_to_defensive_multiplier,
    elo_to_offensive_multiplier,
    poisson_model,
    resolve_league_weights,
)
from ml_predictor import MLPrediction, blend_predictions
from oracle_engine import DEFAULT_CONFIG, DEFAULT_WEIGHTS, H2HRecord, MatchPrediction, TeamProfile

from explainability import explain_prediction

LEAGUE = "Premier League"


def _profile(name, elo, form_score, gf=1.5, ga=1.0, sot=5.0, poss=52.0):
    return TeamProfile(
        team_id=f"id_{name}", team_name=name, matches_analysed=10,
        avg_goals_for=gf, avg_goals_against=ga, avg_shots_ot=sot, avg_possession=poss,
        offensive_rating=0.0, defensive_rating=0.0,
        form_results=["W", "W", "D", "W", "L"], form_score=form_score,
        standings_form="", elo_rating=elo, data_source="test", data_quality="live",
        data_quality_note="",
    )


def _independent_ground_truth(home_p, away_p, h2h, weights, config, league=LEAGUE,
                               weather_penalty=0.0, home_xg_override=None, away_xg_override=None,
                               ml_active=False, ml_probs=(0.0, 0.0, 0.0), ml_samples=0):
    """Recalculează prob_home_win DIRECT din feature_engine.py, independent de
    explainability.py — sursă de adevăr separată pentru comparație."""
    lw = resolve_league_weights(weights, league)
    baseline = weights["league_baselines"].get(league, weights["league_baselines"]["default"])
    elo_blend, elo_ref, elo_scale = config["elo_blend_weight"], config["elo_reference"], config["elo_sigmoid_scale"]

    def ratings(p):
        eo = elo_to_offensive_multiplier(p.elo_rating, elo_ref, elo_scale)
        ed = elo_to_defensive_multiplier(p.elo_rating, elo_ref, elo_scale)
        return compute_team_offdef_rating(
            avg_goals_for=p.avg_goals_for, avg_goals_against=p.avg_goals_against,
            avg_shots_on_target=p.avg_shots_ot, avg_possession=p.avg_possession,
            goals_weight=lw["goals_weight"], shots_ot_weight=lw["shots_ot_weight"],
            possession_weight=lw["possession_weight"], offensive_cap=weights["offensive_cap"],
            defensive_cap=weights["defensive_cap"], elo_offensive_multiplier=eo,
            elo_defensive_multiplier=ed, elo_blend_weight=elo_blend,
        )

    home_off, home_def = ratings(home_p)
    away_off, away_def = ratings(away_p)

    home_xg, away_xg = calibrate_xg(
        home_offensive_rating=home_off, home_defensive_rating=home_def,
        away_offensive_rating=away_off, away_defensive_rating=away_def,
        home_form_score=home_p.form_score, away_form_score=away_p.form_score,
        baseline=baseline, form_weight=lw["form_weight"], dna_weight=lw["dna_weight"],
        home_advantage=lw["home_advantage"], away_penalty=lw["away_penalty"],
        defensive_cap=weights["defensive_cap"],
        h2h_modifier=h2h.h2h_modifier if h2h else 0.0, h2h_meetings=h2h.meetings if h2h else 0,
        weather_penalty=weather_penalty,
    )
    home_xg_pre, away_xg_pre = home_xg, away_xg
    if home_xg_override is not None:
        home_xg, away_xg = home_xg_override, away_xg_override

    ph, pd, pa, _ = poisson_model(home_xg, away_xg, config["max_goals_poisson"])

    if ml_active:
        ml_pred = MLPrediction(prob_home=ml_probs[0], prob_draw=ml_probs[1], prob_away=ml_probs[2],
                                confidence=max(ml_probs), model_version=1, samples_used=ml_samples)
        ph, pd, pa, _ = blend_predictions((ph, pd, pa), ml_pred, config["ml_blend_weight"])

    return round(ph, 4), home_xg, away_xg, home_xg_pre, away_xg_pre


def _make_pred(home_p, away_p, h2h, weights, config, weather_penalty=0.0,
                inject_injury=False, ml_active=False, ml_probs=(0.0, 0.0, 0.0), ml_samples=0):
    _, home_xg, away_xg, _, _ = _independent_ground_truth(
        home_p, away_p, h2h, weights, config, weather_penalty=weather_penalty,
    )
    if inject_injury:
        # simuleaza o reducere reala de xG (echivalent cu apply_injury_penalty)
        home_xg_post = round(home_xg * 0.85, 4)
        away_xg_post = away_xg
    else:
        home_xg_post, away_xg_post = home_xg, away_xg

    ph, pd, pa, _ = poisson_model(home_xg_post, away_xg_post, config["max_goals_poisson"])
    if ml_active:
        ml_pred = MLPrediction(prob_home=ml_probs[0], prob_draw=ml_probs[1], prob_away=ml_probs[2],
                                confidence=max(ml_probs), model_version=1, samples_used=ml_samples)
        ph, pd, pa, _ = blend_predictions((ph, pd, pa), ml_pred, config["ml_blend_weight"])

    return MatchPrediction(
        fixture_id="fx1", home_team=home_p.team_name, away_team=away_p.team_name, league=LEAGUE,
        kickoff_utc="", kickoff_date="", season=2026,
        home_xg=home_xg_post, away_xg=away_xg_post,
        prob_home_win=round(ph, 4), prob_draw=round(pd, 4), prob_away_win=round(pa, 4),
        top_scores=[], bk_home_odds=0.0, bk_draw_odds=0.0, bk_away_odds=0.0, bookmaker_name="",
        impl_home_pct=0.0, impl_draw_pct=0.0, impl_away_pct=0.0,
        edge_home_pct=0.0, edge_draw_pct=0.0, edge_away_pct=0.0, value_bets=[],
        weather_note="", weather_penalty=weather_penalty, kelly_stakes={},
        home_profile=home_p, away_profile=away_p, h2h=h2h,
        data_quality_home=home_p.data_quality, data_quality_away=away_p.data_quality,
        home_injury_report=None, away_injury_report=None, injury_note="",
        home_xg_pre_injury=home_xg, away_xg_pre_injury=away_xg,
        ml_active=ml_active,
        ml_prob_home=ml_probs[0] if ml_active else 0.0,
        ml_prob_draw=ml_probs[1] if ml_active else 0.0,
        ml_prob_away=ml_probs[2] if ml_active else 0.0,
        ml_confidence=max(ml_probs) if ml_active else 0.0,
        ml_samples_used=ml_samples,
    )


def test_explanation_final_stage_matches_real_probability_no_ml_no_weather():
    home_p = _profile("Home FC", elo=1650, form_score=0.75)
    away_p = _profile("Away FC", elo=1500, form_score=0.45)
    h2h = H2HRecord(home_team="Home FC", away_team="Away FC", meetings=4, home_wins=3, draws=1,
                     away_wins=0, home_goals_avg=2.0, away_goals_avg=0.75, last_5=[],
                     h2h_modifier=0.09, summary="")
    pred = _make_pred(home_p, away_p, h2h, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    explanation = explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    assert explanation is not None
    assert explanation.final_prob_home == pred.prob_home_win
    assert explanation.stages[-1].prob_home_after == pred.prob_home_win
    # fara ML activ -> ultima treaptă e "Accidentări", nu "Model ML"
    assert explanation.stages[-1].factor == "Accidentări"


def test_explanation_includes_ml_stage_when_active_and_matches_final():
    home_p = _profile("Home FC", elo=1550, form_score=0.55)
    away_p = _profile("Away FC", elo=1580, form_score=0.60)
    h2h = H2HRecord.empty("Home FC", "Away FC")
    pred = _make_pred(home_p, away_p, h2h, DEFAULT_WEIGHTS, DEFAULT_CONFIG,
                       ml_active=True, ml_probs=(0.5, 0.25, 0.25), ml_samples=120)

    explanation = explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    assert explanation is not None
    assert explanation.stages[-1].factor == "Model ML"
    assert explanation.final_prob_home == pred.prob_home_win


def test_explanation_includes_injury_delta_when_xg_reduced():
    home_p = _profile("Home FC", elo=1600, form_score=0.70)
    away_p = _profile("Away FC", elo=1500, form_score=0.50)
    h2h = H2HRecord.empty("Home FC", "Away FC")
    pred = _make_pred(home_p, away_p, h2h, DEFAULT_WEIGHTS, DEFAULT_CONFIG, inject_injury=True)

    explanation = explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    assert explanation is not None
    injury_stage = next(s for s in explanation.stages if s.factor == "Accidentări")
    assert injury_stage.delta_pct < 0  # xG redus -> probabilitate Home mai mică
    assert explanation.final_prob_home == pred.prob_home_win


def test_explanation_weather_stage_appears_only_when_penalty_nonzero():
    home_p = _profile("Home FC", elo=1600, form_score=0.60)
    away_p = _profile("Away FC", elo=1550, form_score=0.55)
    h2h = H2HRecord.empty("Home FC", "Away FC")

    pred_no_weather = _make_pred(home_p, away_p, h2h, DEFAULT_WEIGHTS, DEFAULT_CONFIG, weather_penalty=0.0)
    explanation_no_weather = explain_prediction(pred_no_weather, DEFAULT_WEIGHTS, DEFAULT_CONFIG)
    assert all(s.factor != "Vreme" for s in explanation_no_weather.stages)

    pred_weather = _make_pred(home_p, away_p, h2h, DEFAULT_WEIGHTS, DEFAULT_CONFIG, weather_penalty=0.15)
    explanation_weather = explain_prediction(pred_weather, DEFAULT_WEIGHTS, DEFAULT_CONFIG)
    assert any(s.factor == "Vreme" for s in explanation_weather.stages)
    assert explanation_weather.final_prob_home == pred_weather.prob_home_win


def test_explanation_returns_none_without_team_profiles():
    pred = _make_pred(_profile("A", 1500, 0.5), _profile("B", 1500, 0.5),
                       H2HRecord.empty("A", "B"), DEFAULT_WEIGHTS, DEFAULT_CONFIG)
    pred.home_profile = None
    assert explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG) is None


def test_explanation_elo_stage_shows_real_ratings():
    home_p = _profile("Home FC", elo=1780, form_score=0.6)
    away_p = _profile("Away FC", elo=1520, form_score=0.5)
    pred = _make_pred(home_p, away_p, H2HRecord.empty("Home FC", "Away FC"), DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    explanation = explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    elo_stage = next(s for s in explanation.stages if s.factor == "ELO")
    assert elo_stage.detail["Home FC"] == "1780"
    assert elo_stage.detail["Away FC"] == "1520"


def test_explanation_form_stage_shows_real_wdl_record():
    home_p = _profile("Home FC", elo=1600, form_score=0.6)
    home_p.form_results = ["W", "W", "D", "W", "W"]
    away_p = _profile("Away FC", elo=1600, form_score=0.4)
    away_p.form_results = ["L", "D", "L", "W", "L"]
    pred = _make_pred(home_p, away_p, H2HRecord.empty("Home FC", "Away FC"), DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    explanation = explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    form_stage = next(s for s in explanation.stages if s.factor == "Formă")
    assert form_stage.detail["Home FC"] == "4W-1D"
    assert form_stage.detail["Away FC"] == "1W-1D-3L"


def test_explanation_h2h_stage_shows_meetings_and_record():
    home_p = _profile("Home FC", elo=1600, form_score=0.5)
    away_p = _profile("Away FC", elo=1550, form_score=0.5)
    h2h = H2HRecord(home_team="Home FC", away_team="Away FC", meetings=5, home_wins=3, draws=1,
                     away_wins=1, home_goals_avg=2.0, away_goals_avg=1.0, last_5=[],
                     h2h_modifier=0.05, summary="")
    pred = _make_pred(home_p, away_p, h2h, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    explanation = explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    h2h_stage = next(s for s in explanation.stages if s.factor == "H2H")
    assert h2h_stage.detail["întâlniri directe"] == "5"
    assert h2h_stage.detail["bilanț (gazdă V-E-Î)"] == "3-1-1"


def test_explanation_ml_stage_shows_samples_and_confidence():
    home_p = _profile("Home FC", elo=1600, form_score=0.5)
    away_p = _profile("Away FC", elo=1580, form_score=0.5)
    pred = _make_pred(home_p, away_p, H2HRecord.empty("Home FC", "Away FC"), DEFAULT_WEIGHTS, DEFAULT_CONFIG,
                       ml_active=True, ml_probs=(0.5, 0.25, 0.25), ml_samples=180)
    pred.ml_confidence = 0.71

    explanation = explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    ml_stage = next(s for s in explanation.stages if s.factor == "Model ML")
    assert ml_stage.detail["samples antrenare"] == "180"
    assert ml_stage.detail["încredere model"] == "71%"


def test_explanation_injury_stage_shows_real_absence_count():
    from injury_manager import PlayerAbsence, TeamInjuryReport

    home_p = _profile("Home FC", elo=1600, form_score=0.6)
    away_p = _profile("Away FC", elo=1550, form_score=0.5)
    pred = _make_pred(home_p, away_p, H2HRecord.empty("Home FC", "Away FC"), DEFAULT_WEIGHTS, DEFAULT_CONFIG,
                       inject_injury=True)

    absence = PlayerAbsence(player_id=1, name="Titular X", position="FWD", minutes_played=900,
                             market_value=30_000_000, absence_type="injury", certainty=1.0,
                             xg_impact=0.1, impact_label="key", note="")
    pred.home_injury_report = TeamInjuryReport(team_name="Home FC", team_id="h1",
                                                absences=[absence, absence], has_key_absences=True)
    pred.away_injury_report = TeamInjuryReport(team_name="Away FC", team_id="a1", absences=[])

    explanation = explain_prediction(pred, DEFAULT_WEIGHTS, DEFAULT_CONFIG)

    injury_stage = next(s for s in explanation.stages if s.factor == "Accidentări")
    assert injury_stage.detail["Home FC"] == "2 titular(i) indisponibil(i)"
    assert injury_stage.detail["Away FC"] == "fără absențe raportate"
