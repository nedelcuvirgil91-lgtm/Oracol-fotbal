"""Teste pentru database.queries.get_odds_fallback_for_missing_fixtures()
(ADR-043 §Decizie pct. 3) — fără rețea, Supabase mock-uit prin monkeypatch.

Verifică exact regula de citire: `odds_history` (Frozen) are prioritate
necondiționată — un fixture_id cu orice rând acolo NU primește niciodată
fallback, indiferent ce conține `odds_fallback_flashscore` pentru el.
DOAR fixture-urile complet absente din `odds_history` sunt căutate în
fallback, iar dintre mai multe case de pariuri se alege cea mai recentă
captură (`captured_at`)."""
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
    def __init__(self, odds_history_rows=None, fallback_rows=None):
        self._tables = {
            "odds_history": odds_history_rows or [],
            "odds_fallback_flashscore": fallback_rows or [],
        }
        self.table_calls: list[str] = []

    def table(self, name):
        self.table_calls.append(name)
        return _FakeSelectQuery(self._tables.get(name, []))


def test_returns_empty_dict_for_empty_input(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient())
    assert q.get_odds_fallback_for_missing_fixtures([]) == {}


def test_returns_empty_dict_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_odds_fallback_for_missing_fixtures(["fx1"]) == {}


def test_no_fallback_query_when_all_fixtures_already_covered_by_primary(monkeypatch):
    fake = _FakeClient(odds_history_rows=[{"fixture_id": "fx1"}, {"fixture_id": "fx2"}])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_odds_fallback_for_missing_fixtures(["fx1", "fx2"])
    assert result == {}
    assert "odds_fallback_flashscore" not in fake.table_calls


def test_fixture_with_primary_row_never_gets_fallback_even_if_present(monkeypatch):
    fake = _FakeClient(
        odds_history_rows=[{"fixture_id": "fx1"}],
        fallback_rows=[{"fixture_id": "fx1", "bookmaker": "bet365", "home": 1.5, "draw": 3.5,
                         "away": 6.0, "captured_at": "2026-08-04T10:00:00Z"}],
    )
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_odds_fallback_for_missing_fixtures(["fx1"])
    assert result == {}


def test_returns_fallback_row_for_fixture_missing_from_primary(monkeypatch):
    fake = _FakeClient(
        odds_history_rows=[],
        fallback_rows=[{"fixture_id": "fx1", "bookmaker": "bet365", "home": 1.5, "draw": 3.5,
                         "away": 6.0, "captured_at": "2026-08-04T10:00:00Z"}],
    )
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_odds_fallback_for_missing_fixtures(["fx1"])
    assert result["fx1"]["bookmaker"] == "bet365"
    assert result["fx1"]["home"] == 1.5


def test_mixed_fixtures_only_missing_ones_queried_and_returned(monkeypatch):
    fake = _FakeClient(
        odds_history_rows=[{"fixture_id": "fx1"}],
        fallback_rows=[{"fixture_id": "fx2", "bookmaker": "bet365", "home": 2.0, "draw": 3.0,
                         "away": 4.0, "captured_at": "2026-08-04T10:00:00Z"}],
    )
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_odds_fallback_for_missing_fixtures(["fx1", "fx2"])
    assert set(result.keys()) == {"fx2"}


def test_picks_most_recently_captured_row_among_multiple_bookmakers(monkeypatch):
    fake = _FakeClient(
        odds_history_rows=[],
        fallback_rows=[
            {"fixture_id": "fx1", "bookmaker": "bet365", "home": 1.5, "draw": 3.5,
             "away": 6.0, "captured_at": "2026-08-04T08:00:00Z"},
            {"fixture_id": "fx1", "bookmaker": "Unibet", "home": 1.6, "draw": 3.4,
             "away": 5.5, "captured_at": "2026-08-04T12:00:00Z"},
        ],
    )
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_odds_fallback_for_missing_fixtures(["fx1"])
    assert result["fx1"]["bookmaker"] == "Unibet"


def test_degrades_gracefully_when_primary_query_raises(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_odds_fallback_for_missing_fixtures(["fx1"]) == {}


def test_degrades_gracefully_when_fallback_query_raises(monkeypatch):
    class _PartialBoom:
        def table(self, name):
            if name == "odds_history":
                return _FakeSelectQuery([])
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _PartialBoom())
    assert q.get_odds_fallback_for_missing_fixtures(["fx1"]) == {}
