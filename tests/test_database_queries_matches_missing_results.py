"""Teste pentru database.queries.get_matches_missing_results() (Sprint 3,
Pasul 1 — închidere retroactivă Feedback Loop) — citire read-only,
match_history fără actual_result, în trecut."""
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

    def gte(self, *a, **kw):
        self._calls.append(("gte", a, kw)); return self

    def lt(self, *a, **kw):
        self._calls.append(("lt", a, kw)); return self

    def order(self, *a, **kw):
        self._calls.append(("order", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append(("limit", a, kw)); return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        self._calls.append(("is_", a, kw)); return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, rows=None):
        self._rows = rows if rows is not None else []
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        assert name == "match_history"
        return _FakeSelectQuery(self._rows, self.calls)


def test_get_matches_missing_results_returns_rows(monkeypatch):
    rows = [{"id": 1, "home_team": "England", "away_team": "DR Congo",
             "league": "World Cup 2026", "kickoff_date": "2026-07-01"}]
    fake = _FakeClient(rows=rows)
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_matches_missing_results() == rows


def test_get_matches_missing_results_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_matches_missing_results() == []


def test_get_matches_missing_results_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_matches_missing_results() == []


def test_get_matches_missing_results_filters_null_result_and_not_superseded():
    import inspect

    source = inspect.getsource(q.get_matches_missing_results)
    assert 'is_("actual_result", "null")' in source
    assert 'is_("superseded_by", "null")' in source


def test_get_matches_missing_results_applies_days_back_and_before_today(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_matches_missing_results(days_back=30)

    gte_calls = [c for c in fake.calls if c[0] == "gte"]
    lt_calls = [c for c in fake.calls if c[0] == "lt"]
    assert len(gte_calls) == 1 and gte_calls[0][1][0] == "kickoff_date"
    assert len(lt_calls) == 1 and lt_calls[0][1][0] == "kickoff_date"
