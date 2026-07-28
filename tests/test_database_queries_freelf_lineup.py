"""Teste pentru ADR-039 / R-Sync-10 — database.queries.get_freelf_lineup_snapshot()/
upsert_freelf_lineup_snapshot()/get_upcoming_freelf_fixtures_for_lineup(),
sursa canonică Database-First pentru aliniamente Free Live Football.

Verifică proprietățile cerute explicit:
(1) citire STRICT din `freelf_lineup_snapshot`, niciun apel de provider;
(2) cheia e (home_team_canonical, away_team_canonical, kickoff_date) — un
    singur rând per meci, ambele părți;
(3) `upsert_freelf_lineup_snapshot` scrie prin RPC
    `upsert_freelf_lineup_snapshot_merge`, nu upsert direct;
(4) `get_upcoming_freelf_fixtures_for_lineup` citește din
    `scheduled_fixtures`, doar rânduri cu freelf_event_id populat, în
    fereastra de kickoff;
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

    def limit(self, *a, **kw):
        self._calls.append(("limit", a, kw)); return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        self._calls.append(("is_", a, kw)); return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeRpcQuery:
    def __init__(self, calls):
        self._calls = calls

    def execute(self):
        return _FakeResult([])


class _FakeClient:
    def __init__(self, rows=None, table_name="freelf_lineup_snapshot"):
        self._rows = rows
        self._table_name = table_name
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        if name != self._table_name:
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeSelectQuery(self._rows, self.calls)

    def rpc(self, name, params):
        self.calls.append(("rpc", name, params))
        return _FakeRpcQuery(self.calls)


# ── get_freelf_lineup_snapshot ────────────────────────────────────────────

def test_get_freelf_lineup_snapshot_returns_row_when_present(monkeypatch):
    row = {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
           "kickoff_date": "2026-08-01", "home_confirmed": True, "away_confirmed": False}
    fake = _FakeClient(rows=[row])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_freelf_lineup_snapshot("Arsenal", "Chelsea", "2026-08-01") == row


def test_get_freelf_lineup_snapshot_returns_none_when_no_row(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_freelf_lineup_snapshot("Arsenal", "Chelsea", "2026-08-01") is None


def test_get_freelf_lineup_snapshot_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_freelf_lineup_snapshot("Arsenal", "Chelsea", "2026-08-01") is None


def test_get_freelf_lineup_snapshot_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_freelf_lineup_snapshot("Arsenal", "Chelsea", "2026-08-01") is None


def test_get_freelf_lineup_snapshot_filters_by_canonical_match_identity():
    import inspect

    source = inspect.getsource(q.get_freelf_lineup_snapshot)
    assert '.eq("home_team_canonical"' in source
    assert '.eq("away_team_canonical"' in source
    assert '.eq("kickoff_date"' in source


# ── upsert_freelf_lineup_snapshot ─────────────────────────────────────────

def test_upsert_freelf_lineup_snapshot_calls_merge_rpc(monkeypatch):
    calls: list = []

    class _RpcClient:
        def rpc(self, name, params):
            calls.append((name, params))
            return _FakeRpcQuery(calls)

    monkeypatch.setattr(q, "get_client", lambda: _RpcClient())
    ok = q.upsert_freelf_lineup_snapshot(
        "Arsenal", "Chelsea", "2026-08-01", "998877",
        True, "4-3-3", [{"id": 1, "name": "X"}],
        False, "", [],
    )
    assert ok is True
    rpc_name, params = calls[0]
    assert rpc_name == "upsert_freelf_lineup_snapshot_merge"
    assert params["p_home_team_canonical"] == "Arsenal"
    assert params["p_away_team_canonical"] == "Chelsea"
    assert params["p_kickoff_date"] == "2026-08-01"
    assert params["p_freelf_event_id"] == "998877"
    assert params["p_home_confirmed"] is True
    assert params["p_home_formation"] == "4-3-3"
    assert params["p_home_unavailable"] == [{"id": 1, "name": "X"}]
    assert params["p_away_confirmed"] is False


def test_upsert_freelf_lineup_snapshot_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_freelf_lineup_snapshot(
        "Arsenal", "Chelsea", "2026-08-01", "998877", True, "", [], False, "", [],
    ) is False


def test_upsert_freelf_lineup_snapshot_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def rpc(self, name, params):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.upsert_freelf_lineup_snapshot(
        "Arsenal", "Chelsea", "2026-08-01", "998877", True, "", [], False, "", [],
    ) is False


# ── get_upcoming_freelf_fixtures_for_lineup ───────────────────────────────

def test_get_upcoming_freelf_fixtures_for_lineup_returns_rows(monkeypatch):
    rows = [{"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
             "kickoff_date": "2026-08-01", "kickoff_utc": "2026-08-01T18:00:00Z",
             "freelf_event_id": "998877"}]
    fake = _FakeClient(rows=rows, table_name="scheduled_fixtures")
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_upcoming_freelf_fixtures_for_lineup() == rows


def test_get_upcoming_freelf_fixtures_for_lineup_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_upcoming_freelf_fixtures_for_lineup() == []


def test_get_upcoming_freelf_fixtures_for_lineup_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_upcoming_freelf_fixtures_for_lineup() == []


def test_get_upcoming_freelf_fixtures_for_lineup_filters_null_event_id():
    import inspect

    source = inspect.getsource(q.get_upcoming_freelf_fixtures_for_lineup)
    assert 'is_("freelf_event_id", "null")' in source
    assert "kickoff_utc" in source
