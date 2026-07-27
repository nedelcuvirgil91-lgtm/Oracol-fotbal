"""Teste pentru espn_fixture_adapter.py (R-Sync-7a, ADR-039)."""
from __future__ import annotations

from espn_fixture_adapter import EspnFixtureAdapter

_RAW = [{
    "fixture_id": "espn_1", "home_team": "Arsenal", "away_team": "Chelsea",
    "home_team_id": "espn_359", "away_team_id": "espn_363",
    "kickoff_utc": "2026-08-01T15:00:00Z", "kickoff_date": "2026-08-01",
    "league": "Premier League", "venue_city": "London", "status": "scheduled",
    "source": "espn",
}]


class _FakeApi:
    def __init__(self, matches=None):
        self._matches = matches if matches is not None else list(_RAW)
        self.calls: list = []

    def get_espn_matches_raw(self, league, target_date):
        self.calls.append((league, target_date))
        return self._matches


def test_fetch_delegates_with_correct_params():
    fake = _FakeApi()
    adapter = EspnFixtureAdapter(api=fake)
    raw = adapter.fetch({"league": "Premier League", "target_date": "2026-08-01"})
    assert raw == _RAW
    assert ("Premier League", "2026-08-01") in fake.calls


def test_normalize_maps_espn_specific_fields():
    adapter = EspnFixtureAdapter(api=_FakeApi())
    records = adapter.normalize(_RAW)
    r = records[0]
    assert r["espn_home_team_id"] == "espn_359"
    assert r["espn_away_team_id"] == "espn_363"
    assert r["venue_city"] == "London"


def test_validate_and_persist_delegate_to_shared_helpers(monkeypatch):
    import espn_fixture_adapter as mod

    calls = []
    monkeypatch.setattr(mod, "validate_fixture_records",
                         lambda records, name: (calls.append(("validate", name)), records)[1])
    monkeypatch.setattr(mod, "persist_fixture_records",
                         lambda records, provider_id: (calls.append(("persist", provider_id)), True)[1])
    adapter = EspnFixtureAdapter(api=_FakeApi())
    adapter.validate([{"home_team": "Arsenal"}])
    adapter.persist([{"home_team": "Arsenal"}])
    assert ("validate", "EspnFixtureAdapter") in calls
    assert ("persist", "espn") in calls


def test_coverage_check_returns_true_deliberately():
    adapter = EspnFixtureAdapter(api=_FakeApi())
    assert adapter.coverage_check({}) is True
    assert "coverage_check" in EspnFixtureAdapter.__dict__
