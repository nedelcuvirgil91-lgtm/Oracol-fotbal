"""Teste pentru ADR-039 / R-Sync-5 — database.queries.get_weather_forecast()/
upsert_weather_forecast(), sursa canonică Database-First pentru
prognoza/condițiile meteo per pereche (oraș, dată).

Verifică proprietățile cerute explicit:
(1) citire STRICT din `weather_forecast_cache`, niciun apel de provider;
(2) cheia e (city, kickoff_date), NU per meci/echipă;
(3) `upsert_weather_forecast` scrie prin `on_conflict="city,kickoff_date"`;
(4) degradare fără excepție la client absent / eroare de rețea."""
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
        if name != "weather_forecast_cache":
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeSelectQuery(self._rows, self.calls) if self._rows is not None else _FakeUpsertQuery(self.calls)


def test_get_weather_forecast_returns_row_when_present(monkeypatch):
    row = {"city": "London", "kickoff_date": "2026-08-01", "xg_penalty": 0.04}
    fake = _FakeClient(rows=[row])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    out = q.get_weather_forecast("London", "2026-08-01")
    assert out == row


def test_get_weather_forecast_returns_none_when_no_row(monkeypatch):
    fake = _FakeClient(rows=[])
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_weather_forecast("Unknown City", "2026-08-01") is None


def test_get_weather_forecast_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_weather_forecast("London", "2026-08-01") is None


def test_get_weather_forecast_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_weather_forecast("London", "2026-08-01") is None


def test_get_weather_forecast_filters_by_city_and_kickoff_date():
    import inspect

    source = inspect.getsource(q.get_weather_forecast)
    assert '.eq("city"' in source
    assert '.eq("kickoff_date"' in source


def test_upsert_weather_forecast_writes_with_correct_conflict_key(monkeypatch):
    calls: list = []

    class _UpsertClient:
        def table(self, name):
            assert name == "weather_forecast_cache"
            return _FakeUpsertQuery(calls)

    monkeypatch.setattr(q, "get_client", lambda: _UpsertClient())
    ok = q.upsert_weather_forecast(
        "London", "2026-08-01", 18.0, "Rain", 20.0, 6.0, 80, 0.04, "light rain",
    )
    assert ok is True
    upsert_call = next(c for c in calls if c[0] == "upsert")
    payload, on_conflict = upsert_call[1], upsert_call[2]
    assert payload["city"] == "London"
    assert payload["kickoff_date"] == "2026-08-01"
    assert payload["xg_penalty"] == 0.04
    assert payload["source_provider"] == "weatherapi"
    assert on_conflict == "city,kickoff_date"


def test_upsert_weather_forecast_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.upsert_weather_forecast("London", "2026-08-01", None, None, None, None, None, 0.0, None) is False


def test_upsert_weather_forecast_degrades_gracefully_on_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("simulated network failure")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.upsert_weather_forecast("London", "2026-08-01", None, None, None, None, None, 0.0, None) is False
