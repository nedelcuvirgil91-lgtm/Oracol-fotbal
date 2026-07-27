"""Teste pentru odds_api_fixture_adapter.py (R-Sync-7a, ADR-039)."""
from __future__ import annotations

from odds_api_fixture_adapter import OddsApiFixtureAdapter

_RAW = [{
    "fixture_id": "odds_1", "home_team": "Arsenal", "away_team": "Chelsea",
    "home_team_id": None, "away_team_id": None,
    "kickoff_utc": "2026-08-01T15:00:00Z", "kickoff_date": "2026-08-01",
    "league": "Premier League", "venue_city": "", "status": "scheduled",
    "source": "the-odds-api", "_odds_api_id": "ev123", "_sport_key": "soccer_epl",
}]


class _FakeApi:
    def __init__(self, matches=None):
        self._matches = matches if matches is not None else list(_RAW)
        self.calls: list = []

    def get_odds_api_events_raw(self, sport_key, days_ahead):
        self.calls.append((sport_key, days_ahead))
        return self._matches


def test_fetch_delegates_with_correct_params():
    fake = _FakeApi()
    adapter = OddsApiFixtureAdapter(api=fake)
    raw = adapter.fetch({"sport_key": "soccer_epl", "days_ahead": 7})
    assert raw == _RAW
    assert ("soccer_epl", 7) in fake.calls


def test_fetch_defaults_days_ahead_to_7():
    fake = _FakeApi()
    adapter = OddsApiFixtureAdapter(api=fake)
    adapter.fetch({"sport_key": "soccer_epl"})
    assert ("soccer_epl", 7) in fake.calls


def test_normalize_handles_none():
    adapter = OddsApiFixtureAdapter(api=_FakeApi())
    assert adapter.normalize(None) == []


def test_normalize_maps_odds_api_specific_fields():
    adapter = OddsApiFixtureAdapter(api=_FakeApi())
    records = adapter.normalize(_RAW)
    r = records[0]
    assert r["odds_api_event_id"] == "ev123"
    assert r["odds_api_sport_key"] == "soccer_epl"
    assert r["venue_city"] is None  # "" -> None (camp gol tratat ca lipsa)


def test_normalize_handles_missing_odds_id():
    raw = [dict(_RAW[0])]
    raw[0].pop("_odds_api_id")
    adapter = OddsApiFixtureAdapter(api=_FakeApi())
    records = adapter.normalize(raw)
    assert records[0]["odds_api_event_id"] is None


def test_validate_and_persist_delegate_to_shared_helpers(monkeypatch):
    import odds_api_fixture_adapter as mod

    calls = []
    monkeypatch.setattr(mod, "validate_fixture_records",
                         lambda records, name: (calls.append(("validate", name)), records)[1])
    monkeypatch.setattr(mod, "persist_fixture_records",
                         lambda records, provider_id: (calls.append(("persist", provider_id)), True)[1])
    adapter = OddsApiFixtureAdapter(api=_FakeApi())
    adapter.validate([{"home_team": "Arsenal"}])
    adapter.persist([{"home_team": "Arsenal"}])
    assert ("validate", "OddsApiFixtureAdapter") in calls
    assert ("persist", "oddsapi") in calls


def test_coverage_check_returns_true_deliberately():
    adapter = OddsApiFixtureAdapter(api=_FakeApi())
    assert adapter.coverage_check({}) is True
    assert "coverage_check" in OddsApiFixtureAdapter.__dict__
