"""Teste pentru ADR-039 / R-Sync-8 — database.queries.get_team_stats_tsdb()/
upsert_team_stats_tsdb()/get_teams_with_tsdb_id(), sursa canonică
Database-First pentru ultimele evenimente TheSportsDB per echipă.

Verifică proprietățile cerute explicit:
(1) citire STRICT din `tsdb_team_stats_snapshot`, niciun apel de provider;
(2) cheia e `team_name_canonical` (nume normalizat, ADR-039 Principiul 7);
(3) `upsert_team_stats_tsdb` scrie prin `on_conflict=team_name_canonical`;
(4) `get_teams_with_tsdb_id` citește din `scheduled_fixtures`, distinct pe
    echipă, doar rânduri cu tsdb_*_team_id populat;
(5) degradare fără excepție la client absent / eroare de rețea."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeSelectQuery:
    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    def select(self, *a, **kw):
        self._calls.append(("select", a, kw)); return self

    def eq(self, *a, **kw):
        self._calls.append(("eq", a, kw)); return self

    def gte(self, *a, **kw):
        self._calls.append(("gte", a, kw)); return self

    def lte(self, *a, **kw):
        self._calls.append(("lte", a, kw)); return self

    def or_(self, *a, **kw):
        self._calls.append(("or_", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append(("limit", a, kw)); return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeUpsertQuery:
    def __init__(self, calls):
        self._calls = calls

    def upsert(self, payload, on_conflict=None):
        self._calls.append(("upsert", payload, on_conflict)); return self

    def execute(self):
        return _FakeResult([])


class _FakeClient:
    def __init__(self, rows=None, table_name="tsdb_team_stats_snapshot"):
        self._rows = rows
        self._table_name = table_name
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        if name != self._table_name:
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeSelectQuery(self._rows, self.calls) if self._rows is not None else _FakeUpsertQuery(self.calls)


# ── get_team_stats_tsdb ───────────────────────────────────────────────────

def test_get_team_stats_tsdb_returns_events_when_present(monkeypatch):
    events = [{"result": "W", "goals_for": 2, "goals_against": 1,
               "shots_on_goal": 7.0, "possession": 50.0}]
    fake = _FakeClient(rows=[{"events": events}])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_stats_tsdb("Arsenal") == events


def test_get_team_stats_tsdb_returns_empty_when_no_row(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_stats_tsdb("Unknown FC") == []


def test_get_team_stats_tsdb_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_team_stats_tsdb("Arsenal") == []


def test_get_team_stats_tsdb_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_team_stats_tsdb("Arsenal") == []


def test_get_team_stats_tsdb_filters_by_canonical_name():
    import inspect

    source = inspect.getsource(q.get_team_stats_tsdb)
    assert '.eq("team_name_canonical"' in source


# ── upsert_team_stats_tsdb ────────────────────────────────────────────────

def test_upsert_team_stats_tsdb_writes_with_correct_conflict_key(monkeypatch):
    calls: list = []

    class _UpsertClient:
        def table(self, name):
            assert name == "tsdb_team_stats_snapshot"
            return _FakeUpsertQuery(calls)

    monkeypatch.setattr(q, "get_client", lambda: _UpsertClient())
    events = [{"result": "W", "goals_for": 2, "goals_against": 1,
               "shots_on_goal": 7.0, "possession": 50.0}]
    ok = q.upsert_team_stats_tsdb("Arsenal", "133604", events)
    assert ok is True
    upsert_call = next(c for c in calls if c[0] == "upsert")
    payload, on_conflict = upsert_call[1], upsert_call[2]
    assert payload["team_name_canonical"] == "Arsenal"
    assert payload["tsdb_team_id"] == "133604"
    assert payload["events"] == events
    assert payload["source_provider"] == "thesportsdb"
    assert on_conflict == "team_name_canonical"


def test_upsert_team_stats_tsdb_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_team_stats_tsdb("Arsenal", "133604", []) is False


def test_upsert_team_stats_tsdb_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.upsert_team_stats_tsdb("Arsenal", "133604", []) is False


# ── get_teams_with_tsdb_id ────────────────────────────────────────────────

def test_get_teams_with_tsdb_id_returns_distinct_teams(monkeypatch):
    rows = [
        {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
         "tsdb_home_team_id": "133604", "tsdb_away_team_id": "133610"},
        {"home_team_canonical": "Arsenal", "away_team_canonical": "Liverpool",
         "tsdb_home_team_id": "133604", "tsdb_away_team_id": None},
    ]
    fake = _FakeClient(rows=rows, table_name="scheduled_fixtures")
    monkeypatch.setattr(q, "get_client", lambda: fake)
    out = q.get_teams_with_tsdb_id()
    teams = {r["team_name"]: r["tsdb_team_id"] for r in out}
    # Liverpool exclus — apare doar ca oaspete, fără tsdb_away_team_id in
    # acel rand (None).
    assert teams == {"Arsenal": "133604", "Chelsea": "133610"}


def test_get_teams_with_tsdb_id_skips_rows_without_tsdb_id(monkeypatch):
    rows = [
        {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
         "tsdb_home_team_id": None, "tsdb_away_team_id": None},
    ]
    fake = _FakeClient(rows=rows, table_name="scheduled_fixtures")
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_teams_with_tsdb_id() == []


def test_get_teams_with_tsdb_id_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_teams_with_tsdb_id() == []


def test_get_teams_with_tsdb_id_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_teams_with_tsdb_id() == []
