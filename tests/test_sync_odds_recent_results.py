"""Teste pentru sync/sync_odds_recent_results.py (R-Sync-6, ADR-039)."""
from __future__ import annotations

from sync import sync_odds_recent_results
from sync_orchestrator import SyncOrchestrator


class _FakeAdapter:
    provider_id = "oddsapi"

    def __init__(self):
        self.persisted: list = []
        self.fetched_sport_keys: list = []

    def fetch(self, params):
        self.fetched_sport_keys.append(params["sport_key"])
        return [{"sport_key": params["sport_key"]}]

    def normalize(self, raw):
        return [{"home_team": f"Team-{r['sport_key']}", "away_team": "Opponent",
                  "kickoff_date": "2026-08-01", "league": "", "home_score": 1, "away_score": 0}
                for r in raw] if raw else []

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
    runner = sync_odds_recent_results._make_task_runner(adapter, "soccer_epl")
    runner()
    assert adapter.fetched_sport_keys == ["soccer_epl"]
    assert len(adapter.persisted) == 1
    assert adapter.persisted[0]["home_team"] == "Team-soccer_epl"


def test_run_registers_one_task_per_league_and_executes(monkeypatch):
    fake_sport_keys = {"Premier League": "soccer_epl", "La Liga": "soccer_spain_la_liga"}
    monkeypatch.setattr("mappings.ODDS_SPORT_KEYS", fake_sport_keys)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_odds_recent_results, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_odds_recent_results, "OddsApiRecentResultsAdapter", lambda: _FakeAdapter())

    results = sync_odds_recent_results.run()
    assert len(results) == 2
    assert all(r.ran for r in results)


def test_run_registers_zero_tasks_when_no_leagues(monkeypatch):
    monkeypatch.setattr("mappings.ODDS_SPORT_KEYS", {})

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_odds_recent_results, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_odds_recent_results, "OddsApiRecentResultsAdapter", lambda: _FakeAdapter())

    assert sync_odds_recent_results.run() == []
