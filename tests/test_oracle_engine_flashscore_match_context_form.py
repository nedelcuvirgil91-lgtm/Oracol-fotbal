"""Teste pentru Level FS2 (Flashscore recent match-context form) din
oracle_engine._build_profile() — adăugat 2026-08-10, caz real confirmat:
Univ. Craiova vs KuPS, Europa League calificări (fază eliminatorie fără
clasament, KuPS din Finlanda — niciodată în vreo ligă domestică urmărită).

Nivelul citește `database.queries.get_team_recent_form_context()`
(flashscore_match_context, migrația 046 — coloana `subject_team`) și e
poziționat între Level FS (clasament domestic) și Level 0+1 (FreeLF) —
completează exact golul pe care Level FS nu-l poate acoperi structural
(cupe eliminatorii fără clasament, echipe străine din ligi neurmărite)."""
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
    monkeypatch.setattr(oracle_engine, "get_team_standings_row", lambda team, league: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_form_freelf_snapshot", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_form_oddsapi", lambda team: [], raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_form_footballdata", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_stats_tsdb", lambda team: None, raising=False)


def test_match_context_form_populates_stats_with_real_form(monkeypatch):
    _base_mocks(monkeypatch)
    monkeypatch.setattr(
        oracle_engine, "get_team_recent_form_context",
        lambda team, n=5: [
            {"result": "L", "goals_for": 1, "goals_against": 5, "date": "2026-07-25"},
            {"result": "D", "goals_for": 1, "goals_against": 1, "date": "2026-08-06"},
            {"result": "L", "goals_for": 0, "goals_against": 1, "date": "2026-08-09"},
        ],
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("kx", "Univ. Craiova", "Europa League")

    assert p.data_source == "flashscore-match-context"
    assert p.form_results == ["L", "D", "L"]


def test_match_context_form_order_feeds_form_score_correctly(monkeypatch):
    """Ordinea cronologică (cel mai recent ULTIM), deja garantată de
    get_team_recent_form_context(), trebuie păstrată intactă până la
    compute_form_score()."""
    _base_mocks(monkeypatch)
    monkeypatch.setattr(
        oracle_engine, "get_team_recent_form_context",
        lambda team, n=5: [
            {"result": "L", "goals_for": 0, "goals_against": 2, "date": "2026-07-01"},
            {"result": "L", "goals_for": 0, "goals_against": 1, "date": "2026-07-10"},
            {"result": "W", "goals_for": 2, "goals_against": 0, "date": "2026-08-01"},
        ],
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("kx", "KuPS", "Europa League")

    assert p.form_results == ["L", "L", "W"]
    from feature_engine import compute_form_score
    assert compute_form_score(p.form_results) > compute_form_score(list(reversed(p.form_results)))


def test_works_for_team_never_in_any_tracked_domestic_league(monkeypatch):
    """Cazul real care a motivat feature-ul: KuPS (Finlanda) — Level FS
    (clasament) nu găsește nimic (mockat None), dar Level FS2 găsește
    formă reală din flashscore_match_context."""
    _base_mocks(monkeypatch)
    monkeypatch.setattr(
        oracle_engine, "get_team_recent_form_context",
        lambda team, n=5: [{"result": "D", "goals_for": 1, "goals_against": 1, "date": "2026-08-06"}],
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("kx", "KuPS", "Europa League")

    assert p.data_source == "flashscore-match-context"
    assert p.form_results == ["D"]


def test_match_context_form_wins_over_freelf(monkeypatch):
    """Level FS2 e poziționat ÎNAINTEA Level 0+1 (FreeLF) — dacă ambele
    au date, Flashscore match-context câștigă."""
    _base_mocks(monkeypatch)
    monkeypatch.setattr(
        oracle_engine, "get_team_recent_form_context",
        lambda team, n=5: [{"result": "W", "goals_for": 2, "goals_against": 0, "date": "2026-08-06"}],
        raising=False,
    )
    monkeypatch.setattr(
        oracle_engine, "get_team_form_freelf_snapshot",
        lambda team: {"played": 10, "goals_for": 20, "goals_against": 8, "form": ""},
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("kx", "Univ. Craiova", "Europa League")

    assert p.data_source == "flashscore-match-context"


def test_flashscore_standings_wins_over_match_context_form(monkeypatch):
    """Level FS (clasament domestic) rulează ÎNAINTEA Level FS2 — dacă
    Level FS are date reale, Level FS2 nu mai e apelat deloc."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(
        oracle_engine, "get_team_standings_row",
        lambda team, league: {
            "played": 4, "won": 3, "drawn": 0, "lost": 1,
            "goals_for": 8, "goals_against": 4, "form": ["W", "W", "W", "L"],
        },
        raising=False,
    )
    calls: list[str] = []

    def _track(team, n=5):
        calls.append(team)
        return [{"result": "W", "goals_for": 1, "goals_against": 0, "date": "2026-08-06"}]

    monkeypatch.setattr(oracle_engine, "get_team_recent_form_context", _track, raising=False)
    eng = _engine()

    p = eng._build_profile("kx", "Univ. Craiova", "Romania SuperLiga")

    assert p.data_source == "flashscore-standings"
    assert calls == []


def test_empty_match_context_form_falls_through_to_freelf(monkeypatch):
    _base_mocks(monkeypatch)
    monkeypatch.setattr(oracle_engine, "get_team_recent_form_context", lambda team, n=5: [], raising=False)
    monkeypatch.setattr(
        oracle_engine, "get_team_form_freelf_snapshot",
        lambda team: {"played": 10, "goals_for": 20, "goals_against": 8, "form": ""},
        raising=False,
    )
    eng = _engine()

    p = eng._build_profile("kx", "New Team FC", "Europa League")

    assert p.data_source == "freelf-standings"


def test_match_context_form_read_failure_falls_back_gracefully(monkeypatch):
    _base_mocks(monkeypatch)

    def _boom(team, n=5):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_team_recent_form_context", _boom, raising=False)
    eng = _engine()

    p = eng._build_profile("kx", "Univ. Craiova", "Europa League")  # nu crapă

    assert p.data_source != "flashscore-match-context"


def test_db_history_wins_match_context_form_never_queried(monkeypatch):
    """Level DB (match_history) rulează PRIMUL — dacă are deja suficiente
    meciuri, Level FS2 nu mai apelează deloc get_team_recent_form_context()."""
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
    monkeypatch.setattr(oracle_engine, "get_team_standings_row", lambda team, league: None, raising=False)

    calls: list[str] = []

    def _track(team, n=5):
        calls.append(team)
        return [{"result": "W", "goals_for": 1, "goals_against": 0, "date": "2026-08-06"}]

    monkeypatch.setattr(oracle_engine, "get_team_recent_form_context", _track, raising=False)
    eng = _engine()

    p = eng._build_profile("kx", "Arsenal", "Premier League")

    assert p.data_source == "supabase-history"
    assert calls == []
