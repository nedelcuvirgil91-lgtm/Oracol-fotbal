"""Teste pentru weather_forecast_adapter.py (R-Sync-5, ADR-039).

A patra implementare reală a SyncAdapter — fetch() delegă integral la
FootballOracleAPI.get_weather() (Provider fals, injectat, fără rețea
reală); xg_penalty/description NU sunt recalculate, doar transportate."""
from __future__ import annotations

from weather_forecast_adapter import WeatherForecastAdapter


class _FakeOracleApi:
    def __init__(self, weather=None):
        self._weather = weather if weather is not None else {
            "temp_c": 18.0, "condition": "Rain", "wind_kph": 20.0,
            "precip_mm": 6.0, "humidity": 80, "xg_penalty": 0.04,
            "description": "🌧️  Rain | light rain → xG -4%",
        }
        self.calls: list = []

    def get_weather(self, city, match_date=None):
        self.calls.append(("get_weather", city, match_date))
        return dict(self._weather)


def test_fetch_delegates_to_api_and_embeds_identity():
    fake = _FakeOracleApi()
    adapter = WeatherForecastAdapter(api=fake)
    raw = adapter.fetch({"city": "London", "kickoff_date": "2026-08-01"})
    assert raw["city"] == "London"
    assert raw["kickoff_date"] == "2026-08-01"
    assert raw["xg_penalty"] == 0.04
    assert ("get_weather", "London", "2026-08-01") in fake.calls


def test_normalize_handles_none_payload():
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    assert adapter.normalize(None) == []


def test_normalize_produces_one_record_per_call():
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({"city": "London", "kickoff_date": "2026-08-01"})
    records = adapter.normalize(raw)
    assert len(records) == 1
    rec = records[0]
    assert rec["city"] == "London"
    assert rec["kickoff_date"] == "2026-08-01"
    assert rec["xg_penalty"] == 0.04
    assert rec["description"] == "🌧️  Rain | light rain → xG -4%"


def test_normalize_never_recalculates_xg_penalty():
    """Regresie directă pe decizia explicită: xg_penalty persistat EXACT
    cum îl calculează get_weather(), niciodată rederivat din
    temp_c/wind_kph/precip_mm în adaptor."""
    fake = _FakeOracleApi(weather={
        "temp_c": 40.0, "condition": "Clear", "wind_kph": 100.0,
        "precip_mm": 0.0, "humidity": 10, "xg_penalty": 0.0,
        "description": "valoare neconforma cu conditiile brute, deliberat, pentru test",
    })
    adapter = WeatherForecastAdapter(api=fake)
    raw = adapter.fetch({"city": "London", "kickoff_date": "2026-08-01"})
    records = adapter.normalize(raw)
    assert records[0]["xg_penalty"] == 0.0  # exact ce a intors get_weather(), nu recalculat


def test_validate_rejects_empty_city():
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    records = [{"city": "", "kickoff_date": "2026-08-01", "xg_penalty": 0.0}]
    assert adapter.validate(records) == []


def test_validate_rejects_empty_kickoff_date():
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    records = [{"city": "London", "kickoff_date": "", "xg_penalty": 0.0}]
    assert adapter.validate(records) == []


def test_validate_rejects_city_that_is_actually_a_league_name():
    """Regresie directă pe bug-ul demonstrat în audit: Odds API produce
    mereu venue_city="" -> fallback pe league -> "Premier League" trimis
    ca oraș. validate() trebuie să respingă asta explicit."""
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    records = [
        {"city": "Premier League", "kickoff_date": "2026-08-01", "xg_penalty": 0.0},
        {"city": "premier league", "kickoff_date": "2026-08-01", "xg_penalty": 0.0},  # case-insensitive
    ]
    assert adapter.validate(records) == []


def test_validate_accepts_real_city():
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    records = [{"city": "London", "kickoff_date": "2026-08-01", "xg_penalty": 0.04}]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["city"] == "London"


def test_persist_calls_upsert_weather_forecast(monkeypatch):
    calls = []

    def _fake_upsert(city, kickoff_date, temp_c, condition, wind_kph, precip_mm, humidity, xg_penalty, description):
        calls.append((city, kickoff_date, xg_penalty))
        return True

    monkeypatch.setattr("database.queries.upsert_weather_forecast", _fake_upsert)
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    ok = adapter.persist([{
        "city": "London", "kickoff_date": "2026-08-01",
        "temp_c": 18.0, "condition": "Rain", "wind_kph": 20.0,
        "precip_mm": 6.0, "humidity": 80, "xg_penalty": 0.04, "description": "rain",
    }])
    assert ok is True
    assert calls == [("London", "2026-08-01", 0.04)]


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    def _fake_upsert(city, kickoff_date, temp_c, condition, wind_kph, precip_mm, humidity, xg_penalty, description):
        return city == "London"

    monkeypatch.setattr("database.queries.upsert_weather_forecast", _fake_upsert)
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    ok = adapter.persist([
        {"city": "London", "kickoff_date": "2026-08-01", "xg_penalty": 0.0},
        {"city": "Paris", "kickoff_date": "2026-08-01", "xg_penalty": 0.0},
    ])
    assert ok is False


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    calls = []

    def _fake_upsert(city, kickoff_date, temp_c, condition, wind_kph, precip_mm, humidity, xg_penalty, description):
        calls.append(city)
        return True

    monkeypatch.setattr("database.queries.upsert_weather_forecast", _fake_upsert)
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())

    raw = adapter.fetch({"city": "London", "kickoff_date": "2026-08-01"})
    records = adapter.normalize(raw)
    records = adapter.validate(records)
    ok = adapter.persist(records)

    assert ok is True
    assert calls == ["London"]


def test_coverage_check_returns_true_deliberately():
    adapter = WeatherForecastAdapter(api=_FakeOracleApi())
    assert adapter.coverage_check({"city": "orice"}) is True
    assert "coverage_check" in WeatherForecastAdapter.__dict__
