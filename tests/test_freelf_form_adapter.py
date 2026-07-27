"""Teste pentru freelf_form_adapter.py (R-Sync-6, ADR-039).

A cincea implementare reală a SyncAdapter — fetch() delegă la
FootballOracleAPI.get_freelf_standings() (Provider fals, injectat, fără
rețea reală). Fuzionează foștii Level 0+1 din _build_profile()."""
from __future__ import annotations

from freelf_form_adapter import FreeLfFormAdapter


_RAW_STANDINGS = [
    {"team": "Arsenal FC", "team_id": 1, "played": 10, "wins": 6, "draws": 2, "losses": 2,
     "goals_for": 20, "goals_against": 8, "avg_gf": 2.0, "avg_ga": 0.8, "points": 20, "position": 1},
    {"team": "Chelsea FC", "team_id": 2, "played": 10, "wins": 4, "draws": 3, "losses": 3,
     "goals_for": 15, "goals_against": 10, "avg_gf": 1.5, "avg_ga": 1.0, "points": 15, "position": 5},
    {"team": "New FC", "team_id": 3, "played": 0, "wins": 0, "draws": 0, "losses": 0,
     "goals_for": 0, "goals_against": 0, "avg_gf": 0, "avg_ga": 0, "points": 0, "position": 0},
]


class _FakeOracleApi:
    def __init__(self, standings=None):
        self._standings = standings if standings is not None else list(_RAW_STANDINGS)
        self.calls: list = []

    def get_freelf_standings(self, league):
        self.calls.append(("get_freelf_standings", league))
        return self._standings


def test_fetch_delegates_to_api_with_league():
    fake = _FakeOracleApi()
    adapter = FreeLfFormAdapter(api=fake)
    raw = adapter.fetch({"league": "Premier League"})
    assert raw == _RAW_STANDINGS
    assert ("get_freelf_standings", "Premier League") in fake.calls


def test_normalize_handles_none_payload():
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())
    assert adapter.normalize(None) == []


def test_normalize_produces_multiple_records_per_call():
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({"league": "Premier League"})
    records = adapter.normalize(raw)
    assert len(records) == 3
    assert records[0]["team_name"] == "Arsenal"  # normalize_team_name strips "FC"
    assert records[0]["played"] == 10
    assert records[0]["goals_for"] == 20


def test_normalize_form_field_is_always_empty_documented_bug():
    """[REGRESIE, R-Sync-6] get_freelf_standings() nu întoarce niciodată
    un câmp "form" — normalize() nu-l inventează, îl lasă gol, exact ca
    în producție azi (bug preexistent documentat, nu reparat aici)."""
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({"league": "Premier League"})
    records = adapter.normalize(raw)
    assert all(r["form"] == "" for r in records)


def test_normalize_calls_canonical_normalize_team_name_explicitly(monkeypatch):
    import mappings

    calls = []

    def _fake_normalize(name):
        calls.append(name)
        return f"CANONICAL[{name}]"

    monkeypatch.setattr(mappings, "normalize_team_name", _fake_normalize)
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({"league": "Premier League"})
    records = adapter.normalize(raw)

    assert calls == ["Arsenal FC", "Chelsea FC", "New FC"]
    assert records[0]["team_name"] == "CANONICAL[Arsenal FC]"


def test_validate_excludes_records_without_team_name():
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())
    records = [
        {"team_name": "Arsenal", "played": 10, "wins": 6, "draws": 2, "losses": 2,
         "goals_for": 20, "goals_against": 8, "points": 20, "position": 1, "form": ""},
        {"played": 10, "wins": 6, "draws": 2, "losses": 2,
         "goals_for": 20, "goals_against": 8, "points": 20, "position": 1, "form": ""},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["team_name"] == "Arsenal"


def test_validate_excludes_records_with_zero_played():
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())
    records = [
        {"team_name": "Arsenal", "played": 10, "wins": 6, "draws": 2, "losses": 2,
         "goals_for": 20, "goals_against": 8, "points": 20, "position": 1, "form": ""},
        {"team_name": "New FC", "played": 0, "wins": 0, "draws": 0, "losses": 0,
         "goals_for": 0, "goals_against": 0, "points": 0, "position": 0, "form": ""},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["team_name"] == "Arsenal"


def test_persist_calls_upsert_team_form_freelf_per_record(monkeypatch):
    calls = []

    def _fake_upsert(team, played, wins, draws, losses, goals_for, goals_against, points, position, form):
        calls.append((team, played, form))
        return True

    monkeypatch.setattr("database.queries.upsert_team_form_freelf", _fake_upsert)
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())
    ok = adapter.persist([{
        "team_name": "Arsenal", "played": 10, "wins": 6, "draws": 2, "losses": 2,
        "goals_for": 20, "goals_against": 8, "points": 20, "position": 1, "form": "",
    }])
    assert ok is True
    assert calls == [("Arsenal", 10, "")]


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    calls = []

    def _fake_upsert(team, played, wins, draws, losses, goals_for, goals_against, points, position, form):
        calls.append(team)
        return True

    monkeypatch.setattr("database.queries.upsert_team_form_freelf", _fake_upsert)
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())

    raw = adapter.fetch({"league": "Premier League"})
    records = adapter.normalize(raw)
    records = adapter.validate(records)
    ok = adapter.persist(records)

    assert ok is True
    assert calls == ["Arsenal", "Chelsea"]  # "New FC" (played=0) exclus


def test_coverage_check_returns_true_deliberately():
    adapter = FreeLfFormAdapter(api=_FakeOracleApi())
    assert adapter.coverage_check({"league": "orice"}) is True
    assert "coverage_check" in FreeLfFormAdapter.__dict__
