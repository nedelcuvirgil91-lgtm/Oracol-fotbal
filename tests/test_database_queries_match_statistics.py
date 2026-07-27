"""Teste pentru database.queries.get_finished_matches_missing_stats()
(Sprint 1, ADR-039). Verifică ambele moduri: fereastră implicită
(days_back, sincronizare zilnică) și fereastră explicită (date_from/
date_to/league, reutilizat de backfill-ul istoric FreeLF)."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    def select(self, *a, **kw):
        self._calls.append(("select", a, kw)); return self

    def not_(self):
        return self

    def is_(self, *a, **kw):
        self._calls.append(("is_", a, kw)); return self

    def gte(self, *a, **kw):
        self._calls.append(("gte", a, kw)); return self

    def lte(self, *a, **kw):
        self._calls.append(("lte", a, kw)); return self

    def eq(self, *a, **kw):
        self._calls.append(("eq", a, kw)); return self

    def order(self, *a, **kw):
        self._calls.append(("order", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append(("limit", a, kw)); return self

    def execute(self):
        return _FakeResult(self._rows)


class _NotProxy:
    """`.not_.is_(...)` — supabase-py expune `.not_` ca proprietate, nu
    metodă; proxy minimal care redirecționează la același obiect query."""
    def __init__(self, query):
        self._query = query

    def is_(self, *a, **kw):
        return self._query.is_(*a, **kw)


class _FakeQueryWithNotProperty(_FakeQuery):
    @property
    def not_(self):
        return _NotProxy(self)


class _FakeClient:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        assert name == "match_history"
        return _FakeQueryWithNotProperty(self._rows, self.calls)


def test_returns_rows_from_client(monkeypatch):
    rows = [{"home_team": "Arsenal", "away_team": "Chelsea",
             "kickoff_date": "2026-01-01", "league": "Premier League"}]
    fake = _FakeClient(rows=rows)
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_finished_matches_missing_stats(days_back=2)
    assert result == rows


def test_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_finished_matches_missing_stats() == []


def test_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")
    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_finished_matches_missing_stats() == []


def test_default_mode_filters_on_actual_home_goals_and_home_possession(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(days_back=5)
    is_calls = [c for c in fake.calls if c[0] == "is_"]
    assert ("actual_home_goals", "null") in [c[1] for c in is_calls]
    assert ("home_possession", "null") in [c[1] for c in is_calls]


def test_explicit_date_range_used_when_provided(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(date_from="2025-05-26", date_to="2025-06-25")
    gte_calls = [c[1] for c in fake.calls if c[0] == "gte"]
    lte_calls = [c[1] for c in fake.calls if c[0] == "lte"]
    assert ("kickoff_date", "2025-05-26") in gte_calls
    assert ("kickoff_date", "2025-06-25") in lte_calls


def test_league_filter_applied_only_when_given(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(date_from="2025-05-26", date_to="2025-06-25", league="Premier League")
    eq_calls = [c[1] for c in fake.calls if c[0] == "eq"]
    assert ("league", "Premier League") in eq_calls


def test_no_league_filter_when_omitted(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(date_from="2025-05-26", date_to="2025-06-25")
    eq_calls = [c for c in fake.calls if c[0] == "eq"]
    assert eq_calls == []


def test_default_days_back_computes_cutoff_relative_to_today(monkeypatch):
    from datetime import date, timedelta
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(days_back=3)
    expected_cutoff = (date.today() - timedelta(days=3)).isoformat()
    gte_calls = [c[1] for c in fake.calls if c[0] == "gte"]
    assert ("kickoff_date", expected_cutoff) in gte_calls
