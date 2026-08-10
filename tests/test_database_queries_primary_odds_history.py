"""Teste pentru database.queries.get_primary_odds_from_history()
(corectare ADR-043 §Decizie pct. 3, 2026-08-10) — fără rețea, Supabase
mock-uit prin monkeypatch.

Verifică: citește valoarea persistată în odds_history (closing, cu
fallback la opening dacă piața nu s-a închis încă) pentru fixture-urile
cerute; alege cea mai recentă captură când există mai multe case de
pariuri; nu aproximează niciodată o pereche incompletă de cote."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeSelectQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **kw):
        return self

    def in_(self, *a, **kw):
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, rows=None):
        self._rows = rows or []

    def table(self, name):
        assert name == "odds_history"
        return _FakeSelectQuery(self._rows)


def test_returns_empty_dict_for_empty_input(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient())
    assert q.get_primary_odds_from_history([]) == {}


def test_returns_empty_dict_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_primary_odds_from_history(["fx1"]) == {}


def test_prefers_closing_odds_when_present(monkeypatch):
    fake = _FakeClient(rows=[{
        "fixture_id": "fx1", "bookmaker": "bet365",
        "closing_home": 1.8, "closing_draw": 3.4, "closing_away": 4.5,
        "opening_home": 2.0, "opening_draw": 3.3, "opening_away": 4.0,
        "closing_fetched_at": "2026-08-09T10:00:00Z", "opening_fetched_at": "2026-08-05T10:00:00Z",
    }])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_primary_odds_from_history(["fx1"])
    assert result["fx1"] == {"home": 1.8, "draw": 3.4, "away": 4.5, "bookmaker": "bet365"}


def test_falls_back_to_opening_odds_when_market_not_closed_yet(monkeypatch):
    fake = _FakeClient(rows=[{
        "fixture_id": "fx1", "bookmaker": "bet365",
        "closing_home": None, "closing_draw": None, "closing_away": None,
        "opening_home": 2.0, "opening_draw": 3.3, "opening_away": 4.0,
        "closing_fetched_at": None, "opening_fetched_at": "2026-08-05T10:00:00Z",
    }])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_primary_odds_from_history(["fx1"])
    assert result["fx1"] == {"home": 2.0, "draw": 3.3, "away": 4.0, "bookmaker": "bet365"}


def test_skips_row_with_incomplete_odds_never_approximates(monkeypatch):
    fake = _FakeClient(rows=[{
        "fixture_id": "fx1", "bookmaker": "bet365",
        "closing_home": None, "closing_draw": None, "closing_away": None,
        "opening_home": 2.0, "opening_draw": None, "opening_away": 4.0,
        "closing_fetched_at": None, "opening_fetched_at": "2026-08-05T10:00:00Z",
    }])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_primary_odds_from_history(["fx1"]) == {}


def test_picks_most_recently_fetched_row_among_multiple_bookmakers(monkeypatch):
    fake = _FakeClient(rows=[
        {"fixture_id": "fx1", "bookmaker": "bet365",
         "closing_home": 1.8, "closing_draw": 3.4, "closing_away": 4.5,
         "opening_home": None, "opening_draw": None, "opening_away": None,
         "closing_fetched_at": "2026-08-07T10:00:00Z", "opening_fetched_at": None},
        {"fixture_id": "fx1", "bookmaker": "Unibet",
         "closing_home": 1.9, "closing_draw": 3.3, "closing_away": 4.3,
         "opening_home": None, "opening_draw": None, "opening_away": None,
         "closing_fetched_at": "2026-08-09T10:00:00Z", "opening_fetched_at": None},
    ])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_primary_odds_from_history(["fx1"])
    assert result["fx1"]["bookmaker"] == "Unibet"


def test_degrades_gracefully_when_query_raises(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_primary_odds_from_history(["fx1"]) == {}
