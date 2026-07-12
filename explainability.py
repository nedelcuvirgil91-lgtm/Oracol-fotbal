"""
================================================================================
FOOTBALL ORACLE — Explainability (v0.1)
================================================================================
Module: explainability.py

Descompune o predicție deja calculată (MatchPrediction) în contribuții per
factor — ELO, formă, avantaj teren, H2H, vreme, accidentări, blend ML —
prin ablație cumulativă REALĂ, nu estimare: recalculează xG → Poisson la
fiecare treaptă, folosind exact aceleași funcții pure din feature_engine.py
pe care oracle_engine.py le folosește deja pentru predicția live.

Nu modifică oracle_engine.py. Nu apelează nicio metodă privată — doar funcții
pure din feature_engine.py + câmpuri deja publice pe MatchPrediction/
TeamProfile/H2HRecord.

Ordinea treptelor urmează ordinea REALĂ de calcul din
oracle_engine._calibrate_xg()/evaluate_match() — nu ordinea „didactică" în
care ar putea fi cerută afișarea. Accidentările se aplică, în codul real,
DUPĂ ce H2H și vremea sunt deja incluse în xG (calibrate_xg le include pe
ambele înainte de penalizarea de accidentări) — deci apar în cascadă DUPĂ
H2H/Vreme, nu înainte. Reordonarea ar însemna calcularea unei valori
intermediare care nu corespunde niciunui pas real din pipeline — exact ce
proiectul evită („verificat, nu presupus").

Invariant verificat explicit (vezi tests/test_explainability.py): ultima
treaptă a cascadei trebuie să cadă exact pe pred.prob_home_win — altfel
defalcarea nu ar reprezenta calculul real.

Monte Carlo NU intră în defalcare — verificat direct în oracle_engine.py:
mc_prob_home/draw/away se calculează separat și nu alimentează niciodată
prob_home_win/prob_draw/prob_away_win (doar afișate ca o comparație).
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field

from feature_engine import (
    calibrate_xg,
    compute_team_offdef_rating,
    elo_to_defensive_multiplier,
    elo_to_offensive_multiplier,
    poisson_model,
    resolve_league_weights,
)


@dataclass
class ExplanationStage:
    """O treaptă din cascadă — probabilitatea Home DUPĂ ce acest factor a
    fost adăugat, plus contribuția lui marginală (delta față de treapta
    anterioară), în puncte procentuale."""
    factor:          str
    prob_home_after: float
    delta_pct:       float


@dataclass
class MatchExplanation:
    stages:           list[ExplanationStage] = field(default_factory=list)
    final_prob_home:  float = 0.0  # trebuie sa coincida (in limita rotunjirii) cu pred.prob_home_win


def _stage_prob_home(home_off, home_def, away_off, away_def, home_form, away_form,
                      baseline, form_w, dna_w, home_adv, away_pen, d_cap,
                      h2h_mod, h2h_meet, weather_pen, max_goals) -> float:
    home_xg, away_xg = calibrate_xg(
        home_offensive_rating=home_off, home_defensive_rating=home_def,
        away_offensive_rating=away_off, away_defensive_rating=away_def,
        home_form_score=home_form, away_form_score=away_form,
        baseline=baseline, form_weight=form_w, dna_weight=dna_w,
        home_advantage=home_adv, away_penalty=away_pen, defensive_cap=d_cap,
        h2h_modifier=h2h_mod, h2h_meetings=h2h_meet, weather_penalty=weather_pen,
    )
    ph, _, _, _ = poisson_model(home_xg, away_xg, max_goals)
    return ph


def explain_prediction(pred, weights: dict, config: dict) -> MatchExplanation | None:
    """Construiește cascada de explicații pentru o predicție deja calculată.
    Întoarce None dacă lipsesc profilurile echipelor (predicție incompletă)."""
    home_p, away_p, h2h = pred.home_profile, pred.away_profile, pred.h2h
    if home_p is None or away_p is None:
        return None

    lw        = resolve_league_weights(weights, pred.league)
    baselines = weights.get("league_baselines", {})
    baseline  = float(baselines.get(pred.league, baselines.get("default", 1.25)))
    o_cap     = float(weights.get("offensive_cap", 3.5))
    d_cap     = float(weights.get("defensive_cap", 2.5))
    max_goals = int(config.get("max_goals_poisson", 8))

    elo_blend = float(config.get("elo_blend_weight", 0.35))
    elo_ref   = float(config.get("elo_reference",    1500.0))
    elo_scale = float(config.get("elo_sigmoid_scale", 400.0))

    def _ratings(profile, elo_on: bool):
        elo_off = elo_def = None
        if elo_on and profile.elo_rating:
            elo_off = elo_to_offensive_multiplier(profile.elo_rating, elo_ref, elo_scale)
            elo_def = elo_to_defensive_multiplier(profile.elo_rating, elo_ref, elo_scale)
        return compute_team_offdef_rating(
            avg_goals_for=profile.avg_goals_for, avg_goals_against=profile.avg_goals_against,
            avg_shots_on_target=profile.avg_shots_ot, avg_possession=profile.avg_possession,
            goals_weight=lw["goals_weight"], shots_ot_weight=lw["shots_ot_weight"],
            possession_weight=lw["possession_weight"], offensive_cap=o_cap, defensive_cap=d_cap,
            elo_offensive_multiplier=elo_off, elo_defensive_multiplier=elo_def,
            elo_blend_weight=elo_blend,
        )

    home_off_stats, home_def_stats = _ratings(home_p, elo_on=False)
    away_off_stats, away_def_stats = _ratings(away_p, elo_on=False)
    home_off_elo,   home_def_elo   = _ratings(home_p, elo_on=True)
    away_off_elo,   away_def_elo   = _ratings(away_p, elo_on=True)

    h2h_mod     = h2h.h2h_modifier if h2h else 0.0
    h2h_meet    = h2h.meetings if h2h else 0
    weather_pen = float(pred.weather_penalty or 0.0)

    stages: list[ExplanationStage] = []
    prev_ph: float | None = None

    def _add(name: str, ph: float) -> None:
        nonlocal prev_ph
        delta = ph if prev_ph is None else ph - prev_ph
        stages.append(ExplanationStage(factor=name, prob_home_after=round(ph, 4),
                                        delta_pct=round(delta * 100, 2)))
        prev_ph = ph

    common = dict(baseline=baseline, form_w=lw["form_weight"], dna_w=lw["dna_weight"],
                  d_cap=d_cap, max_goals=max_goals)

    # Treapta 0 — bază neutră: doar statistici brute, fără ELO/formă/avantaj/H2H/vreme.
    _add("Bază (statistici brute)", _stage_prob_home(
        home_off_stats, home_def_stats, away_off_stats, away_def_stats,
        0.5, 0.5, home_adv=1.0, away_pen=1.0, h2h_mod=0.0, h2h_meet=0, weather_pen=0.0, **common))

    # + ELO
    _add("ELO", _stage_prob_home(
        home_off_elo, home_def_elo, away_off_elo, away_def_elo,
        0.5, 0.5, home_adv=1.0, away_pen=1.0, h2h_mod=0.0, h2h_meet=0, weather_pen=0.0, **common))

    # + Formă reală
    _add("Formă", _stage_prob_home(
        home_off_elo, home_def_elo, away_off_elo, away_def_elo,
        home_p.form_score, away_p.form_score,
        home_adv=1.0, away_pen=1.0, h2h_mod=0.0, h2h_meet=0, weather_pen=0.0, **common))

    # + Avantaj teren real
    _add("Avantaj teren", _stage_prob_home(
        home_off_elo, home_def_elo, away_off_elo, away_def_elo,
        home_p.form_score, away_p.form_score,
        home_adv=lw["home_advantage"], away_pen=lw["away_penalty"],
        h2h_mod=0.0, h2h_meet=0, weather_pen=0.0, **common))

    # + H2H real
    _add("H2H", _stage_prob_home(
        home_off_elo, home_def_elo, away_off_elo, away_def_elo,
        home_p.form_score, away_p.form_score,
        home_adv=lw["home_advantage"], away_pen=lw["away_penalty"],
        h2h_mod=h2h_mod, h2h_meet=h2h_meet, weather_pen=0.0, **common))

    # + Vreme (doar dacă penalizarea e nenulă — altfel treapta n-ar adăuga informație)
    if weather_pen > 0:
        _add("Vreme", _stage_prob_home(
            home_off_elo, home_def_elo, away_off_elo, away_def_elo,
            home_p.form_score, away_p.form_score,
            home_adv=lw["home_advantage"], away_pen=lw["away_penalty"],
            h2h_mod=h2h_mod, h2h_meet=h2h_meet, weather_pen=weather_pen, **common))

    # + Accidentări — xG REAL, post-injury, deja calculat de evaluate_match()
    # (aplicat, în pipeline-ul real, DUPĂ H2H/vreme — vezi nota din header).
    ph_inj, pd_inj, pa_inj, _ = poisson_model(pred.home_xg, pred.away_xg, max_goals)
    _add("Accidentări", ph_inj)
    ph_current, pd_current, pa_current = ph_inj, pd_inj, pa_inj

    # + Blend ML (dacă activ) — folosește exact blend_predictions() real.
    if pred.ml_active:
        from ml_predictor import MLPrediction, blend_predictions
        ml_pred = MLPrediction(
            prob_home=pred.ml_prob_home, prob_draw=pred.ml_prob_draw, prob_away=pred.ml_prob_away,
            confidence=pred.ml_confidence, model_version=0, samples_used=pred.ml_samples_used,
        )
        ml_weight = float(config.get("ml_blend_weight", 0.35))
        ph_final, _, _, _ = blend_predictions((ph_current, pd_current, pa_current), ml_pred, ml_weight)
        _add("Model ML", ph_final)

    return MatchExplanation(stages=stages, final_prob_home=round(prev_ph, 4))
