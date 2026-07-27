"""Teste pentru sync/sync_match_statistics.py (Sprint 1, ADR-039). Fără
rețea — database.queries.get_finished_matches_missing_stats() și
MatchStatisticsAdapter sunt fake-uite. Tipar identic cu
tests/test_sync_team_health.py."""
from __future__ import annotations

from sync import sync_match_statistics
from sync_orchestrator import SyncOrchestrator


class _AlwaysAllowRequestManager:
    def should_request(self, provider):
        return True


class _FakeAdapter:
    provider_id = "freelivefootball"

    def __init__(self, raw_by_match=None):
        self._raw_by_match = raw_by_match or {}
        self.persisted: list = []
        self.fetch_calls: list = []

    def fetch(self, params):
        self.fetch_calls.append(params)
        key = (params["home_team"], params["away_team"], params["kickoff_date"])
        return self._raw_by_match.get(key)

    def normalize(self, raw):
        return [raw] if raw else []

    def validate(self, records):
        return records

    def persist(self, records):
        self.persisted.extend(records)
        return True


def test_matches_missing_stats_delegates_to_query(monkeypatch):
    rows = [{"home_team": "Arsenal", "away_team": "Chelsea",
             "kickoff_date": "2026-01-01", "league": "Premier League"}]
    monkeypatch.setattr("database.queries.get_finished_matches_missing_stats",
                         lambda days_back: rows)
    result = sync_match_statistics._matches_missing_stats(days_back=3)
    assert result == rows


def test_task_runner_skips_when_no_stats_found():
    adapter = _FakeAdapter(raw_by_match={})
    match = {"home_team": "Arsenal", "away_team": "Chelsea",
             "kickoff_date": "2026-01-01", "league": "Premier League"}
    runner = sync_match_statistics._make_task_runner(adapter, match)
    runner()  # nu trebuie sa arunce exceptie
    assert adapter.persisted == []


def test_task_runner_persists_when_stats_found():
    key = ("Arsenal", "Chelsea", "2026-01-01")
    adapter = _FakeAdapter(raw_by_match={key: {"home_possession": 55.0}})
    match = {"home_team": "Arsenal", "away_team": "Chelsea",
             "kickoff_date": "2026-01-01", "league": "Premier League"}
    runner = sync_match_statistics._make_task_runner(adapter, match)
    runner()
    assert len(adapter.persisted) == 1


def test_run_registers_one_task_per_match_and_executes(monkeypatch):
    matches = [
        {"home_team": "Arsenal", "away_team": "Chelsea",
         "kickoff_date": "2026-01-01", "league": "Premier League"},
        {"home_team": "Liverpool", "away_team": "Everton",
         "kickoff_date": "2026-01-02", "league": "Premier League"},
    ]
    monkeypatch.setattr(sync_match_statistics, "_matches_missing_stats", lambda days_back: matches)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_match_statistics, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_match_statistics, "MatchStatisticsAdapter", lambda: _FakeAdapter())

    results = sync_match_statistics.run(days_back=2)
    assert len(results) == 2
    assert all(r.ran for r in results)


def test_run_with_zero_matches_registers_nothing(monkeypatch):
    monkeypatch.setattr(sync_match_statistics, "_matches_missing_stats", lambda days_back: [])
    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_match_statistics, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_match_statistics, "MatchStatisticsAdapter", lambda: _FakeAdapter())

    results = sync_match_statistics.run(days_back=2)
    assert results == []
