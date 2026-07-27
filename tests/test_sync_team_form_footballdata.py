"""Teste pentru sync/sync_team_form_footballdata.py (R-Sync-3, ADR-039).

Fără rețea reală — mappings.FD_COMPETITIONS și FootballDataFormAdapter
sunt înlocuite cu fake-uri."""
from __future__ import annotations

from sync import sync_team_form_footballdata
from sync_orchestrator import SyncOrchestrator


class _FakeAdapter:
    provider_id = "footballdata"

    def __init__(self):
        self.persisted: list = []
        self.fetched_comp_codes: list = []

    def fetch(self, params):
        self.fetched_comp_codes.append(params["comp_code"])
        return {"comp_code": params["comp_code"]}

    def normalize(self, raw):
        return [{"team_name": f"Team-{raw['comp_code']}", "played": 1,
                  "goals_for": 1, "goals_against": 1, "form": "W"}] if raw else []

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
    runner = sync_team_form_footballdata._make_task_runner(adapter, "PL")
    runner()
    assert adapter.fetched_comp_codes == ["PL"]
    assert len(adapter.persisted) == 1
    assert adapter.persisted[0]["team_name"] == "Team-PL"


def test_run_registers_one_task_per_league_and_executes(monkeypatch):
    fake_competitions = {"Premier League": "PL", "La Liga": "PD"}
    monkeypatch.setattr("mappings.FD_COMPETITIONS", fake_competitions)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_team_form_footballdata, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_team_form_footballdata, "FootballDataFormAdapter", lambda: _FakeAdapter())

    results = sync_team_form_footballdata.run()
    assert len(results) == 2
    assert all(r.ran for r in results)


def test_run_registers_zero_tasks_when_no_competitions(monkeypatch):
    monkeypatch.setattr("mappings.FD_COMPETITIONS", {})

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_team_form_footballdata, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_team_form_footballdata, "FootballDataFormAdapter", lambda: _FakeAdapter())

    results = sync_team_form_footballdata.run()
    assert results == []
