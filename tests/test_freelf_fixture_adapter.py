"""Teste pentru freelf_fixture_adapter.py (R-Sync-7a, ADR-039)."""
from __future__ import annotations

from freelf_fixture_adapter import FreeLfFixtureAdapter

_RAW = [{
    "fixture_id": "freelf_1", "home_team": "Arsenal", "away_team": "Chelsea",
    "home_team_id": "freelf_11", "away_team_id": "freelf_22",
    "_freelf_event_id": 998877, "kickoff_utc": "2026-08-01T15:00:00Z",
    "kickoff_date": "2026-08-01", "league": "Premier League",
    "venue_city": "London", "status": "scheduled", "coverage_level": "xg",
    "source": "freelivefootball",
}]


class _FakeApi:
    def __init__(self, matches=None):
        self._matches = matches if matches is not None else list(_RAW)
        self.calls: list = []

    def get_freelf_matches_raw(self, target_date, league):
        self.calls.append((target_date, league))
        return self._matches


def test_fetch_delegates_with_correct_params():
    fake = _FakeApi()
    adapter = FreeLfFixtureAdapter(api=fake)
    raw = adapter.fetch({"target_date": "2026-08-01", "league": "Premier League"})
    assert raw == _RAW
    assert ("2026-08-01", "Premier League") in fake.calls


def test_normalize_handles_none_and_empty():
    adapter = FreeLfFixtureAdapter(api=_FakeApi())
    assert adapter.normalize(None) == []
    assert adapter.normalize([]) == []


def test_normalize_maps_freelf_specific_fields():
    adapter = FreeLfFixtureAdapter(api=_FakeApi())
    records = adapter.normalize(_RAW)
    assert len(records) == 1
    r = records[0]
    assert r["home_team"] == "Arsenal"
    assert r["away_team"] == "Chelsea"
    assert r["freelf_event_id"] == "998877"
    assert r["freelf_home_team_id"] == "freelf_11"
    assert r["freelf_away_team_id"] == "freelf_22"
    assert r["freelf_coverage_level"] == "xg"
    assert r["league"] == "Premier League"
    assert r["venue_city"] == "London"
    # NU seteaza campuri ale altor provideri
    assert "tsdb_home_team_id" not in r
    assert "odds_api_event_id" not in r


def test_normalize_handles_missing_event_id():
    raw = [dict(_RAW[0])]
    raw[0].pop("_freelf_event_id")
    adapter = FreeLfFixtureAdapter(api=_FakeApi())
    records = adapter.normalize(raw)
    assert records[0]["freelf_event_id"] is None


def test_validate_and_persist_delegate_to_shared_helpers(monkeypatch):
    import freelf_fixture_adapter as mod

    calls = []
    monkeypatch.setattr(
        mod, "validate_fixture_records",
        lambda records, name: (calls.append(("validate", name)), records)[1],
    )
    monkeypatch.setattr(
        mod, "persist_fixture_records",
        lambda records, provider_id: (calls.append(("persist", provider_id)), True)[1],
    )
    adapter = FreeLfFixtureAdapter(api=_FakeApi())
    adapter.validate([{"home_team": "Arsenal"}])
    adapter.persist([{"home_team": "Arsenal"}])
    assert ("validate", "FreeLfFixtureAdapter") in calls
    assert ("persist", "freelf") in calls


def test_coverage_check_returns_true_deliberately():
    adapter = FreeLfFixtureAdapter(api=_FakeApi())
    assert adapter.coverage_check({}) is True
    assert "coverage_check" in FreeLfFixtureAdapter.__dict__
