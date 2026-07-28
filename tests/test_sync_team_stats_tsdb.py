"""Teste pentru sync/sync_team_stats_tsdb.py (R-Sync-8, ADR-039).

Fără rețea reală — database.queries.get_teams_with_tsdb_id() și
TsdbTeamStatsAdapter sunt înlocuite cu fake-uri."""
from __future__ import annotations

from sync import sync_team_stats_tsdb
from sync_orchestrator import SyncOrchestrator


class _FakeAdapter:
    provider_id = "thesportsdb"

    def __init__(self):
        self.persisted: list = []
        self.fetched: list = []

    def fetch(self, params):
        self.fetched.append((params["team_name_canonical"], params["tsdb_team_id"]))
        return {"team_name_canonical": params["team_name_canonical"],
                "tsdb_team_id": params["tsdb_team_id"], "events": [{"result": "W"}]}

    def normalize(self, raw):
        return [{"team_name": raw["team_name_canonical"],
                  "tsdb_team_id": raw["tsdb_team_id"], "events": raw["events"]}] if raw else []

    def validate(self, records):
        return records

    def persist(self, records):
        self.persisted.extend(records)
        return True


class _AlwaysAllowRequestManager:
    def should_request(self, provider):
        return True


def test_task_runner_fetches_normalizes_validates_persists():
    adapter = _FakeAdapter()
    runner = sync_team_stats_tsdb._make_task_runner(adapter, "Arsenal", "tsdb_133604")
    runner()
    assert adapter.fetched == [("Arsenal", "tsdb_133604")]
    assert len(adapter.persisted) == 1
    assert adapter.persisted[0]["team_name"] == "Arsenal"


def test_run_registers_one_task_per_team_and_executes(monkeypatch):
    fake_teams = [
        {"team_name": "Arsenal", "tsdb_team_id": "tsdb_1"},
        {"team_name": "Chelsea", "tsdb_team_id": "tsdb_2"},
    ]
    monkeypatch.setattr(sync_team_stats_tsdb, "_teams_needing_sync", lambda days_ahead=14: fake_teams)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_team_stats_tsdb, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_team_stats_tsdb, "TsdbTeamStatsAdapter", lambda: _FakeAdapter())

    results = sync_team_stats_tsdb.run()
    assert len(results) == 2
    assert all(r.ran for r in results)


def test_run_registers_zero_tasks_when_no_teams(monkeypatch):
    monkeypatch.setattr(sync_team_stats_tsdb, "_teams_needing_sync", lambda days_ahead=14: [])

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_team_stats_tsdb, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_team_stats_tsdb, "TsdbTeamStatsAdapter", lambda: _FakeAdapter())

    results = sync_team_stats_tsdb.run()
    assert results == []


def test_teams_needing_sync_delegates_to_queries(monkeypatch):
    calls = []

    def _fake_get_teams_with_tsdb_id(days_ahead):
        calls.append(days_ahead)
        return [{"team_name": "Arsenal", "tsdb_team_id": "tsdb_1"}]

    monkeypatch.setattr("database.queries.get_teams_with_tsdb_id", _fake_get_teams_with_tsdb_id)
    out = sync_team_stats_tsdb._teams_needing_sync(days_ahead=7)
    assert calls == [7]
    assert out == [{"team_name": "Arsenal", "tsdb_team_id": "tsdb_1"}]
