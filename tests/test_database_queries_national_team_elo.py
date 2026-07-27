"""Teste pentru ADR-039 / R-Sync-4 — database.queries.get_national_team_elo()/
upsert_national_team_elo(), sursa canonică Database-First pentru ELO-ul
echipelor naționale (eloratings.net).

Verifică proprietățile cerute explicit:
(1) citire STRICT din `national_team_elo_snapshot`, niciun apel de provider;
(2) cheia e `team_name_canonical` (nume normalizat, ADR-039 Principiul 7);
(3) `upsert_national_team_elo` scrie prin `on_conflict=team_name_canonical`;
(4) degradare fără excepție la client absent / eroare de rețea."""
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
    def __init__(self, rows=None):
        self._rows = rows or []
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        if name != "national_team_elo_snapshot":
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeSelectQuery(self._rows, self.calls) if self._rows is not None else _FakeUpsertQuery(self.calls)


def test_get_national_team_elo_returns_row_when_present(monkeypatch):
    row = {"team_name_canonical": "France", "elo_rating": 2085}
    fake = _FakeClient(rows=[row])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    out = q.get_national_team_elo("France")
    assert out == row


def test_get_national_team_elo_returns_none_when_no_row(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_national_team_elo("Unknown FC") is None


def test_get_national_team_elo_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_national_team_elo("France") is None


def test_get_national_team_elo_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_national_team_elo("France") is None


def test_get_national_team_elo_filters_by_canonical_name():
    import inspect

    source = inspect.getsource(q.get_national_team_elo)
    assert '.eq("team_name_canonical"' in source


def test_upsert_national_team_elo_writes_with_correct_conflict_key(monkeypatch):
    calls: list = []

    class _UpsertClient:
        def table(self, name):
            assert name == "national_team_elo_snapshot"
            return _FakeUpsertQuery(calls)

    monkeypatch.setattr(q, "get_client", lambda: _UpsertClient())
    ok = q.upsert_national_team_elo("France", 2085)
    assert ok is True
    upsert_call = next(c for c in calls if c[0] == "upsert")
    payload, on_conflict = upsert_call[1], upsert_call[2]
    assert payload["team_name_canonical"] == "France"
    assert payload["elo_rating"] == 2085
    assert payload["source_provider"] == "eloratings"
    assert on_conflict == "team_name_canonical"


def test_upsert_national_team_elo_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_national_team_elo("France", 2085) is False


def test_upsert_national_team_elo_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.upsert_national_team_elo("France", 2085) is False
