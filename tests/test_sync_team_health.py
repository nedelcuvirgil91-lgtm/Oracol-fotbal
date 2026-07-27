"""Teste pentru sync/sync_team_health.py (R-Sync-2, ADR-039).

Fără rețea reală — FootballOracleAPI.get_matches_for_week() și
ApiFootballHealthAdapter sunt înlocuite cu fake-uri."""
from __future__ import annotations

from sync import sync_team_health
from sync_orchestrator import SyncOrchestrator


class _FakeOracleApi:
    def __init__(self, matches):
        self._matches = matches

    def get_matches_for_week(self, days_ahead=7, competitions=None):
        return self._matches


def test_teams_needing_sync_dedups_and_extracts_league(monkeypatch):
    matches = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "league": "Premier League"},
        {"home_team": "Liverpool", "away_team": "Arsenal", "league": "Premier League"},
    ]
    monkeypatch.setattr("oracle_api.FootballOracleAPI", lambda: _FakeOracleApi(matches))
    teams = sync_team_health._teams_needing_sync(days_ahead=2)
    names = {t["team_name"] for t in teams}
    assert names == {"Arsenal", "Chelsea", "Liverpool"}
    assert all(t["league"] == "Premier League" for t in teams)


def test_teams_needing_sync_empty_when_no_matches(monkeypatch):
    monkeypatch.setattr("oracle_api.FootballOracleAPI", lambda: _FakeOracleApi([]))
    assert sync_team_health._teams_needing_sync() == []


class _FakeAdapter:
    provider_id = "apifootball"

    def __init__(self, team_id=42):
        self._team_id = team_id
        self.persisted: list = []

    def resolve_team_id(self, team_name):
        return self._team_id

    def fetch(self, params):
        return {"team_name": params["team_name"], "injuries": [], "coaches": []}

    def normalize(self, raw):
        return [raw] if raw else []

    def validate(self, records):
        return records

    def persist(self, records):
        self.persisted.extend(records)
        return True


def test_task_runner_skips_when_team_id_unresolved():
    class _UnresolvableAdapter(_FakeAdapter):
        def resolve_team_id(self, team_name):
            return None

    adapter = _UnresolvableAdapter()
    runner = sync_team_health._make_task_runner(adapter, "Ghost FC", "Premier League", 2025)
    runner()  # nu trebuie sa arunce exceptie
    assert adapter.persisted == []


def test_task_runner_persists_when_team_id_resolved():
    adapter = _FakeAdapter()
    runner = sync_team_health._make_task_runner(adapter, "Arsenal", "Premier League", 2025)
    runner()
    assert len(adapter.persisted) == 1
    assert adapter.persisted[0]["team_name"] == "Arsenal"


def test_run_registers_one_task_per_team_and_executes(monkeypatch):
    matches = [{"home_team": "Arsenal", "away_team": "Chelsea", "league": "Premier League"}]
    monkeypatch.setattr("oracle_api.FootballOracleAPI", lambda: _FakeOracleApi(matches))

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_team_health, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_team_health, "ApiFootballHealthAdapter", lambda: _FakeAdapter())

    results = sync_team_health.run(days_ahead=2)
    assert len(results) == 2  # Arsenal + Chelsea
    assert all(r.ran for r in results)


class _AlwaysAllowRequestManager:
    def should_request(self, provider):
        return True
