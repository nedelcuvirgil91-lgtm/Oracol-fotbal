"""Teste pentru freelf_lineup_adapter.py (R-Sync-10, ADR-039).

fetch() delegă la FootballOracleAPI.get_lineup() (Provider fals, injectat,
fără rețea reală), apelat de DOUĂ ori per meci (acasă + oaspete) —
event_id-ul vine deja gata rezolvat din scheduled_fixtures (R-Sync-7a)."""
from __future__ import annotations

from freelf_lineup_adapter import FreelfLineupAdapter


_HOME_LINEUP = {"confirmed": True, "formation": "4-3-3",
                "unavailable": [{"id": 1, "name": "Player X", "market_value": 5_000_000,
                                  "unavailability": {"type": "injured", "expectedReturn": "a week"}}]}
_AWAY_LINEUP = {"confirmed": False, "formation": "", "unavailable": []}


class _FakeOracleApi:
    def __init__(self, home=_HOME_LINEUP, away=_AWAY_LINEUP):
        self._home = home
        self._away = away
        self.calls: list = []

    def get_lineup(self, event_id, is_home):
        self.calls.append(("get_lineup", event_id, is_home))
        return self._home if is_home else self._away


def _params():
    return {
        "home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
        "kickoff_date": "2026-08-01", "freelf_event_id": "998877",
    }


def test_fetch_calls_get_lineup_for_both_sides():
    fake = _FakeOracleApi()
    adapter = FreelfLineupAdapter(api=fake)
    raw = adapter.fetch(_params())
    assert ("get_lineup", 998877, True) in fake.calls
    assert ("get_lineup", 998877, False) in fake.calls
    assert raw["home_lineup"] == _HOME_LINEUP
    assert raw["away_lineup"] == _AWAY_LINEUP


def test_fetch_returns_none_when_both_sides_empty():
    adapter = FreelfLineupAdapter(api=_FakeOracleApi(home=None, away=None))
    assert adapter.fetch(_params()) is None


def test_normalize_handles_none_payload():
    adapter = FreelfLineupAdapter(api=_FakeOracleApi())
    assert adapter.normalize(None) == []


def test_normalize_produces_one_record_with_both_sides():
    adapter = FreelfLineupAdapter(api=_FakeOracleApi())
    raw = adapter.fetch(_params())
    records = adapter.normalize(raw)
    assert len(records) == 1
    r = records[0]
    assert r["home_team"] == "Arsenal"
    assert r["away_team"] == "Chelsea"
    assert r["home_confirmed"] is True
    assert r["home_formation"] == "4-3-3"
    assert len(r["home_unavailable"]) == 1
    assert r["away_confirmed"] is False
    assert r["away_unavailable"] == []


def test_validate_excludes_records_without_teams():
    adapter = FreelfLineupAdapter(api=_FakeOracleApi())
    records = [
        {"home_team": "Arsenal", "away_team": "Chelsea"},
        {"away_team": "Chelsea"},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["home_team"] == "Arsenal"


def test_persist_calls_upsert_freelf_lineup_snapshot(monkeypatch):
    calls = []

    def _fake_upsert(home, away, kickoff, event_id, hc, hf, hu, ac, af, au):
        calls.append((home, away, kickoff, event_id, hc, ac))
        return True

    monkeypatch.setattr("database.queries.upsert_freelf_lineup_snapshot", _fake_upsert)
    adapter = FreelfLineupAdapter(api=_FakeOracleApi())
    raw = adapter.fetch(_params())
    records = adapter.validate(adapter.normalize(raw))
    ok = adapter.persist(records)

    assert ok is True
    assert calls == [("Arsenal", "Chelsea", "2026-08-01", "998877", True, False)]


def test_persist_returns_false_if_write_fails(monkeypatch):
    monkeypatch.setattr("database.queries.upsert_freelf_lineup_snapshot", lambda *a: False)
    adapter = FreelfLineupAdapter(api=_FakeOracleApi())
    raw = adapter.fetch(_params())
    records = adapter.validate(adapter.normalize(raw))
    assert adapter.persist(records) is False


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "database.queries.upsert_freelf_lineup_snapshot",
        lambda home, *rest: calls.append(home) or True,
    )
    adapter = FreelfLineupAdapter(api=_FakeOracleApi())

    raw = adapter.fetch(_params())
    records = adapter.validate(adapter.normalize(raw))
    ok = adapter.persist(records)

    assert ok is True
    assert calls == ["Arsenal"]


def test_coverage_check_returns_true_deliberately():
    adapter = FreelfLineupAdapter(api=_FakeOracleApi())
    assert adapter.coverage_check({"home_team": "orice"}) is True
    assert "coverage_check" in FreelfLineupAdapter.__dict__
