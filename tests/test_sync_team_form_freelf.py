"""Teste pentru sync/sync_team_form_freelf.py (R-Sync-6, ADR-039)."""
from __future__ import annotations

from sync import sync_team_form_freelf
from sync_orchestrator import SyncOrchestrator


class _FakeAdapter:
    provider_id = "freelivefootball"

    def __init__(self):
        self.persisted: list = []
        self.fetched_leagues: list = []

    def fetch(self, params):
        self.fetched_leagues.append(params["league"])
        return [{"team": params["league"]}]

    def normalize(self, raw):
        return [{"team_name": f"Team-{r['team']}", "played": 1, "wins": 1, "draws": 0,
                  "losses": 0, "goals_for": 1, "goals_against": 0, "points": 3,
                  "position": 1, "form": ""} for r in raw] if raw else []

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
    runner = sync_team_form_freelf._make_task_runner(adapter, "Premier League")
    runner()
    assert adapter.fetched_leagues == ["Premier League"]
    assert len(adapter.persisted) == 1
    assert adapter.persisted[0]["team_name"] == "Team-Premier League"


def test_run_registers_one_task_per_league_and_executes(monkeypatch):
    fake_leagues = {"Premier League": 1, "La Liga": 2}
    monkeypatch.setattr("mappings.FREE_LF_LEAGUE_IDS", fake_leagues)
    monkeypatch.setattr("database.queries.get_flashscore_covered_standings_leagues", lambda: set())

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_team_form_freelf, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_team_form_freelf, "FreeLfFormAdapter", lambda: _FakeAdapter())

    results = sync_team_form_freelf.run()
    assert len(results) == 2
    assert all(r.ran for r in results)


def test_run_registers_zero_tasks_when_no_leagues(monkeypatch):
    monkeypatch.setattr("mappings.FREE_LF_LEAGUE_IDS", {})
    monkeypatch.setattr("database.queries.get_flashscore_covered_standings_leagues", lambda: set())

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_team_form_freelf, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_team_form_freelf, "FreeLfFormAdapter", lambda: _FakeAdapter())

    assert sync_team_form_freelf.run() == []


def test_run_skips_league_already_covered_by_flashscore(monkeypatch):
    """[ADAUGAT Pasul 1 Master Repair Plan, ADR-045 — Single Owner]"""
    fake_leagues = {"Premier League": 1, "La Liga": 2}
    monkeypatch.setattr("mappings.FREE_LF_LEAGUE_IDS", fake_leagues)
    monkeypatch.setattr("database.queries.get_flashscore_covered_standings_leagues", lambda: {"Premier League"})

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_team_form_freelf, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_team_form_freelf, "FreeLfFormAdapter", lambda: _FakeAdapter())

    results = sync_team_form_freelf.run()
    assert len(results) == 1
    assert "La Liga" in results[0].task_name
