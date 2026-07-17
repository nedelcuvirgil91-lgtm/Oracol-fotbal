"""
Teste pentru FootballOracleEngine._real_avg_shots_on_target() — șuturi pe
poartă reale (din match_history, populate de MatchStatsBackfillService),
înlocuind proxy-ul sintetic (avg_gf*0.45) în TeamProfile, doar când există
date reale. Fără rețea, fără Supabase live.
"""
import oracle_engine


def test_real_avg_computed_correctly_home_and_away(monkeypatch):
    """Media se calculează corect indiferent dacă echipa a fost acasă sau
    în deplasare în fiecare meci din istoric."""
    rows = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "home_shots_on_target": 6, "away_shots_on_target": 3},
        {"home_team": "Liverpool", "away_team": "Arsenal", "home_shots_on_target": 5, "away_shots_on_target": 4},
    ]
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True)
    monkeypatch.setattr(oracle_engine.sb, "get_team_recent_shots", lambda team, league, last_n=5: rows)

    result = oracle_engine.FootballOracleEngine._real_avg_shots_on_target("Arsenal", "Premier League")
    assert result == (6 + 4) / 2  # meciul 1: Arsenal acasă (6), meciul 2: Arsenal deplasare (4)


def test_no_history_returns_none_not_approximated():
    """Fără date reale -> None, nu 0 sau vreo aproximare — apelantul
    păstrează fallback-ul sintetic existent."""
    import supabase_client as sb_module
    # sb.get_client() intoarce None cand SUPABASE_URL/SECRET_KEY lipsesc (mediu de test)
    result = oracle_engine.FootballOracleEngine._real_avg_shots_on_target("Echipa Necunoscuta", "Liga Necunoscuta")
    assert result is None


def test_supabase_module_unavailable_returns_none(monkeypatch):
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", False)
    result = oracle_engine.FootballOracleEngine._real_avg_shots_on_target("Arsenal", "Premier League")
    assert result is None


def test_rows_with_null_shots_on_target_skipped(monkeypatch):
    rows = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "home_shots_on_target": None, "away_shots_on_target": 3},
        {"home_team": "Arsenal", "away_team": "Everton", "home_shots_on_target": 7, "away_shots_on_target": 2},
    ]
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True)
    monkeypatch.setattr(oracle_engine.sb, "get_team_recent_shots", lambda team, league, last_n=5: rows)

    result = oracle_engine.FootballOracleEngine._real_avg_shots_on_target("Arsenal", "Premier League")
    assert result == 7.0  # primul rand are NULL -> ignorat, doar al doilea (7) conteaza
