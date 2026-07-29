"""Teste pentru providers/flashscore/persistence.py — orchestrarea
persist() completa a unui meci Flashscore (Foundation Data Layer),
contra fixture-ului real (docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/).

Toate funcțiile database.queries sunt mock-uite (nu se atinge Supabase) —
scopul acestor teste e verificarea orchestrării (ordinea corectă, join-ul
nume↔echipă, propagarea match_id, raportarea per-pas), nu re-testarea
persistenței low-level (deja acoperită în
test_database_queries_flashscore_foundation_data_layer.py). Fără rețea."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from providers.flashscore.persistence import (
    _join_player_stats_with_roster,
    persist_match_foundation_data,
)

FIXTURE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_full_tabs_poc"


@pytest.fixture(scope="module")
def full_tabs_pages() -> dict[str, str]:
    return {f.stem: f.read_text(encoding="utf-8") for f in FIXTURE_DIR.glob("*.html")}


def test_join_player_stats_with_roster_resolves_team():
    roster = [
        {"team": "home", "player_name": "Pop A.", "shirt_number": 7},
        {"team": "away", "player_name": "Ion M.", "shirt_number": 9},
    ]
    stats = [
        {"player_name": "Pop A.", "position": "Striker", "rating": 8.7, "extended_stats": []},
        {"player_name": "Necunoscut X.", "position": "Winger", "rating": 7.0, "extended_stats": []},
    ]
    joined = _join_player_stats_with_roster(stats, roster)
    by_name = {r["player_name"]: r for r in joined}
    assert by_name["Pop A."]["team"] == "home"
    assert by_name["Necunoscut X."]["team"] is None


def test_persist_match_foundation_data_full_orchestration(monkeypatch, full_tabs_pages):
    calls: list[str] = []

    def _mk(name, return_value):
        def _fn(*a, **kw):
            calls.append(name)
            return return_value
        return _fn

    monkeypatch.setattr(
        "providers.flashscore.persistence.upsert_match_and_get_id", _mk("match_history", 123),
    )
    monkeypatch.setattr(
        "providers.flashscore.persistence.upsert_match_statistics_extended", _mk("match_statistics_extended", True),
    )
    roster_mock = _mk("player_roster", True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_roster", roster_mock)
    extended_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_match_stats_extended", extended_mock)
    monkeypatch.setattr(
        "providers.flashscore.persistence.upsert_match_context", _mk("match_context", True),
    )
    standings_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_standings_snapshot", standings_mock)

    report = persist_match_foundation_data(full_tabs_pages, competition="SuperLiga")

    assert report["match_id"] == 123
    assert report["ok"] is True
    assert report["steps"] == {
        "match_history": True, "match_statistics_extended": True, "player_roster": True,
        "player_match_stats_extended": True, "match_context": True, "standings_snapshot": True,
    }
    assert "match_history" in calls

    # match_id (123) propagat corect la statisticile extinse.
    extended_call_args = extended_mock.call_args
    assert extended_call_args[0][0] == 123
    # join name<->echipa aplicat inaintea scrierii - Pop A. e in roster (home).
    joined_rows = extended_call_args[0][1]
    pop = next(r for r in joined_rows if r["player_name"] == "Pop A.")
    assert pop["team"] == "home"

    # standings scris doar cand se da o competitie.
    assert standings_mock.call_args[0][0][0]["competition"] == "SuperLiga"


def test_persist_match_foundation_data_no_competition_skips_standings(monkeypatch, full_tabs_pages):
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", lambda *a, **kw: 123)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_statistics_extended", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_roster", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_match_stats_extended", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_context", lambda *a, **kw: True)
    standings_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_standings_snapshot", standings_mock)

    report = persist_match_foundation_data(full_tabs_pages, competition=None)

    assert report["ok"] is True
    assert report["steps"]["standings_snapshot"] is True
    standings_mock.assert_not_called()


def test_persist_match_foundation_data_aborts_without_natural_key(monkeypatch):
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", lambda *a, **kw: 123)
    report = persist_match_foundation_data({}, competition=None)
    assert report["match_id"] is None
    assert report["ok"] is False


def test_persist_match_foundation_data_reports_partial_failure(monkeypatch, full_tabs_pages):
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", lambda *a, **kw: 123)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_statistics_extended", lambda *a, **kw: False)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_roster", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_match_stats_extended", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_context", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_standings_snapshot", lambda *a, **kw: True)

    report = persist_match_foundation_data(full_tabs_pages, competition=None)

    assert report["ok"] is False
    assert report["steps"]["match_statistics_extended"] is False
    assert report["match_id"] == 123


def test_persist_match_foundation_data_returns_none_match_id_when_upsert_fails(monkeypatch, full_tabs_pages):
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", lambda *a, **kw: None)
    report = persist_match_foundation_data(full_tabs_pages, competition=None)
    assert report["match_id"] is None
    assert report["ok"] is False
    assert report["steps"] == {"match_history": False}
