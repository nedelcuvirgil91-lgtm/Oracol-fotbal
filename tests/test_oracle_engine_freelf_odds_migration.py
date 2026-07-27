"""Teste comportamentale pentru migrarea R-Sync-6 (ADR-039) — dovedesc
explicit că logica de derivare mutată în oracle_engine.py (foste
Level 0+1 FreeLF, Level 2 Odds API, fallback H2H Odds API) produce
rezultate identice cu calea live veche, pornind acum de la rânduri
Supabase (mockate direct, fără rețea reală)."""
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


# ── _build_profile(): Level 0+1 (FreeLF, fuzionate) ──────────────────────────

def test_freelf_snapshot_populates_stats_and_data_source(monkeypatch):
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(
        oracle_engine, "get_team_form_freelf_snapshot",
        lambda team: {"played": 10, "goals_for": 20, "goals_against": 8, "form": ""},
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("freelf_x", "Arsenal", "Premier League")

    assert p.data_source == "freelf-standings"
    assert abs(p.avg_goals_for - 2.0) < 1e-9
    assert abs(p.avg_goals_against - 0.8) < 1e-9


def test_freelf_snapshot_form_string_drives_form_results_when_present(monkeypatch):
    """Dacă snapshot-ul are (ipotetic) un `form` nevid — comportamentul
    corect al cascadei: form_source = recent_form (nu stats-ul placeholder
    "W" repetat). Testul rămâne valabil și după R-Sync-6a, când `form` va
    fi în sfârșit populat cu date reale."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(
        oracle_engine, "get_team_form_freelf_snapshot",
        lambda team: {"played": 10, "goals_for": 20, "goals_against": 8, "form": "WWDLW"},
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("freelf_x", "Arsenal", "Premier League")

    assert p.form_results == ["W", "W", "D", "L", "W"]


def test_freelf_snapshot_empty_form_falls_back_to_stats_results(monkeypatch):
    """[REGRESIE, R-Sync-6] Comportament fidel bug-ului preexistent —
    form="" (cazul real azi) -> form_source cade pe `stats` (placeholder
    "W" repetat), la fel ca înainte de migrare."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(
        oracle_engine, "get_team_form_freelf_snapshot",
        lambda team: {"played": 10, "goals_for": 20, "goals_against": 8, "form": ""},
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("freelf_x", "Arsenal", "Premier League")

    assert p.form_results == ["W"] * 5


def test_no_freelf_row_falls_through_without_crashing(monkeypatch):
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_form_freelf_snapshot", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_form_oddsapi", lambda team: [], raising=False)
    eng = _engine()

    p = eng._build_profile("freelf_x", "Unknown Team FC", "Unknown League")

    assert p.data_source != "freelf-standings"


def test_freelf_read_failure_falls_back_gracefully(monkeypatch):
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)

    def _boom(team):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_team_form_freelf_snapshot", _boom, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_form_oddsapi", lambda team: [], raising=False)
    eng = _engine()

    p = eng._build_profile("freelf_x", "Arsenal", "Premier League")  # nu crapă

    assert p.data_source != "freelf-standings"


# ── _build_profile(): Level 2 (Odds API meciuri recente) ────────────────────

def test_odds_recent_results_populate_stats_when_freelf_empty(monkeypatch):
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_form_freelf_snapshot", lambda team: None, raising=False)
    monkeypatch.setattr(
        oracle_engine, "get_team_recent_form_oddsapi",
        lambda team: [
            {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
             "kickoff_date": "2026-08-01", "home_score": 2, "away_score": 1},
            {"home_team_canonical": "Liverpool", "away_team_canonical": "Arsenal",
             "kickoff_date": "2026-08-02", "home_score": 0, "away_score": 0},
        ],
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("odds_x", "Arsenal", "Premier League")

    assert p.data_source == "scores-api"
    # Arsenal: gazdă în primul (2-1, W), oaspete în al doilea (0-0, D)
    # gf = (2+0)/2 = 1.0 ; ga = (1+0)/2 = 0.5
    assert abs(p.avg_goals_for - 1.0) < 1e-9
    assert abs(p.avg_goals_against - 0.5) < 1e-9


def test_odds_recent_results_read_failure_falls_back_gracefully(monkeypatch):
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_form_freelf_snapshot", lambda team: None, raising=False)

    def _boom(team):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_team_recent_form_oddsapi", _boom, raising=False)
    eng = _engine()

    p = eng._build_profile("odds_x", "Arsenal", "Premier League")  # nu crapă

    assert p.data_source != "scores-api"


# ── _build_h2h(): fallback Odds API meciuri recente ──────────────────────────

def _match():
    return {"home_team": "Arsenal", "away_team": "Chelsea", "league": "Premier League"}


def test_odds_h2h_derives_correctly_from_supabase_rows(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_h2h_from_history", lambda home, away, last_n=10: [], raising=False)
    monkeypatch.setattr(
        oracle_engine, "get_h2h_from_odds_recent",
        lambda home, away, last_n=5: [
            {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
             "kickoff_date": "2026-08-01", "home_score": 2, "away_score": 1},
            {"home_team_canonical": "Chelsea", "away_team_canonical": "Arsenal",
             "kickoff_date": "2025-12-01", "home_score": 1, "away_score": 1},
        ],
        raising=False,
    )
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = SimpleNamespace(get_h2h=lambda eid, h, a: None)

    h = eng._build_h2h("Arsenal", "Chelsea", _match())

    assert h.meetings == 2
    assert (h.home_wins, h.draws, h.away_wins) == (1, 1, 0)
    assert h.last_5 == ["H", "D"]


def test_odds_h2h_empty_when_no_rows(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_h2h_from_history", lambda home, away, last_n=10: [], raising=False)
    monkeypatch.setattr(oracle_engine, "get_h2h_from_odds_recent", lambda home, away, last_n=5: [], raising=False)
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = SimpleNamespace(get_h2h=lambda eid, h, a: None)

    h = eng._build_h2h("Arsenal", "Chelsea", _match())

    assert h.meetings == 0


def test_odds_h2h_read_failure_returns_empty_not_crash(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_h2h_from_history", lambda home, away, last_n=10: [], raising=False)

    def _boom(home, away, last_n=5):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_h2h_from_odds_recent", _boom, raising=False)
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = SimpleNamespace(get_h2h=lambda eid, h, a: None)

    h = eng._build_h2h("Arsenal", "Chelsea", _match())  # nu crapă

    assert h.meetings == 0


def test_freelf_h2h_still_takes_priority_over_odds_when_event_id_present(monkeypatch):
    """Regresie: FreeLF H2H (deliberat neatinsă, R-Sync-8) rămâne
    prioritară față de Odds API atunci când _freelf_event_id există —
    Odds API rămâne strict fallback de nivel următor."""
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_h2h_from_history", lambda home, away, last_n=10: [], raising=False)
    monkeypatch.setattr(
        oracle_engine, "get_h2h_from_odds_recent",
        lambda home, away, last_n=5: [{"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
                                        "kickoff_date": "2026-08-01", "home_score": 9, "away_score": 9}],
        raising=False,
    )
    freelf_h2h = {"meetings": 3, "home_wins": 3, "draws": 0, "away_wins": 0,
                  "home_goals_avg": 2.0, "away_goals_avg": 0.0, "last_5": ["H", "H", "H"],
                  "h2h_modifier": 0.15, "summary": "FREELF"}
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = SimpleNamespace(get_h2h=lambda eid, h, a: freelf_h2h)

    h = eng._build_h2h("Arsenal", "Chelsea", {**_match(), "_freelf_event_id": 123})

    assert h.summary == "FREELF"
    assert h.meetings == 3
