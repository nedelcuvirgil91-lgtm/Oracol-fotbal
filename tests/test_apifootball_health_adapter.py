"""Teste pentru apifootball_health_adapter.py (R-Sync-2, ADR-039).

Prima implementare reală a SyncAdapter — fetch()/normalize() delegă la
ApiFootballProvider (deja testat separat, test_football_providers.py);
validate()/persist() sunt genuine adăugiri, testate direct aici, fără
rețea reală (Provider fals, injectat)."""
from __future__ import annotations

from apifootball_health_adapter import ApiFootballHealthAdapter
from football_providers import CoachInfo, Injury


class _FakeApiFootballProvider:
    def __init__(self, team_id=42, injuries=None, coaches=None):
        self._team_id = team_id
        self._injuries = injuries if injuries is not None else [
            Injury(player_name="M. Salah", team_name="Liverpool", injury_type="Injury",
                   reason="Hamstring", player_id="1", fixture_id=None, source_provider="apifootball"),
        ]
        self._coaches = coaches if coaches is not None else [
            CoachInfo(coach_id="10", name="A. Slot", team_name="Liverpool",
                      appointed_date="2024-06-01", nationality="Netherlands", source_provider="apifootball"),
        ]
        self.calls: list = []

    def resolve_team_id(self, team_name):
        self.calls.append(("resolve_team_id", team_name))
        return self._team_id

    def get_injuries(self, team_name, team_id, league, season):
        self.calls.append(("get_injuries", team_name, team_id, league, season))
        return self._injuries

    def get_coaches(self, team_name, team_id, league):
        self.calls.append(("get_coaches", team_name, team_id, league))
        return self._coaches


def test_resolve_team_id_delegates_to_provider():
    fake = _FakeApiFootballProvider(team_id=99)
    adapter = ApiFootballHealthAdapter(provider=fake)
    assert adapter.resolve_team_id("Liverpool") == 99
    assert ("resolve_team_id", "Liverpool") in fake.calls


def test_fetch_calls_both_injuries_and_coaches():
    fake = _FakeApiFootballProvider()
    adapter = ApiFootballHealthAdapter(provider=fake)
    raw = adapter.fetch({"team_name": "Liverpool", "team_id": 42, "league": "Premier League", "season": 2025})
    assert raw["team_name"] == "Liverpool"
    assert len(raw["injuries"]) == 1
    assert len(raw["coaches"]) == 1
    assert any(c[0] == "get_injuries" for c in fake.calls)
    assert any(c[0] == "get_coaches" for c in fake.calls)


def test_normalize_converts_dataclasses_to_plain_dicts():
    fake = _FakeApiFootballProvider()
    adapter = ApiFootballHealthAdapter(provider=fake)
    raw = adapter.fetch({"team_name": "Liverpool", "team_id": 42, "league": "Premier League", "season": 2025})
    records = adapter.normalize(raw)
    assert len(records) == 1
    rec = records[0]
    assert rec["team_name"] == "Liverpool"
    assert rec["injuries"][0]["player_name"] == "M. Salah"
    assert rec["coaches"][0]["name"] == "A. Slot"
    # dict-uri simple, nu instanțe dataclass — serializabile JSONB direct
    assert isinstance(rec["injuries"][0], dict)


def test_normalize_handles_none_payload():
    adapter = ApiFootballHealthAdapter(provider=_FakeApiFootballProvider())
    assert adapter.normalize(None) == []


def test_normalize_calls_canonical_normalize_team_name_explicitly(monkeypatch):
    """Regresie directă pe verificarea cerută: normalize() NU se bazează
    implicit pe faptul că apelantul a normalizat deja — apelează EXPLICIT
    mecanismul canonic existent (mappings.normalize_team_name), nu o
    canonicalizare proprie (.lower()/.strip()/etc.)."""
    import mappings

    calls = []

    def _fake_normalize(name):
        calls.append(name)
        return f"CANONICAL[{name}]"

    monkeypatch.setattr(mappings, "normalize_team_name", _fake_normalize)
    adapter = ApiFootballHealthAdapter(provider=_FakeApiFootballProvider())
    raw = adapter.fetch({"team_name": "Man Utd", "team_id": 42, "league": "Premier League", "season": 2025})
    records = adapter.normalize(raw)

    assert calls == ["Man Utd"]
    assert records[0]["team_name"] == "CANONICAL[Man Utd]"


def test_validate_excludes_records_without_team_name():
    adapter = ApiFootballHealthAdapter(provider=_FakeApiFootballProvider())
    records = [{"team_name": "Liverpool", "injuries": [], "coaches": []}, {"injuries": [], "coaches": []}]
    out = adapter.validate(records)
    assert out == [{"team_name": "Liverpool", "injuries": [], "coaches": []}]


def test_validate_never_raises_on_bad_records():
    adapter = ApiFootballHealthAdapter(provider=_FakeApiFootballProvider())
    out = adapter.validate([{}, {"team_name": ""}, {"team_name": None}])
    assert out == []


def test_persist_calls_upsert_team_health_per_record(monkeypatch):
    import apifootball_health_adapter as mod

    calls = []

    def _fake_upsert(team, injuries, coaches, source_provider="apifootball"):
        calls.append((team, injuries, coaches, source_provider))
        return True

    monkeypatch.setattr("database.queries.upsert_team_health", _fake_upsert)
    adapter = ApiFootballHealthAdapter(provider=_FakeApiFootballProvider())
    ok = adapter.persist([
        {"team_name": "Liverpool", "injuries": [{"a": 1}], "coaches": [{"b": 2}]},
    ])
    assert ok is True
    assert calls == [("Liverpool", [{"a": 1}], [{"b": 2}], "apifootball")]


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    def _fake_upsert(team, injuries, coaches, source_provider="apifootball"):
        return team == "Liverpool"  # doar prima reușește

    monkeypatch.setattr("database.queries.upsert_team_health", _fake_upsert)
    adapter = ApiFootballHealthAdapter(provider=_FakeApiFootballProvider())
    ok = adapter.persist([
        {"team_name": "Liverpool", "injuries": [], "coaches": []},
        {"team_name": "Chelsea", "injuries": [], "coaches": []},
    ])
    assert ok is False


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    """End-to-end pe adaptorul complet, fara retea reala si fara Supabase real."""
    calls = []

    def _fake_upsert(team, injuries, coaches, source_provider="apifootball"):
        calls.append(team)
        return True

    monkeypatch.setattr("database.queries.upsert_team_health", _fake_upsert)
    adapter = ApiFootballHealthAdapter(provider=_FakeApiFootballProvider())

    raw = adapter.fetch({"team_name": "Liverpool", "team_id": 42, "league": "Premier League", "season": 2025})
    records = adapter.normalize(raw)
    records = adapter.validate(records)
    ok = adapter.persist(records)

    assert ok is True
    assert calls == ["Liverpool"]


def test_coverage_check_returns_true_deliberately_not_via_empty_coverage_cache():
    """Documentează comportamentul cerut explicit: coverage_check() e
    suprascris EXPLICIT (nu moștenit implicit din SyncAdapter), True fix,
    deliberat, fiindcă gating-ul real deja are loc în fetch() prin
    get_injuries()/get_coaches() -> _covered(). Nu consultă Coverage Cache
    (migrare 016, goală azi)."""
    adapter = ApiFootballHealthAdapter(provider=_FakeApiFootballProvider())
    assert adapter.coverage_check({"league": "orice"}) is True
    # Suprascris explicit pe subclasă, nu doar mostenit tacit de la SyncAdapter.
    assert "coverage_check" in ApiFootballHealthAdapter.__dict__
