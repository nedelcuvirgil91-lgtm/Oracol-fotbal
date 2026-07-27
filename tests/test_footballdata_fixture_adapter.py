"""Teste pentru footballdata_fixture_adapter.py (R-Sync-7a, ADR-039)."""
from __future__ import annotations

from footballdata_fixture_adapter import FootballDataFixtureAdapter

_RAW = [{
    "fixture_id": "fd_1", "home_team": "Arsenal", "away_team": "Chelsea",
    "home_team_id": "fd_57", "away_team_id": "fd_61",
    "kickoff_utc": "2026-08-01T15:00:00Z", "kickoff_date": "2026-08-01",
    "league": "England", "venue_city": "England", "status": "scheduled",
    "source": "football-data.org",
}]


class _FakeApi:
    def __init__(self, matches=None):
        self._matches = matches if matches is not None else list(_RAW)
        self.calls: list = []

    def get_football_data_matches_raw(self, date_from, date_to, comp_codes=None):
        self.calls.append((date_from, date_to, comp_codes))
        return self._matches


def test_fetch_delegates_with_correct_params():
    fake = _FakeApi()
    adapter = FootballDataFixtureAdapter(api=fake)
    raw = adapter.fetch({"date_from": "2026-08-01", "date_to": "2026-08-08", "comp_codes": ["PL"]})
    assert raw == _RAW
    assert ("2026-08-01", "2026-08-08", ["PL"]) in fake.calls


def test_normalize_maps_fd_specific_fields():
    adapter = FootballDataFixtureAdapter(api=_FakeApi())
    records = adapter.normalize(_RAW)
    r = records[0]
    assert r["fd_home_team_id"] == "fd_57"
    assert r["fd_away_team_id"] == "fd_61"
    # league brut, "England" - NU e canonicalizat aici (documentat, gasit la audit)
    assert r["league"] == "England"


def test_validate_and_persist_delegate_to_shared_helpers(monkeypatch):
    import footballdata_fixture_adapter as mod

    calls = []
    monkeypatch.setattr(mod, "validate_fixture_records",
                         lambda records, name: (calls.append(("validate", name)), records)[1])
    monkeypatch.setattr(mod, "persist_fixture_records",
                         lambda records, provider_id: (calls.append(("persist", provider_id)), True)[1])
    adapter = FootballDataFixtureAdapter(api=_FakeApi())
    adapter.validate([{"home_team": "Arsenal"}])
    adapter.persist([{"home_team": "Arsenal"}])
    assert ("validate", "FootballDataFixtureAdapter") in calls
    assert ("persist", "fd") in calls


def test_coverage_check_returns_true_deliberately():
    adapter = FootballDataFixtureAdapter(api=_FakeApi())
    assert adapter.coverage_check({}) is True
    assert "coverage_check" in FootballDataFixtureAdapter.__dict__
