"""Teste pentru flashscore_team_dna.py — funcții PURE (fără I/O), Faza 2
(ADR-044 §5). Verifică: rezoluția home/away corectă, degradare la None/
listă goală fără date, agregarea EAV pe stat_key real, combinarea în
build_team_dna(). Fără rețea."""
from __future__ import annotations

from flashscore_team_dna import (
    build_team_dna,
    rolling_advanced_stats,
    rolling_extended_stats,
    rolling_finishing_and_setpieces,
    rolling_player_ratings,
)


# ════════════════════════════════════════════════════════════════════════
# rolling_advanced_stats
# ════════════════════════════════════════════════════════════════════════

def test_rolling_advanced_stats_averages_correct_side():
    rows = [
        {"home_team": "Dinamo", "away_team": "Rapid",
         "home_xg_actual": 1.8, "away_xg_actual": 0.9,
         "home_possession": 55.0, "away_possession": 45.0,
         "home_offsides": 2, "away_offsides": 1,
         "home_goalkeeper_saves": 3, "away_goalkeeper_saves": 5,
         "home_red_cards": 0, "away_red_cards": 1,
         "actual_home_goals": 2, "actual_away_goals": 1},
        {"home_team": "Craiova", "away_team": "Dinamo",
         "home_xg_actual": 1.0, "away_xg_actual": 1.4,
         "home_possession": 48.0, "away_possession": 52.0,
         "home_offsides": 0, "away_offsides": 3,
         "home_goalkeeper_saves": 2, "away_goalkeeper_saves": 4,
         "home_red_cards": 0, "away_red_cards": 0,
         "actual_home_goals": 0, "actual_away_goals": 2},
    ]
    out = rolling_advanced_stats(rows, "Dinamo")
    assert out["avg_xg"] == (1.8 + 1.4) / 2
    assert out["avg_possession"] == (55.0 + 52.0) / 2
    assert out["avg_offsides"] == (2 + 3) / 2
    assert out["avg_goalkeeper_saves"] == (3 + 4) / 2
    assert out["avg_red_cards"] == (0 + 0) / 2
    assert out["avg_goals_for"] == (2 + 2) / 2
    assert out["avg_goals_against"] == (1 + 0) / 2
    assert out["matches_sampled"] == 2


def test_rolling_advanced_stats_skips_rows_without_the_team():
    rows = [{"home_team": "Craiova", "away_team": "Rapid", "home_xg_actual": 1.0}]
    out = rolling_advanced_stats(rows, "Dinamo")
    assert out["avg_xg"] is None


def test_rolling_advanced_stats_empty_input_returns_none_values():
    out = rolling_advanced_stats([], "Dinamo")
    assert out["avg_xg"] is None
    assert out["avg_possession"] is None
    assert out["matches_sampled"] == 0


def test_rolling_advanced_stats_none_values_excluded_not_treated_as_zero():
    rows = [
        {"home_team": "Dinamo", "away_team": "Rapid", "home_xg_actual": None,
         "home_possession": 60.0},
    ]
    out = rolling_advanced_stats(rows, "Dinamo")
    assert out["avg_xg"] is None
    assert out["avg_possession"] == 60.0


# ════════════════════════════════════════════════════════════════════════
# rolling_finishing_and_setpieces
# ════════════════════════════════════════════════════════════════════════

def test_rolling_finishing_sums_goals_and_xg_across_matches_not_per_match_average():
    rows = [
        {"home_team": "Dinamo", "away_team": "Rapid",
         "actual_home_goals": 2, "home_xg_actual": 1.0, "home_shots_on_target": 4, "home_corners": 6},
        {"home_team": "Craiova", "away_team": "Dinamo",
         "actual_away_goals": 1, "away_xg_actual": 1.0, "away_shots_on_target": 2, "away_corners": 4},
    ]
    out = rolling_finishing_and_setpieces(rows, "Dinamo")
    # 3 goluri / 2.0 xG total (nu media a (2/1 + 1/1)/2 = 1.5)
    assert out["goals_per_xg"] == 3 / 2.0
    assert out["goals_per_shot_on_target"] == 3 / 6
    assert out["avg_corners"] == (6 + 4) / 2
    assert out["matches_sampled"] == 2
    assert out["finishing_sample_matches"] == 2


def test_rolling_finishing_skips_rows_without_the_team():
    rows = [{"home_team": "Craiova", "away_team": "Rapid", "actual_home_goals": 1, "home_xg_actual": 1.0}]
    out = rolling_finishing_and_setpieces(rows, "Dinamo")
    assert out["goals_per_xg"] is None
    assert out["matches_sampled"] == 0


def test_rolling_finishing_does_not_pair_goals_with_missing_xg():
    rows = [{"home_team": "Dinamo", "away_team": "Rapid", "actual_home_goals": 2, "home_xg_actual": None}]
    out = rolling_finishing_and_setpieces(rows, "Dinamo")
    assert out["goals_per_xg"] is None
    assert out["finishing_sample_matches"] == 0


def test_rolling_finishing_empty_input_returns_none_values():
    out = rolling_finishing_and_setpieces([], "Dinamo")
    assert out["goals_per_xg"] is None
    assert out["goals_per_shot_on_target"] is None
    assert out["avg_corners"] is None
    assert out["matches_sampled"] == 0


# ════════════════════════════════════════════════════════════════════════
# rolling_extended_stats
# ════════════════════════════════════════════════════════════════════════

def test_rolling_extended_stats_groups_by_real_stat_key():
    rows = [
        {"stat_key": "passes", "value": 400.0},
        {"stat_key": "passes", "value": 500.0},
        {"stat_key": "big_chances", "value": 3.0},
    ]
    out = rolling_extended_stats(rows)
    assert out["passes"] == 450.0
    assert out["big_chances"] == 3.0


def test_rolling_extended_stats_empty_input():
    assert rolling_extended_stats([]) == {}


def test_rolling_extended_stats_skips_rows_with_missing_value():
    rows = [{"stat_key": "passes", "value": None}, {"stat_key": "passes", "value": 300.0}]
    out = rolling_extended_stats(rows)
    assert out["passes"] == 300.0


# ════════════════════════════════════════════════════════════════════════
# rolling_player_ratings
# ════════════════════════════════════════════════════════════════════════

def test_rolling_player_ratings_averages_real_ratings():
    rows = [{"rating": 7.5}, {"rating": 6.5}, {"rating": None}]
    out = rolling_player_ratings(rows)
    assert out["avg_player_rating"] == 7.0
    assert out["players_sampled"] == 2


def test_rolling_player_ratings_empty_input_returns_none():
    out = rolling_player_ratings([])
    assert out["avg_player_rating"] is None
    assert out["players_sampled"] == 0


# ════════════════════════════════════════════════════════════════════════
# build_team_dna
# ════════════════════════════════════════════════════════════════════════

def test_build_team_dna_combines_all_sections():
    advanced_rows = [{"home_team": "Dinamo", "away_team": "Rapid", "home_xg_actual": 1.5,
                       "actual_home_goals": 2, "home_shots_on_target": 3, "home_corners": 5}]
    extended_rows = [{"stat_key": "passes", "value": 400.0}]
    player_rows = [{"rating": 7.0}]
    standings_row = {"team": "Dinamo", "rank": 3, "points": 40}

    dna = build_team_dna(advanced_rows, extended_rows, player_rows, standings_row, "Dinamo")

    assert dna["advanced"]["avg_xg"] == 1.5
    assert dna["finishing"]["goals_per_xg"] == 2 / 1.5
    assert dna["finishing"]["avg_corners"] == 5
    assert dna["extended_stats"]["passes"] == 400.0
    assert dna["player_ratings"]["avg_player_rating"] == 7.0
    assert dna["standings"] == standings_row


def test_build_team_dna_degrades_independently_per_section():
    dna = build_team_dna([], [], [], None, "Dinamo")
    assert dna["advanced"]["avg_xg"] is None
    assert dna["finishing"]["goals_per_xg"] is None
    assert dna["extended_stats"] == {}
    assert dna["player_ratings"]["avg_player_rating"] is None
    assert dna["standings"] is None
