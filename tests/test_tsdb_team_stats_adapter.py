"""Teste pentru tsdb_team_stats_adapter.py (R-Sync-8, ADR-039).

fetch() delegă la FootballOracleAPI.get_team_last_events_tsdb() (Provider
fals, injectat, fără rețea reală) — `tsdb_team_id` vine deja gata rezolvat
din `scheduled_fixtures` (R-Sync-7a), nu se caută live aici."""
from __future__ import annotations

from tsdb_team_stats_adapter import TsdbTeamStatsAdapter


_EVENTS = [
    {"date": "2026-07-01", "result": "W", "goals_for": 2, "goals_against": 1,
     "shots_on_goal": 7.0, "possession": 50.0},
    {"date": "2026-06-20", "result": "D", "goals_for": 1, "goals_against": 1,
     "shots_on_goal": 3.5, "possession": 50.0},
]


class _FakeOracleApi:
    def __init__(self, events=None):
        self._events = events if events is not None else _EVENTS
        self.calls: list = []

    def get_team_last_events_tsdb(self, team_id):
        self.calls.append(("get_team_last_events_tsdb", team_id))
        return self._events


def test_fetch_delegates_to_api_with_tsdb_team_id():
    fake = _FakeOracleApi()
    adapter = TsdbTeamStatsAdapter(api=fake)
    raw = adapter.fetch({"team_name_canonical": "Arsenal", "tsdb_team_id": "tsdb_133604"})
    assert raw == {
        "team_name_canonical": "Arsenal", "tsdb_team_id": "tsdb_133604", "events": _EVENTS,
    }
    assert ("get_team_last_events_tsdb", "tsdb_133604") in fake.calls


def test_normalize_handles_none_payload():
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi())
    assert adapter.normalize(None) == []


def test_normalize_handles_missing_team_name():
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi())
    assert adapter.normalize({"tsdb_team_id": "tsdb_1", "events": _EVENTS}) == []


def test_normalize_produces_one_record_with_events():
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({"team_name_canonical": "Arsenal", "tsdb_team_id": "tsdb_133604"})
    records = adapter.normalize(raw)
    assert records == [{
        "team_name": "Arsenal", "tsdb_team_id": "tsdb_133604", "events": _EVENTS,
    }]


def test_validate_excludes_records_without_team_name():
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi())
    records = [
        {"team_name": "Arsenal", "tsdb_team_id": "tsdb_1", "events": _EVENTS},
        {"tsdb_team_id": "tsdb_2", "events": _EVENTS},
    ]
    out = adapter.validate(records)
    assert out == [{"team_name": "Arsenal", "tsdb_team_id": "tsdb_1", "events": _EVENTS}]


def test_validate_excludes_records_without_events():
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi())
    records = [
        {"team_name": "Arsenal", "tsdb_team_id": "tsdb_1", "events": _EVENTS},
        {"team_name": "New FC", "tsdb_team_id": "tsdb_2", "events": []},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["team_name"] == "Arsenal"


def test_persist_calls_upsert_team_stats_tsdb_per_record(monkeypatch):
    calls = []

    def _fake_upsert(team, tsdb_team_id, events):
        calls.append((team, tsdb_team_id, events))
        return True

    monkeypatch.setattr("database.queries.upsert_team_stats_tsdb", _fake_upsert)
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi())
    ok = adapter.persist([{"team_name": "Arsenal", "tsdb_team_id": "tsdb_1", "events": _EVENTS}])
    assert ok is True
    assert calls == [("Arsenal", "tsdb_1", _EVENTS)]


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    def _fake_upsert(team, tsdb_team_id, events):
        return team == "Arsenal"

    monkeypatch.setattr("database.queries.upsert_team_stats_tsdb", _fake_upsert)
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi())
    ok = adapter.persist([
        {"team_name": "Arsenal", "tsdb_team_id": "tsdb_1", "events": _EVENTS},
        {"team_name": "Chelsea", "tsdb_team_id": "tsdb_2", "events": _EVENTS},
    ])
    assert ok is False


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    calls = []

    def _fake_upsert(team, tsdb_team_id, events):
        calls.append(team)
        return True

    monkeypatch.setattr("database.queries.upsert_team_stats_tsdb", _fake_upsert)
    fake_api = _FakeOracleApi()
    adapter = TsdbTeamStatsAdapter(api=fake_api)

    raw = adapter.fetch({"team_name_canonical": "Arsenal", "tsdb_team_id": "tsdb_133604"})
    records = adapter.normalize(raw)
    records = adapter.validate(records)
    ok = adapter.persist(records)

    assert ok is True
    assert calls == ["Arsenal"]


def test_full_pipeline_skips_persist_when_no_events(monkeypatch):
    calls = []
    monkeypatch.setattr("database.queries.upsert_team_stats_tsdb",
                         lambda team, tid, ev: calls.append(team) or True)
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi(events=[]))

    raw = adapter.fetch({"team_name_canonical": "New FC", "tsdb_team_id": "tsdb_9"})
    records = adapter.validate(adapter.normalize(raw))
    adapter.persist(records)

    assert calls == []


def test_coverage_check_returns_true_deliberately():
    adapter = TsdbTeamStatsAdapter(api=_FakeOracleApi())
    assert adapter.coverage_check({"team_name": "orice"}) is True
    assert "coverage_check" in TsdbTeamStatsAdapter.__dict__
