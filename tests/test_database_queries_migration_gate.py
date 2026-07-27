"""Teste pentru database.queries.get_migration_gate_status_row() /
list_recent_equivalence_evaluations() (ADR-040, G3)."""
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

    def order(self, *a, **kw):
        self._calls.append(("order", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append(("limit", a, kw)); return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, table_name, rows):
        self._table_name = table_name
        self._rows = rows
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        if name != self._table_name:
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeSelectQuery(self._rows, self.calls)


def test_get_migration_gate_status_row_returns_first_row(monkeypatch):
    rows = [{"gate_key": "R-Sync-7b", "entity": "scheduled_fixtures", "current_health": "green"}]
    client = _FakeClient("migration_gate_status", rows)
    monkeypatch.setattr(q, "get_client", lambda: client)

    row = q.get_migration_gate_status_row("R-Sync-7b", "scheduled_fixtures")
    assert row["current_health"] == "green"
    eq_calls = [c for c in client.calls if c[0] == "eq"]
    assert ("eq", ("gate_key", "R-Sync-7b"), {}) in eq_calls
    assert ("eq", ("entity", "scheduled_fixtures"), {}) in eq_calls


def test_get_migration_gate_status_row_none_when_empty(monkeypatch):
    client = _FakeClient("migration_gate_status", [])
    monkeypatch.setattr(q, "get_client", lambda: client)
    assert q.get_migration_gate_status_row("R-Sync-7b", "scheduled_fixtures") is None


def test_get_migration_gate_status_row_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_migration_gate_status_row("R-Sync-7b", "scheduled_fixtures") is None


def test_get_migration_gate_status_row_none_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("boom")
    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_migration_gate_status_row("R-Sync-7b", "scheduled_fixtures") is None


def test_list_recent_equivalence_evaluations_returns_rows(monkeypatch):
    rows = [{"id": 2, "equivalence_state": "green"}, {"id": 1, "equivalence_state": "red"}]
    client = _FakeClient("equivalence_evaluations", rows)
    monkeypatch.setattr(q, "get_client", lambda: client)

    out = q.list_recent_equivalence_evaluations("R-Sync-7b", "scheduled_fixtures", limit=10)
    assert out == rows
    limit_calls = [c for c in client.calls if c[0] == "limit"]
    assert limit_calls[0][1] == (10,)


def test_list_recent_equivalence_evaluations_empty_list_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.list_recent_equivalence_evaluations("R-Sync-7b", "scheduled_fixtures") == []


def test_list_recent_equivalence_evaluations_empty_list_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("boom")
    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.list_recent_equivalence_evaluations("R-Sync-7b", "scheduled_fixtures") == []
