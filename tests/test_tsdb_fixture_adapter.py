"""Teste pentru tsdb_fixture_adapter.py (R-Sync-7a, ADR-039)."""
from __future__ import annotations

from tsdb_fixture_adapter import TsdbFixtureAdapter

_RAW = [{
    "fixture_id": "tsdb_1", "home_team": "Arsenal", "away_team": "Chelsea",
    "home_team_id": "tsdb_133604", "away_team_id": "tsdb_133610",
    "kickoff_utc": "2026-08-01T15:00:00Z", "kickoff_date": "2026-08-01",
    "league": "Premier League", "venue_city": "", "status": "scheduled",
    "source": "thesportsdb",
}]


class _FakeApi:
    def __init__(self, matches=None):
        self._matches = matches if matches is not None else list(_RAW)
        self.calls: list = []

    def get_tsdb_matches_raw(self, league_id, league_name):
        self.calls.append((league_id, league_name))
        return self._matches


def test_fetch_delegates_with_correct_params():
    fake = _FakeApi()
    adapter = TsdbFixtureAdapter(api=fake)
    raw = adapter.fetch({"league_id": "4328", "league_name": "Premier League"})
    assert raw == _RAW
    assert ("4328", "Premier League") in fake.calls


def test_normalize_maps_tsdb_specific_fields():
    adapter = TsdbFixtureAdapter(api=_FakeApi())
    records = adapter.normalize(_RAW)
    r = records[0]
    assert r["tsdb_home_team_id"] == "tsdb_133604"
    assert r["tsdb_away_team_id"] == "tsdb_133610"
    # venue_city gol (reparat la sursa, R-Sync-5) -> None, nu string gol
    assert r["venue_city"] is None


def test_validate_and_persist_delegate_to_shared_helpers(monkeypatch):
    import tsdb_fixture_adapter as mod

    calls = []
    monkeypatch.setattr(mod, "validate_fixture_records",
                         lambda records, name: (calls.append(("validate", name)), records)[1])
    monkeypatch.setattr(mod, "persist_fixture_records",
                         lambda records, provider_id: (calls.append(("persist", provider_id)), True)[1])
    adapter = TsdbFixtureAdapter(api=_FakeApi())
    adapter.validate([{"home_team": "Arsenal"}])
    adapter.persist([{"home_team": "Arsenal"}])
    assert ("validate", "TsdbFixtureAdapter") in calls
    assert ("persist", "tsdb") in calls


def test_coverage_check_returns_true_deliberately():
    adapter = TsdbFixtureAdapter(api=_FakeApi())
    assert adapter.coverage_check({}) is True
    assert "coverage_check" in TsdbFixtureAdapter.__dict__
