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
    _raw_snapshot_by_tab,
    compute_data_completeness,
    persist_match_foundation_data,
    persist_match_with_data_trust_layer,
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
    events_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_events", events_mock)
    standings_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_standings_snapshot", standings_mock)

    report = persist_match_foundation_data(full_tabs_pages, competition="SuperLiga")

    assert report["match_id"] == 123
    assert report["ok"] is True
    assert report["steps"] == {
        "match_history": True, "match_statistics_extended": True, "player_roster": True,
        "player_match_stats_extended": True, "match_context": True, "match_events": True,
        "standings_snapshot": True,
    }
    assert "match_history" in calls

    # 21 evenimente reale (timeline complet Summary) propagate cu match_id corect.
    assert events_mock.call_args[0][0] == 123
    assert len(events_mock.call_args[0][1]) == 21

    # match_id (123) propagat corect la statisticile extinse.
    extended_call_args = extended_mock.call_args
    assert extended_call_args[0][0] == 123
    # join name<->echipa aplicat inaintea scrierii - Pop A. e in roster (home).
    joined_rows = extended_call_args[0][1]
    pop = next(r for r in joined_rows if r["player_name"] == "Pop A.")
    assert pop["team"] == "home"

    # standings scris doar cand se da o competitie.
    assert standings_mock.call_args[0][0][0]["competition"] == "SuperLiga"


def test_persist_match_foundation_data_propagates_season_when_provided(monkeypatch, full_tabs_pages):
    """[TASK APROBAT M1, Raspuns oficial] season se propaga uniform la
    toate scrierile FK-dependente ale meciului - NU e derivat aici, doar
    transmis de la apelant (Flashscore nu il ofera robust azi, verificat
    pe fixture - vezi normalize_odds/normalize_match_context docstrings)."""
    match_history_mock = MagicMock(return_value=123)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", match_history_mock)
    extended_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_statistics_extended", extended_mock)
    roster_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_roster", roster_mock)
    player_ext_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_match_stats_extended", player_ext_mock)
    context_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_context", context_mock)
    events_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_events", events_mock)
    standings_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_standings_snapshot", standings_mock)

    persist_match_foundation_data(full_tabs_pages, competition="SuperLiga", season="2026-2027")

    assert match_history_mock.call_args[0][0]["season"] == "2026-2027"
    assert all(r["season"] == "2026-2027" for r in extended_mock.call_args[0][1])
    assert roster_mock.call_args[1]["season"] == "2026-2027"
    assert player_ext_mock.call_args[1]["season"] == "2026-2027"
    assert all(r["season"] == "2026-2027" for r in context_mock.call_args[0][0])
    assert events_mock.call_args[1]["season"] == "2026-2027"
    assert all(r["season"] == "2026-2027" for r in standings_mock.call_args[0][0])


def test_persist_match_foundation_data_propagates_league_when_provided(monkeypatch, full_tabs_pages):
    """[FIX live, gasit la al treilea run live real] match_history.league
    e NOT NULL - orice meci nou descoperit de Flashscore Discovery esua
    la INSERT fara el. NU se deriva din pagina Flashscore aici - doar
    transmis de la apelant (Discovery deja stie liga urmarita)."""
    match_history_mock = MagicMock(return_value=123)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", match_history_mock)
    for fn in (
        "upsert_match_statistics_extended", "upsert_player_roster",
        "upsert_player_match_stats_extended", "upsert_match_context",
        "upsert_match_events", "upsert_standings_snapshot",
    ):
        monkeypatch.setattr(f"providers.flashscore.persistence.{fn}", MagicMock(return_value=True))

    persist_match_foundation_data(full_tabs_pages, league="Romania SuperLiga")

    assert match_history_mock.call_args[0][0]["league"] == "Romania SuperLiga"


def test_persist_match_foundation_data_no_competition_skips_standings(monkeypatch, full_tabs_pages):
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", lambda *a, **kw: 123)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_statistics_extended", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_roster", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_player_match_stats_extended", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_context", lambda *a, **kw: True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_events", lambda *a, **kw: True)
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
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_events", lambda *a, **kw: True)
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


# ════════════════════════════════════════════════════════════════════════
# Data Trust Layer: RAW -> VALIDATED -> CANONICAL
# ════════════════════════════════════════════════════════════════════════

def test_raw_snapshot_by_tab_has_no_match_id_yet(full_tabs_pages):
    """RAW e independent de rezolvarea canonica - context_match_id ramane
    None in snapshot, nu aproximat (North Star #8)."""
    snap = _raw_snapshot_by_tab(full_tabs_pages, competition="SuperLiga")
    assert set(snap) == {"stats", "events", "player_stats", "h2h", "standings", "odds"}
    assert snap["h2h"][0]["context_match_id"] is None
    assert snap["stats"]["home_team"] == "Dinamo Bucuresti"
    assert len(snap["odds"]) == 3
    assert len(snap["events"]) == 21


def test_raw_snapshot_by_tab_skips_standings_without_competition(full_tabs_pages):
    snap = _raw_snapshot_by_tab(full_tabs_pages, competition=None)
    assert "standings" not in snap


def test_data_trust_layer_valid_record_writes_raw_and_canonical(monkeypatch, full_tabs_pages):
    raw_calls: list = []
    monkeypatch.setattr(
        "providers.flashscore.persistence.upsert_raw_extraction",
        lambda match_ref, tab_name, raw, **kw: raw_calls.append((match_ref, tab_name, kw)) or True,
    )
    monkeypatch.setattr(
        "providers.flashscore.persistence.persist_match_foundation_data",
        lambda pages, competition=None, season=None, league=None: {"match_id": 123, "ok": True, "steps": {"match_history": True}},
    )
    completeness_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_data_completeness", completeness_mock)

    report = persist_match_with_data_trust_layer(full_tabs_pages, match_ref="dinamo_craiova_2026-07-25",
                                                  competition="SuperLiga")

    assert report["validation_status"] == "valid"
    assert report["validation_errors"] is None
    assert report["match_id"] == 123
    assert report["ok"] is True
    # RAW scris pentru toate cele 6 categorii disponibile (stats/events/player_stats/h2h/standings/odds).
    tab_names = {c[1] for c in raw_calls}
    assert tab_names == {"stats", "events", "player_stats", "h2h", "standings", "odds"}
    for _, _, kw in raw_calls:
        assert kw["validation_status"] == "valid"
        assert kw["canonical_written"] is True

    # Data Completeness Score calculat si scris cu match_id-ul rezolvat.
    completeness_mock.assert_called_once()
    call_args = completeness_mock.call_args[0]
    assert call_args[0] == "dinamo_craiova_2026-07-25"
    assert call_args[1] == 123
    assert call_args[2]["coverage_percent"] == 100.0


def test_data_trust_layer_invalid_record_skips_canonical_but_writes_raw(monkeypatch):
    raw_calls: list = []
    monkeypatch.setattr(
        "providers.flashscore.persistence.upsert_raw_extraction",
        lambda match_ref, tab_name, raw, **kw: raw_calls.append((match_ref, tab_name, kw)) or True,
    )
    canonical_mock = MagicMock()
    monkeypatch.setattr("providers.flashscore.persistence.persist_match_foundation_data", canonical_mock)
    completeness_mock = MagicMock(return_value=True)
    monkeypatch.setattr("providers.flashscore.persistence.upsert_data_completeness", completeness_mock)

    # pages fara continut util -> normalize_match_statistics() intoarce {} ->
    # fara cheie naturala -> validare esueaza.
    report = persist_match_with_data_trust_layer({}, match_ref="ref-invalid", competition=None)

    assert report["validation_status"] == "rejected"
    assert report["validation_errors"] == ["missing_natural_key"]
    assert report["ok"] is False
    canonical_mock.assert_not_called()
    # RAW tot se scrie - "nu exista bypass", dar dovada exista chiar si pentru respins.
    assert len(raw_calls) >= 1
    for _, _, kw in raw_calls:
        assert kw["validation_status"] == "rejected"
        assert kw["canonical_written"] is False

    # Completeness se calculeaza si se scrie chiar si pentru meci respins
    # (e o proprietate a colectarii, nu a validarii) - dar cu match_id=None
    # (nicio scriere canonica nu a avut loc).
    completeness_mock.assert_called_once()
    call_args = completeness_mock.call_args[0]
    assert call_args[1] is None
    assert call_args[2]["coverage_percent"] == 0.0


# ════════════════════════════════════════════════════════════════════════
# compute_data_completeness — regula 7, TASK APROBAT M1
# ════════════════════════════════════════════════════════════════════════

def test_compute_data_completeness_full_coverage(full_tabs_pages):
    score = compute_data_completeness(full_tabs_pages)
    assert score["coverage_percent"] == 100.0
    for tab in ("summary", "stats", "lineups", "player_stats", "odds", "h2h", "standings"):
        assert score[tab] is True


def test_compute_data_completeness_partial_coverage():
    pages = {"summary": "<html>x</html>", "stats": "<html>y</html>"}
    score = compute_data_completeness(pages)
    assert score["summary"] is True
    assert score["stats"] is True
    assert score["lineups"] is False
    assert score["odds"] is False
    assert score["coverage_percent"] == round(100.0 * 2 / 7, 2)


def test_compute_data_completeness_empty_pages():
    score = compute_data_completeness({})
    assert score["coverage_percent"] == 0.0
    assert all(score[tab] is False for tab in
               ("summary", "stats", "lineups", "player_stats", "odds", "h2h", "standings"))
