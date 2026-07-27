"""Teste pentru ADR-035 / D1 — Level DB (Supabase match_history) devine
PRIMUL nivel în cascada _build_profile(), înaintea oricărui provider.

Reproduce exact cazul demonstrat de auditul Petrolul-Dinamo (2026-07-19):
match_history avea 38-40 meciuri terminate per echipă, dar profilul se
construia din 1 meci TheSportsDB cu șuturi sintetice. După D1, profilul
trebuie să vină din match_history (data_source="supabase-history"), iar
cascada veche rămâne fallback intact pentru echipe fără istoric suficient.

Toate testele pică pe codul pre-D1 (verificat) și trec după."""
from __future__ import annotations

from types import SimpleNamespace

import oracle_engine


def _fake_api(tsdb_stats: list[dict] | None = None):
    """Stub minimal pentru FootballOracleAPI — doar metodele atinse de
    _build_profile(), fiecare inertă (fără rețea)."""
    return SimpleNamespace(
        get_freelf_standings=lambda league: [],
        get_team_form_freelf=lambda tid, league, n: [],
        get_team_recent_form=lambda name, league, days_back=14: [],
        get_team_stats=lambda tid, league: list(tsdb_stats or []),
    )


def _engine(tsdb_stats: list[dict] | None = None) -> oracle_engine.FootballOracleEngine:
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = _fake_api(tsdb_stats)
    return eng


def _fake_sb(monkeypatch, recent_results: list[dict]):
    fake = SimpleNamespace(
        get_team_recent_results=lambda team, league, last_n=5, lookback_days=365: list(recent_results),
        get_team_recent_shots=lambda team, league, last_n=5: [],
        get_team_recent_match_events=lambda team, league, last_n=5: [],
    )
    monkeypatch.setattr(oracle_engine, "sb", fake, raising=False)
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True, raising=False)
    return fake


PETROLUL = "Petrolul Ploiești"
DB_ROWS_PETROLUL = [
    # ultimele 5 din match_history, exact forma reala din audit (D,D,L,L,D
    # din perspectiva echipei; mix acasa/deplasare ca sa acopere maparea)
    {"home_team": PETROLUL, "away_team": "Otelul", "actual_home_goals": 0,
     "actual_away_goals": 1, "actual_result": "A", "kickoff_date": "2026-05-18"},
    {"home_team": "FC Botosani", "away_team": PETROLUL, "actual_home_goals": 1,
     "actual_away_goals": 1, "actual_result": "D", "kickoff_date": "2026-05-10"},
    {"home_team": PETROLUL, "away_team": "UTA Arad", "actual_home_goals": 2,
     "actual_away_goals": 2, "actual_result": "D", "kickoff_date": "2026-05-03"},
    {"home_team": "FCSB", "away_team": PETROLUL, "actual_home_goals": 2,
     "actual_away_goals": 0, "actual_result": "H", "kickoff_date": "2026-04-24"},
    {"home_team": PETROLUL, "away_team": "FC Hermannstadt", "actual_home_goals": 1,
     "actual_away_goals": 1, "actual_result": "D", "kickoff_date": "2026-04-19"},
]

TSDB_ONE_MATCH = [{"result": "D", "goals_for": 2, "goals_against": 2,
                   "shots_on_goal": 7.0, "possession": 50.0}]


def test_profile_comes_from_match_history_when_db_has_enough_matches(monkeypatch):
    """Cazul central al auditului: cu istoric suficient în DB, profilul NU
    mai vine de la TSDB (1 meci), ci din match_history."""
    _fake_sb(monkeypatch, DB_ROWS_PETROLUL)
    eng = _engine(tsdb_stats=TSDB_ONE_MATCH)

    p = eng._build_profile("tsdb_134398", PETROLUL, "Romania SuperLiga")

    assert p.data_source == "supabase-history"
    assert p.matches_analysed == 5
    # ordinea DESC din DB: L, D, D, L, D — maparea W/L/D corecta pe ambele
    # perspective (acasa si deplasare)
    assert p.form_results == ["L", "D", "D", "L", "D"]
    # gf mediu: (0+1+2+0+1)/5 = 0.8 ; ga mediu: (1+1+2+2+1)/5 = 1.4
    assert abs(p.avg_goals_for - 0.8) < 1e-9
    assert abs(p.avg_goals_against - 1.4) < 1e-9


def test_falls_back_to_provider_cascade_when_db_insufficient(monkeypatch):
    """Sub pragul minim (3 meciuri), cascada veche rămâne neatinsă —
    TSDB e folosit exact ca înainte de D1."""
    _fake_sb(monkeypatch, DB_ROWS_PETROLUL[:2])  # doar 2 meciuri
    eng = _engine(tsdb_stats=TSDB_ONE_MATCH)

    p = eng._build_profile("tsdb_134398", PETROLUL, "Romania SuperLiga")

    assert p.data_source == "thesportsdb"
    assert p.matches_analysed == 1


def test_falls_back_when_supabase_module_unavailable(monkeypatch):
    """Fără modulul Supabase, comportamentul pre-D1 e identic — nicio
    dependință nouă obligatorie."""
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", False, raising=False)
    eng = _engine(tsdb_stats=TSDB_ONE_MATCH)

    p = eng._build_profile("tsdb_134398", PETROLUL, "Romania SuperLiga")

    assert p.data_source == "thesportsdb"


def test_db_level_ignores_rows_with_missing_goals_or_result(monkeypatch):
    """Rândurile incomplete nu se aproximează (Regula #8) — se ignoră; dacă
    rămân sub prag, se cade pe cascada veche."""
    dirty = [
        {"home_team": PETROLUL, "away_team": "X", "actual_home_goals": None,
         "actual_away_goals": 1, "actual_result": "H", "kickoff_date": "2026-05-01"},
        {"home_team": PETROLUL, "away_team": "Y", "actual_home_goals": 2,
         "actual_away_goals": 1, "actual_result": None, "kickoff_date": "2026-04-20"},
        {"home_team": PETROLUL, "away_team": "Z", "actual_home_goals": 1,
         "actual_away_goals": 0, "actual_result": "H", "kickoff_date": "2026-04-10"},
    ]
    _fake_sb(monkeypatch, dirty)
    eng = _engine(tsdb_stats=TSDB_ONE_MATCH)

    p = eng._build_profile("tsdb_134398", PETROLUL, "Romania SuperLiga")

    # doar 1 rând valid < MIN_DB_MATCHES -> fallback provider
    assert p.data_source == "thesportsdb"


def test_national_hardcoded_stats_still_used_when_db_insufficient(monkeypatch):
    """Echipele naționale fără istoric suficient în DB păstrează exact
    comportamentul vechi (NATIONAL_TEAM_STATS) — zero regresie pe World Cup."""
    _fake_sb(monkeypatch, [])
    eng = _engine()

    p = eng._build_profile("odds_x", "France", "World Cup 2026")

    assert p.data_source == "national-stats-hardcoded"
