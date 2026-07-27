"""Teste pentru footballdata_form_adapter.py (R-Sync-3, ADR-039).

A doua implementare reală a SyncAdapter — sincronizare PE LIGĂ (nu per
echipă), produce MULTIPLE înregistrări per fetch() (toate echipele din
tabelul de clasament al unei competiții). fetch() delegă la
FootballOracleAPI.get_competition_standings_raw() (Provider fals,
injectat, fără rețea reală)."""
from __future__ import annotations

from footballdata_form_adapter import FootballDataFormAdapter


_RAW_STANDINGS = {
    "standings": [
        {
            "table": [
                {"team": {"id": 1, "name": "Arsenal FC"}, "playedGames": 10,
                 "goalsFor": 20, "goalsAgainst": 8, "form": "W,W,D,L,W"},
                {"team": {"id": 2, "name": "Chelsea FC"}, "playedGames": 10,
                 "goalsFor": 15, "goalsAgainst": 10, "form": "D,W,L,W,D"},
                {"team": {"id": 3, "name": "New FC"}, "playedGames": 0,
                 "goalsFor": 0, "goalsAgainst": 0, "form": ""},
            ]
        }
    ]
}


class _FakeOracleApi:
    def __init__(self, standings=None):
        self._standings = standings if standings is not None else _RAW_STANDINGS
        self.calls: list = []

    def get_competition_standings_raw(self, comp_code):
        self.calls.append(("get_competition_standings_raw", comp_code))
        return self._standings


def test_fetch_delegates_to_api_with_comp_code():
    fake = _FakeOracleApi()
    adapter = FootballDataFormAdapter(api=fake)
    raw = adapter.fetch({"comp_code": "PL"})
    assert raw == _RAW_STANDINGS
    assert ("get_competition_standings_raw", "PL") in fake.calls


def test_normalize_handles_none_payload():
    adapter = FootballDataFormAdapter(api=_FakeOracleApi())
    assert adapter.normalize(None) == []


def test_normalize_produces_multiple_records_per_call():
    adapter = FootballDataFormAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({"comp_code": "PL"})
    records = adapter.normalize(raw)
    assert len(records) == 3
    # "Arsenal FC" -> "Arsenal": normalize_team_name() (mappings.py,
    # TEAM_ALIASES) strips sufixul "FC" — comportament canonic real,
    # verificat separat mai jos (test_normalize_calls_canonical_normalize_team_name_explicitly).
    assert records[0]["team_name"] == "Arsenal"
    assert records[0]["played"] == 10
    assert records[0]["goals_for"] == 20
    assert records[0]["goals_against"] == 8
    assert records[0]["form"] == "W,W,D,L,W"


def test_normalize_calls_canonical_normalize_team_name_explicitly(monkeypatch):
    """Regresie directă, oglindă a verificării cerute la R-Sync-2:
    normalize() apelează EXPLICIT mecanismul canonic existent
    (mappings.normalize_team_name), nu o canonicalizare proprie."""
    import mappings

    calls = []

    def _fake_normalize(name):
        calls.append(name)
        return f"CANONICAL[{name}]"

    monkeypatch.setattr(mappings, "normalize_team_name", _fake_normalize)
    adapter = FootballDataFormAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({"comp_code": "PL"})
    records = adapter.normalize(raw)

    assert calls == ["Arsenal FC", "Chelsea FC", "New FC"]
    assert records[0]["team_name"] == "CANONICAL[Arsenal FC]"


def test_validate_excludes_records_without_team_name():
    adapter = FootballDataFormAdapter(api=_FakeOracleApi())
    records = [
        {"team_name": "Arsenal", "played": 10, "goals_for": 1, "goals_against": 1, "form": ""},
        {"played": 10, "goals_for": 1, "goals_against": 1, "form": ""},
    ]
    out = adapter.validate(records)
    assert out == [{"team_name": "Arsenal", "played": 10, "goals_for": 1, "goals_against": 1, "form": ""}]


def test_validate_excludes_records_with_zero_played():
    adapter = FootballDataFormAdapter(api=_FakeOracleApi())
    records = [
        {"team_name": "Arsenal", "played": 10, "goals_for": 1, "goals_against": 1, "form": ""},
        {"team_name": "New FC", "played": 0, "goals_for": 0, "goals_against": 0, "form": ""},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["team_name"] == "Arsenal"


def test_persist_calls_upsert_team_form_footballdata_per_record(monkeypatch):
    calls = []

    def _fake_upsert(team, played, goals_for, goals_against, form):
        calls.append((team, played, goals_for, goals_against, form))
        return True

    monkeypatch.setattr("database.queries.upsert_team_form_footballdata", _fake_upsert)
    adapter = FootballDataFormAdapter(api=_FakeOracleApi())
    ok = adapter.persist([
        {"team_name": "Arsenal", "played": 10, "goals_for": 20, "goals_against": 8, "form": "W,W,D"},
    ])
    assert ok is True
    assert calls == [("Arsenal", 10, 20, 8, "W,W,D")]


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    def _fake_upsert(team, played, goals_for, goals_against, form):
        return team == "Arsenal"

    monkeypatch.setattr("database.queries.upsert_team_form_footballdata", _fake_upsert)
    adapter = FootballDataFormAdapter(api=_FakeOracleApi())
    ok = adapter.persist([
        {"team_name": "Arsenal", "played": 10, "goals_for": 20, "goals_against": 8, "form": ""},
        {"team_name": "Chelsea", "played": 10, "goals_for": 15, "goals_against": 10, "form": ""},
    ])
    assert ok is False


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    """End-to-end pe adaptorul complet, fara retea reala si fara Supabase real."""
    calls = []

    def _fake_upsert(team, played, goals_for, goals_against, form):
        calls.append(team)
        return True

    monkeypatch.setattr("database.queries.upsert_team_form_footballdata", _fake_upsert)
    fake_api = _FakeOracleApi()
    adapter = FootballDataFormAdapter(api=fake_api)

    raw = adapter.fetch({"comp_code": "PL"})
    records = adapter.normalize(raw)
    records = adapter.validate(records)
    ok = adapter.persist(records)

    assert ok is True
    # "New FC" (played=0) e exclus de validate() — doar 2 rânduri persistate.
    # Nume canonice (normalize_team_name strips sufixul "FC").
    assert calls == ["Arsenal", "Chelsea"]


def test_coverage_check_returns_true_deliberately():
    """Documentează comportamentul cerut explicit, oglindă a
    apifootball_health_adapter.coverage_check(): suprascris EXPLICIT (nu
    moștenit implicit din SyncAdapter), True fix, deliberat, fiindcă
    gating-ul real are loc deja la apelant (sync/sync_team_form_footballdata.py,
    iterează exclusiv mappings.FD_COMPETITIONS)."""
    adapter = FootballDataFormAdapter(api=_FakeOracleApi())
    assert adapter.coverage_check({"league": "orice"}) is True
    assert "coverage_check" in FootballDataFormAdapter.__dict__
