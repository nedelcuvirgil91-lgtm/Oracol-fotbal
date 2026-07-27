"""Teste pentru apifootball_fixture_adapter.py (R-Sync-7a, ADR-039)."""
from __future__ import annotations

from apifootball_fixture_adapter import ApiFootballFixtureAdapter

_RAW = [{
    "fixture_id": "apifootball_1", "home_team": "Arsenal", "away_team": "Chelsea",
    "home_team_id": "apifootball_42", "away_team_id": "apifootball_49",
    "kickoff_utc": "2026-08-01T15:00:00Z", "kickoff_date": "2026-08-01",
    "league": "Premier League", "venue_city": "London", "status": "scheduled",
    "source": "apifootball",
}]


class _FakeApi:
    def __init__(self, matches=None):
        self._matches = matches if matches is not None else list(_RAW)
        self.calls: list = []

    def get_api_football_matches_raw(self, league, date_from, date_to):
        self.calls.append((league, date_from, date_to))
        return self._matches


def test_fetch_delegates_with_correct_params():
    fake = _FakeApi()
    adapter = ApiFootballFixtureAdapter(api=fake)
    raw = adapter.fetch({"league": "Premier League", "date_from": "2026-08-01", "date_to": "2026-08-08"})
    assert raw == _RAW
    assert ("Premier League", "2026-08-01", "2026-08-08") in fake.calls


def test_normalize_maps_apifootball_specific_fields():
    adapter = ApiFootballFixtureAdapter(api=_FakeApi())
    records = adapter.normalize(_RAW)
    r = records[0]
    assert r["apifootball_fixture_id"] == "apifootball_1"
    assert r["apifootball_home_team_id"] == "apifootball_42"
    assert r["apifootball_away_team_id"] == "apifootball_49"


def test_validate_and_persist_delegate_to_shared_helpers(monkeypatch):
    import apifootball_fixture_adapter as mod

    calls = []
    monkeypatch.setattr(mod, "validate_fixture_records",
                         lambda records, name: (calls.append(("validate", name)), records)[1])
    monkeypatch.setattr(mod, "persist_fixture_records",
                         lambda records, provider_id: (calls.append(("persist", provider_id)), True)[1])
    adapter = ApiFootballFixtureAdapter(api=_FakeApi())
    adapter.validate([{"home_team": "Arsenal"}])
    adapter.persist([{"home_team": "Arsenal"}])
    assert ("validate", "ApiFootballFixtureAdapter") in calls
    assert ("persist", "apifootball") in calls


def test_coverage_check_returns_true_deliberately():
    adapter = ApiFootballFixtureAdapter(api=_FakeApi())
    assert adapter.coverage_check({}) is True
    assert "coverage_check" in ApiFootballFixtureAdapter.__dict__
