"""Teste pentru Level FS (Flashscore standings) din oracle_engine.
_build_profile() — ADR-045, Owner Standings, adăugat 2026-08-10.

Nivelul nou citește `database.queries.get_team_standings_row()`
(flashscore_standings_snapshot, migrația 045 — coloana `form`, secvență
cronologică reală W/D/L) și e poziționat între Level DB/Level -1 (național
hardcodat) și Level 0+1 (FreeLF) — Owner declarat explicit de ADR-045
pentru Standings, cu prioritate față de fallback-urile existente."""
from __future__ import annotations

from types import SimpleNamespace

import oracle_engine


def _fake_sb_no_history(monkeypatch):
    fake = SimpleNamespace(
        get_team_recent_results=lambda team, league, last_n=5, lookback_days=365: [],
        get_team_recent_shots=lambda team, league, last_n=5: [],
        get_team_recent_match_events=lambda team, league, last_n=5: [],
    )
    monkeypatch.setattr(oracle_engine, "sb", fake, raising=False)
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True, raising=False)


def _engine() -> oracle_engine.FootballOracleEngine:
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = SimpleNamespace(get_team_stats=lambda tid, league: [])
    return eng


def _base_mocks(monkeypatch):
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_form_freelf_snapshot", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_form_oddsapi", lambda team: [], raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_form_footballdata", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_stats_tsdb", lambda team: None, raising=False)


def test_flashscore_standings_populates_stats_with_real_form(monkeypatch):
    _base_mocks(monkeypatch)
    monkeypatch.setattr(
        oracle_engine, "get_team_standings_row",
        lambda team, league: {
            "played": 4, "won": 3, "drawn": 0, "lost": 1,
            "goals_for": 8, "goals_against": 4,
            "form": ["W", "W", "W", "L"],
        },
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("fs_x", "FC Arges", "Romania SuperLiga")

    assert p.data_source == "flashscore-standings"
    assert p.form_results == ["W", "W", "W", "L"]
    assert abs(p.avg_goals_for - 2.0) < 1e-9   # 8/4
    assert abs(p.avg_goals_against - 1.0) < 1e-9  # 4/4


def test_flashscore_standings_form_order_feeds_form_score_correctly(monkeypatch):
    """Ordinea cronologică (cel mai recent ULTIM) trebuie păstrată intactă
    până la compute_form_score() — regresie directă pentru blocajul găsit
    la analiza inițială (FreeLF sintetiza mereu "W", fără ordine reală)."""
    _base_mocks(monkeypatch)
    monkeypatch.setattr(
        oracle_engine, "get_team_standings_row",
        lambda team, league: {
            "played": 3, "won": 1, "drawn": 0, "lost": 2,
            "goals_for": 3, "goals_against": 5,
            "form": ["L", "L", "W"],  # cel mai recent: victorie
        },
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("fs_x", "CFR Cluj", "Romania SuperLiga")

    assert p.form_results == ["L", "L", "W"]
    # form_score trebuie sa fie > 0.5 (favorizeaza rezultatul recent, W) -
    # daca ordinea ar fi inversata (W primul), scorul ar fi mult mai mic.
    from feature_engine import compute_form_score
    assert compute_form_score(p.form_results) > compute_form_score(list(reversed(p.form_results)))


def test_flashscore_standings_wins_over_freelf(monkeypatch):
    """Level FS e poziționat ÎNAINTEA Level 0+1 (FreeLF) — dacă ambele au
    date, Flashscore câștigă (Owner declarat, ADR-045)."""
    _base_mocks(monkeypatch)
    monkeypatch.setattr(
        oracle_engine, "get_team_standings_row",
        lambda team, league: {
            "played": 2, "won": 2, "drawn": 0, "lost": 0,
            "goals_for": 4, "goals_against": 0,
            "form": ["W", "W"],
        },
        raising=False,
    )
    monkeypatch.setattr(
        oracle_engine, "get_team_form_freelf_snapshot",
        lambda team: {"played": 10, "goals_for": 20, "goals_against": 8, "form": ""},
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("fs_x", "FCSB", "Romania SuperLiga")

    assert p.data_source == "flashscore-standings"


def test_flashscore_standings_empty_form_falls_through_to_freelf(monkeypatch):
    """Rândul de clasament există, dar `form` e goală (niciun rezultat
    real capturat încă) — nivelul NU se activează (Regula #8: mai bine
    cascada continuă decât un `results=[]` -> form_score=0.0 worst-case,
    tratat implicit ca neutru de restul cascadei)."""
    _base_mocks(monkeypatch)
    monkeypatch.setattr(
        oracle_engine, "get_team_standings_row",
        lambda team, league: {
            "played": 0, "won": 0, "drawn": 0, "lost": 0,
            "goals_for": 0, "goals_against": 0, "form": [],
        },
        raising=False,
    )
    monkeypatch.setattr(
        oracle_engine, "get_team_form_freelf_snapshot",
        lambda team: {"played": 10, "goals_for": 20, "goals_against": 8, "form": ""},
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("fs_x", "New Team FC", "Romania SuperLiga")

    assert p.data_source == "freelf-standings"


def test_no_flashscore_standings_row_falls_through_without_crashing(monkeypatch):
    _base_mocks(monkeypatch)
    monkeypatch.setattr(oracle_engine, "get_team_standings_row", lambda team, league: None, raising=False)
    eng = _engine()

    p = eng._build_profile("fs_x", "Unknown Team FC", "Unknown League")

    assert p.data_source != "flashscore-standings"


def test_flashscore_standings_read_failure_falls_back_gracefully(monkeypatch):
    _base_mocks(monkeypatch)

    def _boom(team, league):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_team_standings_row", _boom, raising=False)
    eng = _engine()

    p = eng._build_profile("fs_x", "FC Arges", "Romania SuperLiga")  # nu crapă

    assert p.data_source != "flashscore-standings"


def test_db_history_wins_flashscore_standings_never_queried(monkeypatch):
    """Level DB (match_history) rulează PRIMUL — dacă are deja suficiente
    meciuri, Level FS nu mai apelează deloc get_team_standings_row()
    (gate-ul `if not stats`, identic restului cascadei)."""
    fake = SimpleNamespace(
        get_team_recent_results=lambda team, league, last_n=5, lookback_days=365: [
            {"home_team": "Arsenal", "away_team": "X", "actual_result": "H",
             "actual_home_goals": 2, "actual_away_goals": 0},
            {"home_team": "Y", "away_team": "Arsenal", "actual_result": "A",
             "actual_home_goals": 0, "actual_away_goals": 1},
            {"home_team": "Arsenal", "away_team": "Z", "actual_result": "D",
             "actual_home_goals": 1, "actual_away_goals": 1},
        ],
        get_team_recent_shots=lambda team, league, last_n=5: [],
        get_team_recent_match_events=lambda team, league, last_n=5: [],
    )
    monkeypatch.setattr(oracle_engine, "sb", fake, raising=False)
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)

    calls: list[str] = []

    def _track(team, league):
        calls.append(team)
        return {"played": 4, "won": 4, "drawn": 0, "lost": 0,
                "goals_for": 8, "goals_against": 0, "form": ["W", "W", "W", "W"]}

    monkeypatch.setattr(oracle_engine, "get_team_standings_row", _track, raising=False)
    eng = _engine()

    p = eng._build_profile("fs_x", "Arsenal", "Premier League")

    assert p.data_source == "supabase-history"
    assert calls == []
