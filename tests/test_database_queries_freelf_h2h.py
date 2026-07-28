"""Teste pentru ADR-039 / R-Sync-9 — database.queries.get_freelf_h2h_snapshot()/
upsert_freelf_h2h_snapshot()/get_freelf_fixtures_needing_h2h(), sursa
canonică Database-First pentru H2H Free Live Football.

Verifică proprietățile cerute explicit:
(1) citire STRICT din `freelf_h2h_snapshot`, niciun apel de provider;
(2) cheia e ORIENTATĂ (home_team_canonical, away_team_canonical);
(3) `upsert_freelf_h2h_snapshot` scrie prin
    `on_conflict=home_team_canonical,away_team_canonical`;
(4) `get_freelf_fixtures_needing_h2h` citește din `scheduled_fixtures`,
    doar rânduri cu freelf_event_id populat;
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


class _FakeUpsertQuery:
    def __init__(self, calls):
        self._calls = calls

    def upsert(self, payload, on_conflict=None):
        self._calls.append(("upsert", payload, on_conflict)); return self

    def execute(self):
        return _FakeResult([])


class _FakeClient:
    def __init__(self, rows=None, table_name="freelf_h2h_snapshot"):
        self._rows = rows
        self._table_name = table_name
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        if name != self._table_name:
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeSelectQuery(self._rows, self.calls) if self._rows is not None else _FakeUpsertQuery(self.calls)


# ── get_freelf_h2h_snapshot ───────────────────────────────────────────────

def test_get_freelf_h2h_snapshot_returns_row_when_present(monkeypatch):
    row = {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
           "meetings": 3, "home_wins": 2, "draws": 1, "away_wins": 0}
    fake = _FakeClient(rows=[row])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_freelf_h2h_snapshot("Arsenal", "Chelsea") == row


def test_get_freelf_h2h_snapshot_returns_none_when_no_row(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_freelf_h2h_snapshot("Arsenal", "Chelsea") is None


def test_get_freelf_h2h_snapshot_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_freelf_h2h_snapshot("Arsenal", "Chelsea") is None


def test_get_freelf_h2h_snapshot_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_freelf_h2h_snapshot("Arsenal", "Chelsea") is None


def test_get_freelf_h2h_snapshot_filters_by_oriented_canonical_names():
    import inspect

    source = inspect.getsource(q.get_freelf_h2h_snapshot)
    assert '.eq("home_team_canonical"' in source
    assert '.eq("away_team_canonical"' in source


# ── upsert_freelf_h2h_snapshot ────────────────────────────────────────────

def test_upsert_freelf_h2h_snapshot_writes_with_correct_conflict_key(monkeypatch):
    calls: list = []

    class _UpsertClient:
        def table(self, name):
            assert name == "freelf_h2h_snapshot"
            return _FakeUpsertQuery(calls)

    monkeypatch.setattr(q, "get_client", lambda: _UpsertClient())
    ok = q.upsert_freelf_h2h_snapshot(
        "Arsenal", "Chelsea", "998877",
        3, 2, 1, 0, 1.5, 0.7, ["H", "D", "H"], 0.1, "H2H (3 meciuri)",
    )
    assert ok is True
    upsert_call = next(c for c in calls if c[0] == "upsert")
    payload, on_conflict = upsert_call[1], upsert_call[2]
    assert payload["home_team_canonical"] == "Arsenal"
    assert payload["away_team_canonical"] == "Chelsea"
    assert payload["freelf_event_id"] == "998877"
    assert payload["meetings"] == 3
    assert payload["last_5"] == ["H", "D", "H"]
    assert payload["source_provider"] == "freelivefootball"
    assert on_conflict == "home_team_canonical,away_team_canonical"


def test_upsert_freelf_h2h_snapshot_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_freelf_h2h_snapshot(
        "Arsenal", "Chelsea", "998877", 3, 2, 1, 0, 1.5, 0.7, [], 0.1, "",
    ) is False


def test_upsert_freelf_h2h_snapshot_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.upsert_freelf_h2h_snapshot(
        "Arsenal", "Chelsea", "998877", 3, 2, 1, 0, 1.5, 0.7, [], 0.1, "",
    ) is False


# ── get_freelf_fixtures_needing_h2h ───────────────────────────────────────

def test_get_freelf_fixtures_needing_h2h_returns_rows(monkeypatch):
    rows = [{"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea",
             "freelf_event_id": "998877"}]
    fake = _FakeClient(rows=rows, table_name="scheduled_fixtures")
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_freelf_fixtures_needing_h2h() == rows


def test_get_freelf_fixtures_needing_h2h_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_freelf_fixtures_needing_h2h() == []


def test_get_freelf_fixtures_needing_h2h_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_freelf_fixtures_needing_h2h() == []


def test_get_freelf_fixtures_needing_h2h_filters_null_event_id():
    import inspect

    source = inspect.getsource(q.get_freelf_fixtures_needing_h2h)
    assert 'is_("freelf_event_id", "null")' in source
