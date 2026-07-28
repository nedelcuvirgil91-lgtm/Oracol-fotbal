"""Teste pentru freelf_h2h_adapter.py (R-Sync-9, ADR-039).

fetch() delegă la FootballOracleAPI.get_h2h() (Provider fals, injectat,
fără rețea reală) — `freelf_event_id`/nume vin deja gata rezolvate din
scheduled_fixtures (R-Sync-7a), nu se caută live aici."""
from __future__ import annotations

from freelf_h2h_adapter import FreelfH2hAdapter


_H2H = {"meetings": 3, "home_wins": 2, "draws": 1, "away_wins": 0,
        "home_goals_avg": 1.5, "away_goals_avg": 0.7, "last_5": ["H", "D", "H"],
        "h2h_modifier": 0.1, "summary": "H2H (3 meciuri): 2W 1D 0L"}


class _FakeOracleApi:
    def __init__(self, h2h=_H2H):
        self._h2h = h2h
        self.calls: list = []

    def get_h2h(self, event_id, home_name, away_name):
        self.calls.append(("get_h2h", event_id, home_name, away_name))
        return self._h2h


def test_fetch_delegates_to_api_with_event_id_and_names():
    fake = _FakeOracleApi()
    adapter = FreelfH2hAdapter(api=fake)
    raw = adapter.fetch({
        "home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
        "freelf_event_id": "998877",
    })
    assert raw == {
        "home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
        "freelf_event_id": "998877", "h2h": _H2H,
    }
    assert ("get_h2h", 998877, "Arsenal", "Chelsea") in fake.calls


def test_fetch_returns_none_when_api_returns_none():
    adapter = FreelfH2hAdapter(api=_FakeOracleApi(h2h=None))
    raw = adapter.fetch({
        "home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
        "freelf_event_id": "998877",
    })
    assert raw is None


def test_normalize_handles_none_payload():
    adapter = FreelfH2hAdapter(api=_FakeOracleApi())
    assert adapter.normalize(None) == []


def test_normalize_produces_one_record():
    adapter = FreelfH2hAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({
        "home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
        "freelf_event_id": "998877",
    })
    records = adapter.normalize(raw)
    assert records == [{
        "home_team": "Arsenal", "away_team": "Chelsea", "freelf_event_id": "998877",
        "meetings": 3, "home_wins": 2, "draws": 1, "away_wins": 0,
        "home_goals_avg": 1.5, "away_goals_avg": 0.7, "last_5": ["H", "D", "H"],
        "h2h_modifier": 0.1, "summary": "H2H (3 meciuri): 2W 1D 0L",
    }]


def test_validate_excludes_records_without_teams():
    adapter = FreelfH2hAdapter(api=_FakeOracleApi())
    records = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "meetings": 3},
        {"away_team": "Chelsea", "meetings": 3},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["home_team"] == "Arsenal"


def test_validate_excludes_records_without_meetings():
    adapter = FreelfH2hAdapter(api=_FakeOracleApi())
    records = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "meetings": 3},
        {"home_team": "Real Madrid", "away_team": "Barcelona", "meetings": 0},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["home_team"] == "Arsenal"


def test_persist_calls_upsert_freelf_h2h_snapshot_per_record(monkeypatch):
    calls = []

    def _fake_upsert(home, away, event_id, meetings, hw, d, aw, hg, ag, last5, mod, summary):
        calls.append((home, away, event_id, meetings))
        return True

    monkeypatch.setattr("database.queries.upsert_freelf_h2h_snapshot", _fake_upsert)
    adapter = FreelfH2hAdapter(api=_FakeOracleApi())
    record = {
        "home_team": "Arsenal", "away_team": "Chelsea", "freelf_event_id": "998877",
        "meetings": 3, "home_wins": 2, "draws": 1, "away_wins": 0,
        "home_goals_avg": 1.5, "away_goals_avg": 0.7, "last_5": ["H", "D", "H"],
        "h2h_modifier": 0.1, "summary": "H2H",
    }
    ok = adapter.persist([record])
    assert ok is True
    assert calls == [("Arsenal", "Chelsea", "998877", 3)]


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    def _fake_upsert(home, away, *a):
        return home == "Arsenal"

    monkeypatch.setattr("database.queries.upsert_freelf_h2h_snapshot", _fake_upsert)
    adapter = FreelfH2hAdapter(api=_FakeOracleApi())
    base = {"freelf_event_id": "1", "meetings": 1, "home_wins": 1, "draws": 0,
            "away_wins": 0, "home_goals_avg": 1.0, "away_goals_avg": 0.0,
            "last_5": ["H"], "h2h_modifier": 0.1, "summary": ""}
    ok = adapter.persist([
        {**base, "home_team": "Arsenal", "away_team": "Chelsea"},
        {**base, "home_team": "Liverpool", "away_team": "City"},
    ])
    assert ok is False


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "database.queries.upsert_freelf_h2h_snapshot",
        lambda home, away, *a: calls.append(home) or True,
    )
    adapter = FreelfH2hAdapter(api=_FakeOracleApi())

    raw = adapter.fetch({
        "home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
        "freelf_event_id": "998877",
    })
    records = adapter.validate(adapter.normalize(raw))
    ok = adapter.persist(records)

    assert ok is True
    assert calls == ["Arsenal"]


def test_full_pipeline_skips_persist_when_no_h2h(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "database.queries.upsert_freelf_h2h_snapshot",
        lambda home, away, *a: calls.append(home) or True,
    )
    adapter = FreelfH2hAdapter(api=_FakeOracleApi(h2h=None))

    raw = adapter.fetch({
        "home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
        "freelf_event_id": "998877",
    })
    records = adapter.validate(adapter.normalize(raw))
    adapter.persist(records)

    assert calls == []


def test_coverage_check_returns_true_deliberately():
    adapter = FreelfH2hAdapter(api=_FakeOracleApi())
    assert adapter.coverage_check({"home_team": "orice"}) is True
    assert "coverage_check" in FreelfH2hAdapter.__dict__
