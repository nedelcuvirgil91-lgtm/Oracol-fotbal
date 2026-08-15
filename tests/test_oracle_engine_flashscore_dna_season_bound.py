"""Teste pentru mărginirea la sezonul curent a Team DNA Flashscore
(oracle_engine._current_season_start_date / _build_flashscore_dna) —
cerință explicită a proprietarului produsului (sesiune 2026-08-15):
loturile se schimbă între sezoane, profilul de echipă trebuie să reflecte
doar sezonul curent, nu istoricul cross-sezon."""
from __future__ import annotations

from datetime import date

import oracle_engine


# ════════════════════════════════════════════════════════════════════════
# _current_season_start_date
# ════════════════════════════════════════════════════════════════════════

def test_season_start_after_july_cutover_is_same_calendar_year():
    assert oracle_engine.FootballOracleEngine._current_season_start_date(
        date(2026, 8, 15)
    ) == "2026-07-01"


def test_season_start_before_july_cutover_is_previous_calendar_year():
    assert oracle_engine.FootballOracleEngine._current_season_start_date(
        date(2027, 3, 1)
    ) == "2026-07-01"


def test_season_start_exactly_on_july_first():
    assert oracle_engine.FootballOracleEngine._current_season_start_date(
        date(2026, 7, 1)
    ) == "2026-07-01"


# ════════════════════════════════════════════════════════════════════════
# _build_flashscore_dna — since_date propagat la toate cele 3 interogări
# ════════════════════════════════════════════════════════════════════════

def test_build_flashscore_dna_forwards_season_start_to_all_three_queries(monkeypatch):
    calls: dict[str, str | None] = {}

    def _advanced(team, league, last_n=5, since_date=None):
        calls["advanced"] = since_date
        return []

    def _extended(team, league, last_n=5, since_date=None):
        calls["extended"] = since_date
        return []

    def _ratings(team, league, last_n=5, since_date=None):
        calls["ratings"] = since_date
        return []

    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "FLASHSCORE_TEAM_DNA_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_advanced_stats", _advanced, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_statistics_extended", _extended, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_recent_player_ratings", _ratings, raising=False)
    monkeypatch.setattr(oracle_engine, "get_team_standings_row", lambda team, league: None, raising=False)

    expected = oracle_engine.FootballOracleEngine._current_season_start_date()
    oracle_engine.FootballOracleEngine._build_flashscore_dna("FCSB", "Romania SuperLiga")

    assert calls == {"advanced": expected, "extended": expected, "ratings": expected}


def test_build_flashscore_dna_returns_none_when_modules_unavailable(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", False, raising=False)
    assert oracle_engine.FootballOracleEngine._build_flashscore_dna("FCSB", "Romania SuperLiga") is None
