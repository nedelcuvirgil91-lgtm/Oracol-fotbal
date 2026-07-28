"""Teste pentru sync/sync_lineup_freelf.py (R-Sync-10, ADR-039).

Fără rețea reală — database.queries.get_upcoming_freelf_fixtures_for_lineup()
și FreelfLineupAdapter sunt înlocuite cu fake-uri."""
from __future__ import annotations

from sync import sync_lineup_freelf
from sync_orchestrator import SyncOrchestrator


class _FakeAdapter:
    provider_id = "freelivefootball"

    def __init__(self):
        self.persisted: list = []
        self.fetched: list = []

    def fetch(self, params):
        self.fetched.append((
            params["home_team_canonical"], params["away_team_canonical"],
            params["kickoff_date"], params["freelf_event_id"],
        ))
        return {"home_team_canonical": params["home_team_canonical"],
                "away_team_canonical": params["away_team_canonical"]}

    def normalize(self, raw):
        if not raw:
            return []
        return [{"home_team": raw["home_team_canonical"], "away_team": raw["away_team_canonical"]}]

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
    runner = sync_lineup_freelf._make_task_runner(adapter, "Arsenal", "Chelsea", "2026-08-01", "998877")
    runner()
    assert adapter.fetched == [("Arsenal", "Chelsea", "2026-08-01", "998877")]
    assert len(adapter.persisted) == 1
    assert adapter.persisted[0]["home_team"] == "Arsenal"


def test_run_registers_one_task_per_fixture_and_executes(monkeypatch):
    fake_fixtures = [
        {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
         "kickoff_date": "2026-08-01", "freelf_event_id": "1"},
        {"home_team_canonical": "Real Madrid", "away_team_canonical": "Barcelona",
         "kickoff_date": "2026-08-01", "freelf_event_id": "2"},
    ]
    monkeypatch.setattr(sync_lineup_freelf, "_fixtures_needing_sync", lambda window_minutes_ahead=240: fake_fixtures)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_lineup_freelf, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_lineup_freelf, "FreelfLineupAdapter", lambda: _FakeAdapter())

    results = sync_lineup_freelf.run()
    assert len(results) == 2
    assert all(r.ran for r in results)


def test_run_registers_zero_tasks_when_no_fixtures(monkeypatch):
    monkeypatch.setattr(sync_lineup_freelf, "_fixtures_needing_sync", lambda window_minutes_ahead=240: [])

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_lineup_freelf, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_lineup_freelf, "FreelfLineupAdapter", lambda: _FakeAdapter())

    results = sync_lineup_freelf.run()
    assert results == []


def test_fixtures_needing_sync_delegates_to_queries(monkeypatch):
    calls = []

    def _fake_get_upcoming(window_minutes_ahead):
        calls.append(window_minutes_ahead)
        return [{"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
                 "kickoff_date": "2026-08-01", "freelf_event_id": "1"}]

    monkeypatch.setattr("database.queries.get_upcoming_freelf_fixtures_for_lineup", _fake_get_upcoming)
    out = sync_lineup_freelf._fixtures_needing_sync(window_minutes_ahead=180)
    assert calls == [180]
    assert out[0]["freelf_event_id"] == "1"
