"""Teste de integrare pentru view-ul Value Bets din app.py, folosind
streamlit.testing.v1.AppTest (rulare headless reală a scriptului, fără
browser). Fără rețea: toate meciurile sunt pre-cache-uite în session_state
înainte de prima rulare, exact tiparul pe care sprintul îl cere — Dashboard-ul
nu trebuie să depindă de apeluri live dacă meciul e deja analizat.
"""
from __future__ import annotations

import time
from datetime import date

import pathlib

from streamlit.testing.v1 import AppTest

from oracle_engine import H2HRecord, MatchPrediction, TeamProfile

# [REPARAT 2026-08-21] `AppTest.from_file(_APP)` era rezolvat relativ la
# fisierul de test (`tests/app.py`), nu la radacina repo-ului — FileNotFoundError
# la fiecare rulare. Calea se calculeaza acum explicit din locatia acestui
# fisier, deci nu mai depinde nici de directorul de lucru, nici de felul in care
# Streamlit alege sa rezolve caile relative.
_APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")

TODAY = date.today().isoformat()


def _fake_pred(fixture_id: str, home: str, away: str, league: str, edge: float) -> MatchPrediction:
    home_p = TeamProfile(
        team_id="h", team_name=home, matches_analysed=10,
        avg_goals_for=2.0, avg_goals_against=1.0, avg_shots_ot=6.0, avg_possession=55.0,
        offensive_rating=1.5, defensive_rating=1.0,
        form_results=["W", "W", "D"], form_score=0.7,
        standings_form="", elo_rating=1700, data_source="test", data_quality="live", data_quality_note="",
    )
    away_p = TeamProfile(
        team_id="a", team_name=away, matches_analysed=10,
        avg_goals_for=1.2, avg_goals_against=1.4, avg_shots_ot=4.0, avg_possession=45.0,
        offensive_rating=1.0, defensive_rating=1.3,
        form_results=["L", "D", "W"], form_score=0.4,
        standings_form="", elo_rating=1550, data_source="test", data_quality="live", data_quality_note="",
    )
    return MatchPrediction(
        fixture_id=fixture_id, home_team=home, away_team=away, league=league,
        kickoff_utc=f"{TODAY}T18:00:00Z", kickoff_date=TODAY, season=2026,
        home_xg=1.8, away_xg=1.1, prob_home_win=0.55, prob_draw=0.25, prob_away_win=0.20,
        top_scores=[], bk_home_odds=2.1, bk_draw_odds=3.4, bk_away_odds=3.8, bookmaker_name="Demo",
        impl_home_pct=0.0, impl_draw_pct=0.0, impl_away_pct=0.0,
        edge_home_pct=edge, edge_draw_pct=0.0, edge_away_pct=0.0,
        value_bets=[{"market": "1X2", "selection": "Home Win", "edge_pct": edge,
                     "model_prob_pct": 55.0, "bk_odds": 2.1, "rating": "🔥 HIGH"}],
        weather_note="", weather_penalty=0.0, kelly_stakes={"Home Win": 8.25},
        home_profile=home_p, away_profile=away_p, h2h=H2HRecord.empty(home, away),
        data_quality_home="live", data_quality_away="live",
        home_injury_report=None, away_injury_report=None, injury_note="",
        home_xg_pre_injury=1.8, away_xg_pre_injury=1.1,
        special_value_bets=[],
    )


def test_value_bets_view_reuses_cached_predictions_without_recompute():
    """Cerința centrală a sprintului: dacă meciurile de azi sunt deja
    analizate (cache de sesiune valid), view-ul NU recalculează — 0 apeluri
    evaluate_match(), doar agregare peste ce există deja."""
    at = AppTest.from_file(_APP, default_timeout=30)

    at.session_state["nav"] = "value_bets"
    at.session_state["all_matches"] = [
        {"fixture_id": "demo1", "home_team": "Arsenal", "away_team": "Chelsea",
         "league": "Premier League", "kickoff_date": TODAY, "kickoff_utc": f"{TODAY}T18:00:00Z"},
        {"fixture_id": "demo2", "home_team": "Real Madrid", "away_team": "Betis",
         "league": "La Liga", "kickoff_date": TODAY, "kickoff_utc": f"{TODAY}T20:00:00Z"},
    ]
    at.session_state["pred_demo1"] = {
        "pred": _fake_pred("demo1", "Arsenal", "Chelsea", "Premier League", edge=8.7),
        "cached_at": time.time(),
    }
    at.session_state["pred_demo2"] = {
        "pred": _fake_pred("demo2", "Real Madrid", "Betis", "La Liga", edge=6.3),
        "cached_at": time.time(),
    }

    t0 = time.time()
    at.run()
    elapsed = time.time() - t0

    assert not at.exception
    # rapid — sub 10s, fara retry-uri de retea (recalcularea unui singur meci
    # a durat ~40s in verificarea anterioara, fara cache)
    assert elapsed < 10, f"Prea lent ({elapsed:.1f}s) — pare că a recalculat, nu a reutilizat cache-ul"

    captions = " ".join(c.value for c in at.caption)
    assert "2 din cache" in captions
    assert "0 recalculate" in captions

    # tabelul agregat conține ambele value bets, sortate după edge descrescător
    # (Arsenal-Chelsea are edge 8.7, mai mare decât Real Madrid-Betis, 6.3)
    df = at.dataframe[0].value
    assert list(df["Meci"]) == ["Arsenal - Chelsea", "Real Madrid - Betis"]
    assert list(df["Edge %"]) == [8.7, 6.3]
    assert df.iloc[0]["Edge %"] >= df.iloc[1]["Edge %"]

    # mini audit de performanță — populat, nu afișat direct utilizatorului
    # (doar în session_state, citit de tab-ul Diagnostics)
    perf = at.session_state["perf_value_bets"]
    assert perf["matches"] == 2
    assert perf["from_cache"] == 2
    assert perf["recomputed"] == 0
    assert perf["avg_live_seconds"] == 0.0


def test_value_bets_view_shows_empty_state_without_matches_today():
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["nav"] = "value_bets"
    at.session_state["all_matches"] = [
        {"fixture_id": "future1", "home_team": "A", "away_team": "B", "league": "Premier League",
         "kickoff_date": "2099-01-01", "kickoff_utc": "2099-01-01T18:00:00Z"},
    ]
    at.run()
    assert not at.exception
    infos = " ".join(i.value for i in at.info)
    assert "Niciun meci azi" in infos
