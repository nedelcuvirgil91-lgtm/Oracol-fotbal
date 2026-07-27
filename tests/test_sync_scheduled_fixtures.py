"""Teste pentru sync/sync_scheduled_fixtures.py (R-Sync-7a, ADR-039) —
verifică orchestrarea (câte task-uri per provider, cu ce parametri), fără
rețea reală — toți cei 6 adaptori sunt înlocuiți cu fake-uri."""
from __future__ import annotations

from sync import sync_scheduled_fixtures
from sync_orchestrator import SyncOrchestrator


class _FakeAdapter:
    def __init__(self, provider_id):
        self.provider_id = provider_id
        self.fetch_calls: list = []
        self.persisted: list = []

    def fetch(self, params):
        self.fetch_calls.append(params)
        return [{"marker": params}]

    def normalize(self, raw):
        return [{"home_team": "A", "away_team": "B", "kickoff_date": "2026-08-01"}] if raw else []

    def validate(self, records):
        return records

    def persist(self, records):
        self.persisted.extend(records)
        return True


class _AlwaysAllowRequestManager:
    def should_request(self, provider):
        return True


def _patch_all_adapters(monkeypatch, fakes: dict):
    monkeypatch.setattr(sync_scheduled_fixtures, "OddsApiFixtureAdapter", lambda: fakes["oddsapi"])
    monkeypatch.setattr(sync_scheduled_fixtures, "FreeLfFixtureAdapter", lambda: fakes["freelf"])
    monkeypatch.setattr(sync_scheduled_fixtures, "FootballDataFixtureAdapter", lambda: fakes["fd"])
    monkeypatch.setattr(sync_scheduled_fixtures, "EspnFixtureAdapter", lambda: fakes["espn"])
    monkeypatch.setattr(sync_scheduled_fixtures, "TsdbFixtureAdapter", lambda: fakes["tsdb"])
    monkeypatch.setattr(sync_scheduled_fixtures, "ApiFootballFixtureAdapter", lambda: fakes["apifootball"])


def test_run_registers_tasks_for_all_six_providers(monkeypatch):
    monkeypatch.setattr("mappings.ODDS_SPORT_KEYS", {"Premier League": "soccer_epl"})
    monkeypatch.setattr("mappings.FREE_LF_LEAGUE_IDS", {"Premier League": 1})
    monkeypatch.setattr("mappings.FD_COMPETITIONS", {"Premier League": "PL"})
    monkeypatch.setattr("mappings.ESPN_LEAGUE_SLUGS", {"Premier League": "eng.1"})
    monkeypatch.setattr("mappings.TSDB_LEAGUE_IDS", {"Premier League": "4328"})
    monkeypatch.setattr("mappings.API_FOOTBALL_LEAGUE_IDS", {"Premier League": 39})

    fakes = {
        "oddsapi": _FakeAdapter("oddsapi"), "freelf": _FakeAdapter("freelf"),
        "fd": _FakeAdapter("fd"), "espn": _FakeAdapter("espn"),
        "tsdb": _FakeAdapter("tsdb"), "apifootball": _FakeAdapter("apifootball"),
    }
    _patch_all_adapters(monkeypatch, fakes)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_scheduled_fixtures, "get_sync_orchestrator", lambda: fake_orchestrator)

    results = sync_scheduled_fixtures.run(days_ahead=2)

    assert all(r.ran for r in results)
    # oddsapi: 1 task (per liga, nu per zi)
    assert len(fakes["oddsapi"].fetch_calls) == 1
    assert fakes["oddsapi"].fetch_calls[0] == {"sport_key": "soccer_epl", "days_ahead": 2}
    # freelf: 1 task per (liga, zi) -> min(2,7)=2 zile x 1 liga = 2
    assert len(fakes["freelf"].fetch_calls) == 2
    # fd: un singur task, toate ligile deodata
    assert len(fakes["fd"].fetch_calls) == 1
    assert fakes["fd"].fetch_calls[0]["comp_codes"] == ["PL"]
    # espn: 1 task per (liga, zi) -> 2
    assert len(fakes["espn"].fetch_calls) == 2
    # tsdb: 1 task per liga (nu per zi)
    assert len(fakes["tsdb"].fetch_calls) == 1
    # apifootball: 1 task per liga
    assert len(fakes["apifootball"].fetch_calls) == 1


def test_run_registers_zero_tasks_when_no_leagues_configured(monkeypatch):
    for name in ("ODDS_SPORT_KEYS", "FREE_LF_LEAGUE_IDS", "FD_COMPETITIONS",
                 "ESPN_LEAGUE_SLUGS", "TSDB_LEAGUE_IDS", "API_FOOTBALL_LEAGUE_IDS"):
        monkeypatch.setattr(f"mappings.{name}", {})

    fakes = {k: _FakeAdapter(k) for k in ("oddsapi", "freelf", "fd", "espn", "tsdb", "apifootball")}
    _patch_all_adapters(monkeypatch, fakes)

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_scheduled_fixtures, "get_sync_orchestrator", lambda: fake_orchestrator)

    results = sync_scheduled_fixtures.run(days_ahead=2)

    # fd inregistreaza mereu 1 task (chiar cu comp_codes=None), restul 0
    assert len(fakes["oddsapi"].fetch_calls) == 0
    assert len(fakes["freelf"].fetch_calls) == 0
    assert len(fakes["fd"].fetch_calls) == 1
    assert fakes["fd"].fetch_calls[0]["comp_codes"] is None
    assert len(fakes["espn"].fetch_calls) == 0
    assert len(fakes["tsdb"].fetch_calls) == 0
    assert len(fakes["apifootball"].fetch_calls) == 0
