"""
Teste pentru FootballOracleEngine._real_match_events() — cornere/faulturi/
cartonașe reale, informative (Task 2, ADR-011), afișate în TeamProfile
fără a alimenta formula de rating. Fără rețea, fără Supabase live.
"""
import oracle_engine


def test_averages_computed_correctly_home_and_away(monkeypatch):
    rows = [
        {"home_team": "Arsenal", "away_team": "Chelsea",
         "home_corners": 6, "away_corners": 3, "home_fouls": 10, "away_fouls": 12,
         "home_yellow_cards": 2, "away_yellow_cards": 1},
        {"home_team": "Liverpool", "away_team": "Arsenal",
         "home_corners": 5, "away_corners": 4, "home_fouls": 8, "away_fouls": 9,
         "home_yellow_cards": 3, "away_yellow_cards": 2},
    ]
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True)
    monkeypatch.setattr(oracle_engine.sb, "get_team_recent_match_events", lambda team, league, last_n=5: rows)

    result = oracle_engine.FootballOracleEngine._real_match_events("Arsenal", "Premier League")
    assert result["avg_corners"] == (6 + 4) / 2
    assert result["avg_fouls"] == (10 + 9) / 2
    assert result["avg_yellow_cards"] == (2 + 2) / 2


def test_no_history_returns_all_none():
    result = oracle_engine.FootballOracleEngine._real_match_events("Echipa Necunoscuta", "Liga Necunoscuta")
    assert result == {"avg_corners": None, "avg_fouls": None, "avg_yellow_cards": None}


def test_supabase_unavailable_returns_all_none(monkeypatch):
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", False)
    result = oracle_engine.FootballOracleEngine._real_match_events("Arsenal", "Premier League")
    assert result == {"avg_corners": None, "avg_fouls": None, "avg_yellow_cards": None}


def test_partial_null_fields_handled_independently(monkeypatch):
    """Daca doar cornere lipsesc pe un rand, media pentru fouls/cards tot se calculeaza."""
    rows = [
        {"home_team": "Arsenal", "away_team": "Chelsea",
         "home_corners": None, "away_corners": 3, "home_fouls": 10, "away_fouls": 12,
         "home_yellow_cards": None, "away_yellow_cards": 1},
    ]
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True)
    monkeypatch.setattr(oracle_engine.sb, "get_team_recent_match_events", lambda team, league, last_n=5: rows)

    result = oracle_engine.FootballOracleEngine._real_match_events("Arsenal", "Premier League")
    assert result["avg_corners"] is None  # singura valoare disponibila era None
    assert result["avg_fouls"] == 10.0
    assert result["avg_yellow_cards"] is None
