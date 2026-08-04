"""Teste pentru providers/flashscore/pre_match_odds.py — flux NOU, separat,
fara retea. Verifica exact frontiera cu discovery.py/normalizer.py
(reutilizare, nu duplicare) si garda critica: fetch-ul unui meci nejucat
atinge DOAR 2 taburi (summary + odds), niciodata cele 7 din adapter.py."""
from __future__ import annotations

from datetime import datetime

import pytest

from providers.flashscore.pre_match_odds import (
    _fetch_summary_and_odds,
    _within_window,
    discover_week_fixtures_with_odds,
    persist_week_odds,
    resolve_fixture_id,
    sync_week_odds_from_flashscore,
)


# ── _within_window — pura ───────────────────────────────────────────────────

def test_within_window_true_for_kickoff_in_range():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-06T18:00:00", days_ahead=7, now=now) is True


def test_within_window_false_for_kickoff_beyond_days_ahead():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-20T18:00:00", days_ahead=7, now=now) is False


def test_within_window_false_for_kickoff_in_the_past():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-01T18:00:00", days_ahead=7, now=now) is False


def test_within_window_false_for_missing_kickoff():
    assert _within_window(None, days_ahead=7) is False


def test_within_window_false_for_unparseable_kickoff():
    assert _within_window("not-a-date", days_ahead=7) is False


def test_within_window_true_at_exact_boundaries():
    now = datetime(2026, 8, 4, 12, 0, 0)
    assert _within_window("2026-08-04T12:00:00", days_ahead=7, now=now) is True
    assert _within_window("2026-08-11T12:00:00", days_ahead=7, now=now) is True


# ── resolve_fixture_id — pura ───────────────────────────────────────────────

def test_resolve_fixture_id_reuses_primary_source_fixture_id_on_match():
    record = {"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "mid": "abc123"}
    live_matches = [
        {"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "fixture_id": "odds_api_999"},
    ]
    assert resolve_fixture_id(record, live_matches) == "odds_api_999"


def test_resolve_fixture_id_mints_flashscore_id_when_no_primary_match():
    record = {"home_team": "Shamrock Rovers", "away_team": "Egnatia", "kickoff_date": "2026-08-10", "mid": "abc123"}
    assert resolve_fixture_id(record, live_matches=[]) == "flashscore_abc123"
    assert resolve_fixture_id(record, live_matches=None) == "flashscore_abc123"


def test_resolve_fixture_id_no_false_positive_on_different_date():
    record = {"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "mid": "abc123"}
    live_matches = [
        {"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-11", "fixture_id": "odds_api_999"},
    ]
    assert resolve_fixture_id(record, live_matches) == "flashscore_abc123"


# ── persist_week_odds — I/O mockuit ─────────────────────────────────────────

def test_persist_week_odds_writes_one_row_per_bookmaker(monkeypatch):
    written = []

    def _fake_upsert(fixture_id, bookmaker, home, draw, away):
        written.append((fixture_id, bookmaker, home, draw, away))
        return True

    monkeypatch.setattr("database.queries.upsert_odds_fallback_flashscore", _fake_upsert)

    records = [{
        "home_team": "A", "away_team": "B", "kickoff_date": "2026-08-10", "mid": "m1",
        "odds": [
            {"bookmaker": "bet365", "home": 1.5, "draw": 3.5, "away": 6.0, "source": "flashscore"},
            {"bookmaker": "Unibet", "home": 1.55, "draw": 3.4, "away": 5.8, "source": "flashscore"},
        ],
    }]
    report = persist_week_odds(records)

    assert report == {"matches_seen": 1, "odds_rows_written": 2, "odds_rows_failed": 0, "matches_without_odds": 0}
    assert written == [
        ("flashscore_m1", "bet365", 1.5, 3.5, 6.0),
        ("flashscore_m1", "Unibet", 1.55, 3.4, 5.8),
    ]


def test_persist_week_odds_counts_matches_without_any_odds_row():
    records = [{"home_team": "A", "away_team": "B", "kickoff_date": "2026-08-10", "mid": "m1", "odds": []}]
    report = persist_week_odds(records)
    assert report == {"matches_seen": 1, "odds_rows_written": 0, "odds_rows_failed": 0, "matches_without_odds": 1}


def test_persist_week_odds_counts_write_failures_separately(monkeypatch):
    monkeypatch.setattr("database.queries.upsert_odds_fallback_flashscore", lambda **kw: False)
    records = [{
        "home_team": "A", "away_team": "B", "kickoff_date": "2026-08-10", "mid": "m1",
        "odds": [{"bookmaker": "bet365", "home": 1.5, "draw": 3.5, "away": 6.0, "source": "flashscore"}],
    }]
    report = persist_week_odds(records)
    assert report["odds_rows_written"] == 0
    assert report["odds_rows_failed"] == 1


def test_persist_week_odds_uses_resolved_fixture_id_from_live_matches(monkeypatch):
    seen_fixture_ids = []
    monkeypatch.setattr(
        "database.queries.upsert_odds_fallback_flashscore",
        lambda fixture_id, bookmaker, home, draw, away: seen_fixture_ids.append(fixture_id) or True,
    )
    records = [{
        "home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "mid": "m1",
        "odds": [{"bookmaker": "bet365", "home": 1.5, "draw": 3.5, "away": 6.0, "source": "flashscore"}],
    }]
    live_matches = [{"home_team": "FC Botosani", "away_team": "Universitatea Cluj", "kickoff_date": "2026-08-10", "fixture_id": "odds_api_999"}]
    persist_week_odds(records, live_matches=live_matches)
    assert seen_fixture_ids == ["odds_api_999"]


# ── discover_week_fixtures_with_odds — validare fara retea ────────────────

def test_discover_week_fixtures_rejects_unknown_league():
    with pytest.raises(ValueError, match="fara slug Flashscore verificat live"):
        discover_week_fixtures_with_odds(leagues=["Liga Necunoscuta"])


# ── _fetch_summary_and_odds — garda critica: DOAR 2 taburi, nu 7 ───────────

class _FakeResponse:
    def __init__(self, status=200):
        self.status = status


class _FakeLightPage:
    """Fake Playwright page — inregistreaza fiecare URL vizitat, ca sa se
    poata verifica exact ce taburi au fost cerute."""
    def __init__(self):
        self.urls_visited: list[str] = []

    def goto(self, url, wait_until=None, timeout=None):
        self.urls_visited.append(url)
        return _FakeResponse()

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return "<html><body>fake</body></html>"


def test_fetch_summary_and_odds_visits_exactly_two_tabs_not_seven():
    page = _FakeLightPage()
    pages = _fetch_summary_and_odds(page, "https://www.flashscore.com/match/football/x", "mid123")

    assert set(pages.keys()) == {"summary", "odds"}
    assert len(page.urls_visited) == 2
    assert page.urls_visited[0] == "https://www.flashscore.com/match/football/x/?mid=mid123"
    assert page.urls_visited[1] == "https://www.flashscore.com/match/football/x/odds/?mid=mid123"
    # nu apar niciodata taburile "grele" (stats/lineups/player-stats/h2h/standings)
    for forbidden in ("stats", "lineups", "player-stats", "h2h", "standings"):
        assert not any(forbidden in u for u in page.urls_visited)


# ── sync_week_odds_from_flashscore — orchestrare ───────────────────────────

def test_sync_week_odds_from_flashscore_wires_discover_and_persist(monkeypatch):
    fake_records = [{
        "league": "Europa League", "home_team": "A", "away_team": "B",
        "kickoff_date": "2026-08-10", "mid": "m1", "odds": [],
    }]
    monkeypatch.setattr(
        "providers.flashscore.pre_match_odds.discover_week_fixtures_with_odds",
        lambda leagues, days_ahead, limit_per_league: fake_records,
    )
    report = sync_week_odds_from_flashscore(leagues=["Europa League"], days_ahead=7)
    assert report["matches_seen"] == 1
    assert report["leagues"] == ["Europa League"]
    assert report["days_ahead"] == 7
