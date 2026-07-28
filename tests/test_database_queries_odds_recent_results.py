"""Teste pentru ADR-039 / R-Sync-6 — database.queries.get_team_recent_form_oddsapi()/
get_h2h_from_odds_recent()/upsert_odds_recent_result(), sursa canonică
UNICĂ (audit R-Sync-6, opțiunea A) din care derivă atât forma cât și H2H."""
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

    def or_(self, *a, **kw):
        self._calls.append(("or_", a, kw)); return self

    def order(self, *a, **kw):
        self._calls.append(("order", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append(("limit", a, kw)); return self

    def gte(self, *a, **kw):
        self._calls.append(("gte", a, kw)); return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        self._calls.append(("is_", a, kw)); return self

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
        self._rows = rows
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        if name != "odds_api_recent_results":
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeSelectQuery(self._rows, self.calls) if self._rows is not None else _FakeUpsertQuery(self.calls)


def test_get_team_recent_form_oddsapi_returns_rows(monkeypatch):
    rows = [{"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
             "kickoff_date": "2026-08-01", "home_score": 2, "away_score": 1}]
    fake = _FakeClient(rows=rows)
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_recent_form_oddsapi("Arsenal") == rows


def test_get_team_recent_form_oddsapi_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_team_recent_form_oddsapi("Arsenal") == []


def test_get_team_recent_form_oddsapi_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_team_recent_form_oddsapi("Arsenal") == []


def test_get_team_recent_form_oddsapi_filters_by_either_side():
    import inspect

    source = inspect.getsource(q.get_team_recent_form_oddsapi)
    assert "home_team_canonical.eq" in source and "away_team_canonical.eq" in source


def test_get_h2h_from_odds_recent_returns_rows(monkeypatch):
    rows = [{"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
             "kickoff_date": "2026-08-01", "home_score": 2, "away_score": 1}]
    fake = _FakeClient(rows=rows)
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_h2h_from_odds_recent("Arsenal", "Chelsea") == rows


def test_get_h2h_from_odds_recent_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_h2h_from_odds_recent("Arsenal", "Chelsea") == []


def test_get_h2h_from_odds_recent_uses_symmetric_pair_key():
    import inspect

    source = inspect.getsource(q.get_h2h_from_odds_recent)
    assert "and(home_team_canonical.eq.{home},away_team_canonical.eq.{away})" in source
    assert "and(home_team_canonical.eq.{away},away_team_canonical.eq.{home})" in source


def test_upsert_odds_recent_result_writes_with_correct_conflict_key(monkeypatch):
    calls: list = []

    class _UpsertClient:
        def table(self, name):
            assert name == "odds_api_recent_results"
            return _FakeUpsertQuery(calls)

    monkeypatch.setattr(q, "get_client", lambda: _UpsertClient())
    ok = q.upsert_odds_recent_result("Arsenal", "Chelsea", "2026-08-01", "Premier League", 2, 1)
    assert ok is True
    upsert_call = next(c for c in calls if c[0] == "upsert")
    payload, on_conflict = upsert_call[1], upsert_call[2]
    assert payload["home_team_canonical"] == "Arsenal"
    assert payload["away_team_canonical"] == "Chelsea"
    assert payload["kickoff_date"] == "2026-08-01"
    assert payload["source_provider"] == "oddsapi"
    assert on_conflict == "home_team_canonical,away_team_canonical,kickoff_date"


def test_upsert_odds_recent_result_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_odds_recent_result("Arsenal", "Chelsea", "2026-08-01", "PL", 2, 1) is False


def test_upsert_odds_recent_result_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.upsert_odds_recent_result("Arsenal", "Chelsea", "2026-08-01", "PL", 2, 1) is False


# ── get_recent_odds_results (Sprint 0 — Stabilizare, Etapa 2) ──────────────

def test_get_recent_odds_results_returns_rows(monkeypatch):
    rows = [{"home_team_canonical": "Portland Timbers", "away_team_canonical": "Real Salt Lake",
             "kickoff_date": "2026-07-26", "league": "MLS", "home_score": 2, "away_score": 1}]
    fake = _FakeClient(rows=rows)
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_recent_odds_results() == rows


def test_get_recent_odds_results_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_recent_odds_results() == []


def test_get_recent_odds_results_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_recent_odds_results() == []


def test_get_recent_odds_results_filters_out_incomplete_scores():
    """Doar rânduri cu scor complet — un rând fără home_score/away_score
    nu poate produce actual_result valid, filtrat la sursă (query-ul
    Supabase, nu la apelant)."""
    import inspect

    source = inspect.getsource(q.get_recent_odds_results)
    assert 'not_.is_("home_score", "null")' in source
    assert 'not_.is_("away_score", "null")' in source
