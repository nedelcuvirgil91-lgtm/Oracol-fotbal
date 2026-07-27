"""Teste pentru ADR-039 / R-Sync-7a — database.queries.upsert_scheduled_fixture()/
get_scheduled_fixture(). `upsert_scheduled_fixture` e un wrapper SUBȚIRE
peste RPC-ul `upsert_scheduled_fixture_merge` (migrare 023) — TOATĂ
logica FixtureMergePolicy trăiește în SQL, nu aici. Testele de față
verifică DOAR că wrapper-ul trimite corect parametrii, nu logica de merge
(aceea se verifică live, prin Supabase, separat de suita pytest fără
rețea)."""
from __future__ import annotations

import database.queries as q


class _FakeRpcResult:
    def execute(self):
        return None


class _FakeClient:
    def __init__(self):
        self.rpc_calls: list = []

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        return _FakeRpcResult()

    def table(self, name):
        raise AssertionError("upsert_scheduled_fixture nu are voie sa foloseasca .table() direct — doar RPC")


def test_upsert_scheduled_fixture_calls_correct_rpc_name(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    ok = q.upsert_scheduled_fixture("Arsenal", "Chelsea", "2026-08-01", "freelf")
    assert ok is True
    assert fake.rpc_calls[0][0] == "upsert_scheduled_fixture_merge"


def test_upsert_scheduled_fixture_passes_identity_and_provider(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.upsert_scheduled_fixture("Arsenal", "Chelsea", "2026-08-01", "freelf")
    params = fake.rpc_calls[0][1]
    assert params["p_home_team_canonical"] == "Arsenal"
    assert params["p_away_team_canonical"] == "Chelsea"
    assert params["p_kickoff_date"] == "2026-08-01"
    assert params["p_provider_id"] == "freelf"


def test_upsert_scheduled_fixture_passes_freelf_specific_fields(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.upsert_scheduled_fixture(
        "Arsenal", "Chelsea", "2026-08-01", "freelf",
        freelf_event_id="998877", freelf_coverage_level="xg",
    )
    params = fake.rpc_calls[0][1]
    assert params["p_freelf_event_id"] == "998877"
    assert params["p_freelf_coverage_level"] == "xg"
    # Campuri neasignate raman None -> RPC le trateaza ca "lipsa" (DEFAULT NULL SQL)
    assert params["p_tsdb_home_team_id"] is None
    assert params["p_odds_api_event_id"] is None


def test_upsert_scheduled_fixture_passes_shared_governed_fields(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.upsert_scheduled_fixture(
        "Arsenal", "Chelsea", "2026-08-01", "fd",
        league="Premier League", kickoff_utc="2026-08-01T15:00:00Z",
        venue_city="England", status="scheduled",
    )
    params = fake.rpc_calls[0][1]
    assert params["p_league"] == "Premier League"
    assert params["p_kickoff_utc"] == "2026-08-01T15:00:00Z"
    assert params["p_venue_city"] == "England"
    assert params["p_status"] == "scheduled"


def test_upsert_scheduled_fixture_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_scheduled_fixture("Arsenal", "Chelsea", "2026-08-01", "freelf") is False


def test_upsert_scheduled_fixture_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def rpc(self, name, params):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.upsert_scheduled_fixture("Arsenal", "Chelsea", "2026-08-01", "freelf") is False


def test_upsert_scheduled_fixture_never_uses_table_upsert_directly():
    """Regresie directă pe decizia explicită: TOATĂ logica de merge
    trăiește în RPC — funcția nu are voie să facă vreodată
    client.table("scheduled_fixtures").upsert(...) direct (ar ocoli
    FixtureMergePolicy)."""
    import inspect

    source = inspect.getsource(q.upsert_scheduled_fixture)
    assert '.table(' not in source
    assert '.rpc("upsert_scheduled_fixture_merge"' in source


# ── get_scheduled_fixture ─────────────────────────────────────────────────

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


class _FakeSelectClient:
    def __init__(self, rows):
        self._rows = rows
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        assert name == "scheduled_fixtures"
        return _FakeSelectQuery(self._rows, self.calls)


def test_get_scheduled_fixture_returns_row_when_present(monkeypatch):
    row = {"home_team_canonical": "Arsenal", "away_team_canonical": "Chelsea", "kickoff_date": "2026-08-01"}
    fake = _FakeSelectClient(rows=[row])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_scheduled_fixture("Arsenal", "Chelsea", "2026-08-01") == row


def test_get_scheduled_fixture_returns_none_when_no_row(monkeypatch):
    fake = _FakeSelectClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_scheduled_fixture("Arsenal", "Chelsea", "2026-08-01") is None


def test_get_scheduled_fixture_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_scheduled_fixture("Arsenal", "Chelsea", "2026-08-01") is None
