"""Teste pentru ADR-039 / R-Sync-6 — database.queries.get_team_form_freelf_snapshot()/
upsert_team_form_freelf(), sursa canonică Database-First pentru
standings/formă FreeLF a unei echipe."""
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
        if name != "freelf_team_form_snapshot":
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeSelectQuery(self._rows, self.calls) if self._rows is not None else _FakeUpsertQuery(self.calls)


def test_get_team_form_freelf_snapshot_returns_row_when_present(monkeypatch):
    row = {"team_name_canonical": "Arsenal", "played": 10, "goals_for": 20, "goals_against": 8, "form": ""}
    fake = _FakeClient(rows=[row])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_form_freelf_snapshot("Arsenal") == row


def test_get_team_form_freelf_snapshot_returns_none_when_no_row(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_form_freelf_snapshot("Unknown FC") is None


def test_get_team_form_freelf_snapshot_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_team_form_freelf_snapshot("Arsenal") is None


def test_get_team_form_freelf_snapshot_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_team_form_freelf_snapshot("Arsenal") is None


def test_get_team_form_freelf_snapshot_filters_by_canonical_name():
    import inspect

    source = inspect.getsource(q.get_team_form_freelf_snapshot)
    assert '.eq("team_name_canonical"' in source


def test_upsert_team_form_freelf_writes_with_correct_conflict_key(monkeypatch):
    calls: list = []

    class _UpsertClient:
        def table(self, name):
            assert name == "freelf_team_form_snapshot"
            return _FakeUpsertQuery(calls)

    monkeypatch.setattr(q, "get_client", lambda: _UpsertClient())
    ok = q.upsert_team_form_freelf("Arsenal", 10, 5, 3, 2, 20, 8, 18, 3, "")
    assert ok is True
    upsert_call = next(c for c in calls if c[0] == "upsert")
    payload, on_conflict = upsert_call[1], upsert_call[2]
    assert payload["team_name_canonical"] == "Arsenal"
    assert payload["played"] == 10
    assert payload["form"] == ""
    assert payload["source_provider"] == "freelivefootball"
    assert on_conflict == "team_name_canonical"


def test_upsert_team_form_freelf_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_team_form_freelf("Arsenal", 10, 5, 3, 2, 20, 8, 18, 3, "") is False


def test_upsert_team_form_freelf_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.upsert_team_form_freelf("Arsenal", 10, 5, 3, 2, 20, 8, 18, 3, "") is False
