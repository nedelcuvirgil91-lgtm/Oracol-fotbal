"""Teste pentru sync/sync_h2h_freelf.py (R-Sync-9, ADR-039).

Fără rețea reală — database.queries.get_freelf_fixtures_needing_h2h() și
FreelfH2hAdapter sunt înlocuite cu fake-uri."""
from __future__ import annotations

from sync import sync_h2h_freelf
from sync_orchestrator import SyncOrchestrator


class _FakeAdapter:
    provider_id = "freelivefootball"

    def __init__(self):
        self.persisted: list = []
        self.fetched: list = []

    def fetch(self, params):
        self.fetched.append((
            params["home_team_canonical"], params["away_team_canonical"], params["freelf_event_id"],
        ))
        return {
            "home_team_canonical": params["home_team_canonical"],
            "away_team_canonical": params["away_team_canonical"],
            "freelf_event_id": params["freelf_event_id"],
            "h2h": {"meetings": 1, "home_wins": 1, "draws": 0, "away_wins": 0,
                    "home_goals_avg": 1.0, "away_goals_avg": 0.0, "last_5": ["H"],
                    "h2h_modifier": 0.05, "summary": ""},
        }

    def normalize(self, raw):
        if not raw:
            return []
        return [{"home_team": raw["home_team_canonical"], "away_team": raw["away_team_canonical"],
                 "freelf_event_id": raw["freelf_event_id"], **raw["h2h"]}]

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
    runner = sync_h2h_freelf._make_task_runner(adapter, "Arsenal", "Chelsea", "998877")
    runner()
    assert adapter.fetched == [("Arsenal", "Chelsea", "998877")]
    assert len(adapter.persisted) == 1
    assert adapter.persisted[0]["home_team"] == "Arsenal"


def test_run_registers_one_task_per_fixture_and_executes(monkeypatch):
    fake_fixtures = [
        {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea", "freelf_event_id": "1"},
        {"home_team_canonical": "Real Madrid", "away_team_canonical": "Barcelona", "freelf_event_id": "2"},
    ]
    monkeypatch.setattr(sync_h2h_freelf, "_fixtures_needing_sync", lambda days_ahead=14: fake_fixtures)
    monkeypatch.setattr(sync_h2h_freelf, "_already_has_flashscore_h2h", lambda home, away: False)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_h2h_freelf, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_h2h_freelf, "FreelfH2hAdapter", lambda: _FakeAdapter())

    results = sync_h2h_freelf.run()
    assert len(results) == 2
    assert all(r.ran for r in results)


def test_run_registers_zero_tasks_when_no_fixtures(monkeypatch):
    monkeypatch.setattr(sync_h2h_freelf, "_fixtures_needing_sync", lambda days_ahead=14: [])
    monkeypatch.setattr(sync_h2h_freelf, "_already_has_flashscore_h2h", lambda home, away: False)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_h2h_freelf, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_h2h_freelf, "FreelfH2hAdapter", lambda: _FakeAdapter())

    results = sync_h2h_freelf.run()
    assert results == []


def test_run_skips_fixture_when_flashscore_already_has_h2h(monkeypatch):
    """[ADAUGAT Pasul 1 Master Repair Plan, ADR-045 — Single Owner] Daca
    Flashscore are deja context H2H complet pentru o pereche, FreeLF NU mai
    e interogat pentru ea — dar restul perechilor raman neschimbate."""
    fake_fixtures = [
        {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea", "freelf_event_id": "1"},
        {"home_team_canonical": "Real Madrid", "away_team_canonical": "Barcelona", "freelf_event_id": "2"},
    ]
    monkeypatch.setattr(sync_h2h_freelf, "_fixtures_needing_sync", lambda days_ahead=14: fake_fixtures)
    monkeypatch.setattr(
        sync_h2h_freelf, "_already_has_flashscore_h2h",
        lambda home, away: (home, away) == ("Arsenal", "Chelsea"),
    )

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_h2h_freelf, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_h2h_freelf, "FreelfH2hAdapter", lambda: _FakeAdapter())

    results = sync_h2h_freelf.run()
    assert len(results) == 1
    assert "Real Madrid" in results[0].task_name


def test_already_has_flashscore_h2h_delegates_to_queries(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "database.queries.has_flashscore_h2h_context",
        lambda home, away: (calls.append((home, away)), True)[1],
    )
    assert sync_h2h_freelf._already_has_flashscore_h2h("Arsenal", "Chelsea") is True
    assert calls == [("Arsenal", "Chelsea")]


def test_fixtures_needing_sync_delegates_to_queries(monkeypatch):
    calls = []

    def _fake_get_freelf_fixtures_needing_h2h(days_ahead):
        calls.append(days_ahead)
        return [{"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea", "freelf_event_id": "1"}]

    monkeypatch.setattr("database.queries.get_freelf_fixtures_needing_h2h", _fake_get_freelf_fixtures_needing_h2h)
    out = sync_h2h_freelf._fixtures_needing_sync(days_ahead=7)
    assert calls == [7]
    assert out == [{"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea", "freelf_event_id": "1"}]
