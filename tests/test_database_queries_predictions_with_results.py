"""Teste pentru database.queries.get_predictions_with_results() (Sprint 0 —
Stabilizare, Etapa 3) — citire read-only, match_history cu predicție ȘI
rezultat real."""
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


def test_get_predictions_with_results_returns_rows(monkeypatch):
    rows = [{"league": "Premier League", "home_team": "A", "away_team": "B",
             "kickoff_date": "2026-07-20", "prob_home_pred": 0.6, "prob_draw_pred": 0.3,
             "prob_away_pred": 0.1, "actual_result": "H"}]
    fake = _FakeClient(rows=rows)
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_predictions_with_results() == rows


def test_get_predictions_with_results_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_predictions_with_results() == []


def test_get_predictions_with_results_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_predictions_with_results() == []


def test_get_predictions_with_results_filters_by_prob_and_actual_result():
    import inspect

    source = inspect.getsource(q.get_predictions_with_results)
    assert 'not_.is_("prob_home_pred", "null")' in source
    assert 'not_.is_("actual_result", "null")' in source


def test_get_predictions_with_results_applies_days_back_window(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_predictions_with_results(days_back=30)

    gte_calls = [c for c in fake.calls if c[0] == "gte"]
    assert len(gte_calls) == 1
    assert gte_calls[0][1][0] == "kickoff_date"


def test_get_predictions_with_results_no_window_when_days_back_none(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_predictions_with_results(days_back=None)

    assert not any(c[0] == "gte" for c in fake.calls)
