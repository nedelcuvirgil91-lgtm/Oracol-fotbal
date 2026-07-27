"""Teste pentru sync/sync_national_team_elo.py (R-Sync-4, ADR-039).

Fără rețea reală — EloRatingsAdapter e înlocuit cu un fake. Un singur
SyncTask, spre deosebire de sync_team_health.py (per echipă) sau
sync_team_form_footballdata.py (per ligă)."""
from __future__ import annotations

from sync import sync_national_team_elo
from sync_orchestrator import SyncOrchestrator


class _FakeAdapter:
    provider_id = "eloratings"

    def __init__(self):
        self.persisted: list = []
        self.fetch_calls = 0

    def fetch(self, params):
        self.fetch_calls += 1
        return {"France": 2085, "Brazil": 2050}

    def normalize(self, raw):
        return [{"team_name": k, "elo_rating": v} for k, v in raw.items()] if raw else []

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
    runner = sync_national_team_elo._make_task_runner(adapter)
    runner()
    assert adapter.fetch_calls == 1
    assert len(adapter.persisted) == 2
    names = {r["team_name"] for r in adapter.persisted}
    assert names == {"France", "Brazil"}


def test_run_registers_exactly_one_task_and_executes(monkeypatch):
    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_national_team_elo, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_national_team_elo, "EloRatingsAdapter", lambda: _FakeAdapter())

    results = sync_national_team_elo.run()
    assert len(results) == 1
    assert results[0].ran
    assert results[0].task_name == "national_team_elo"
