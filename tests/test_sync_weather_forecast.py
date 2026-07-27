"""Teste pentru sync/sync_weather_forecast.py (R-Sync-5, ADR-039).

Fără rețea reală — FootballOracleAPI.get_matches_for_week() și
WeatherForecastAdapter sunt înlocuite cu fake-uri."""
from __future__ import annotations

from sync import sync_weather_forecast
from sync_orchestrator import SyncOrchestrator


class _FakeOracleApi:
    def __init__(self, matches):
        self._matches = matches

    def get_matches_for_week(self, days_ahead=7, competitions=None):
        return self._matches


def test_pairs_needing_sync_dedups_by_city_and_date(monkeypatch):
    matches = [
        {"venue_city": "London", "kickoff_date": "2026-08-01"},
        {"venue_city": "London", "kickoff_date": "2026-08-01"},  # duplicat
        {"venue_city": "Paris", "kickoff_date": "2026-08-02"},
    ]
    monkeypatch.setattr("oracle_api.FootballOracleAPI", lambda: _FakeOracleApi(matches))
    pairs = sync_weather_forecast._pairs_needing_sync(days_ahead=2)
    assert pairs == [("London", "2026-08-01"), ("Paris", "2026-08-02")]


def test_pairs_needing_sync_includes_empty_city_no_prefiltering(monkeypatch):
    """Nicio pre-filtrare aici — responsabilitatea validării e exclusiv a
    adaptorului (validate()), nu duplicată în scriptul de sync."""
    matches = [{"venue_city": "", "kickoff_date": "2026-08-01"}]
    monkeypatch.setattr("oracle_api.FootballOracleAPI", lambda: _FakeOracleApi(matches))
    pairs = sync_weather_forecast._pairs_needing_sync(days_ahead=2)
    assert pairs == [("", "2026-08-01")]


def test_pairs_needing_sync_empty_when_no_matches(monkeypatch):
    monkeypatch.setattr("oracle_api.FootballOracleAPI", lambda: _FakeOracleApi([]))
    assert sync_weather_forecast._pairs_needing_sync() == []


class _FakeAdapter:
    provider_id = "weatherapi"

    def __init__(self):
        self.persisted: list = []

    def fetch(self, params):
        return {"city": params["city"], "kickoff_date": params["kickoff_date"], "xg_penalty": 0.0}

    def normalize(self, raw):
        return [raw] if raw else []

    def validate(self, records):
        return [r for r in records if r.get("city")]

    def persist(self, records):
        self.persisted.extend(records)
        return True


class _AlwaysAllowRequestManager:
    def should_request(self, provider):
        return True


def test_task_runner_persists_valid_pair():
    adapter = _FakeAdapter()
    runner = sync_weather_forecast._make_task_runner(adapter, "London", "2026-08-01")
    runner()
    assert len(adapter.persisted) == 1
    assert adapter.persisted[0]["city"] == "London"


def test_task_runner_skips_pair_rejected_by_validate():
    adapter = _FakeAdapter()
    runner = sync_weather_forecast._make_task_runner(adapter, "", "2026-08-01")
    runner()
    assert adapter.persisted == []


def test_run_registers_one_task_per_pair_and_executes(monkeypatch):
    matches = [
        {"venue_city": "London", "kickoff_date": "2026-08-01"},
        {"venue_city": "Paris", "kickoff_date": "2026-08-02"},
    ]
    monkeypatch.setattr("oracle_api.FootballOracleAPI", lambda: _FakeOracleApi(matches))

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_weather_forecast, "get_sync_orchestrator", lambda: fake_orchestrator)
    monkeypatch.setattr(sync_weather_forecast, "WeatherForecastAdapter", lambda: _FakeAdapter())

    results = sync_weather_forecast.run(days_ahead=2)
    assert len(results) == 2
    assert all(r.ran for r in results)
