"""
================================================================================
FOOTBALL ORACLE — Weather Forecast Adapter (R-Sync-5, ADR-039)
================================================================================
A patra implementare reală a `SyncAdapter` (sync_adapter.py, R-Sync-1) —
prognoză/condiții meteo per pereche (oraș, dată). Înlocuiește apelul live,
necondiționat, din `oracle_engine.evaluate_match()`
(`self.api.get_weather(city, kickoff_date)`) cu un flux
fetch → normalize → validate → persist, rulat DOAR de Sync Layer
(`sync/sync_weather_forecast.py`), niciodată de Oracle Engine.

`fetch()` reutilizează EXACT `oracle_api.get_weather()` (deja publică,
deja funcțională — fetch + calcul penalizare xG într-un singur loc) — nu
se rescrie logica de calcul a penalizării (ADR-039 Principiul 4, decizie
explicită proprietar produs: „Business Logic rămâne într-un singur loc").

`validate()` respinge explicit valorile de `city` evident greșite —
gol sau identice cu numele unei ligi cunoscute (bug demonstrat: Odds API,
sursă PRIMARĂ de descoperire, produce mereu `venue_city=""`, care cade pe
`city = league`, trimițând literalmente „Premier League" ca oraș).

[LIMITĂ RECUNOSCUTĂ EXPLICIT, nu ascunsă] NU detectează generic „nume de
stadion" sau „valoare evident negeografică" (ex. „Old Trafford", „Camp
Nou") — un astfel de detector ar necesita exact tipul de resolver
geografic pe care proprietarul produsului a decis explicit să NU-l
introducă acum (Canonical City Resolution, tratat ca proiect separat dacă
devine necesar). Cazul concret cunoscut (TheSportsDB `strVenue` populat
greșit drept `venue_city`) a fost reparat la SURSĂ
(`oracle_api._parse_tsdb_event()`, lăsat gol în loc de aproximat) — nu
prin pattern-matching downstream, care ar fi fost un mini-resolver
informal, nu o validare.
================================================================================
"""
from __future__ import annotations

import logging
from typing import Any

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.WeatherForecast")


class WeatherForecastAdapter(SyncAdapter):
    provider_id = "weatherapi"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> dict | None:
        """`params`: `{"city", "kickoff_date"}`. Delegă integral la
        `get_weather()` — inclusiv calculul `xg_penalty`/`description`,
        nerecalculat aici."""
        city = params["city"]
        kickoff_date = params["kickoff_date"]
        weather = self._api.get_weather(city, kickoff_date)
        return {"city": city, "kickoff_date": kickoff_date, **weather}

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        """Un `fetch()` = o pereche (oraș, dată) = o înregistrare —
        spre deosebire de R-Sync-3/4 (un fetch → multe echipe), aici
        granularitatea sursei (WeatherAPI, o cerere per oraș+dată) e deja
        1:1 cu cheia de persistare."""
        if not raw_payload:
            return []
        return [{
            "city":         raw_payload.get("city", ""),
            "kickoff_date": raw_payload.get("kickoff_date", ""),
            "temp_c":       raw_payload.get("temp_c"),
            "condition":    raw_payload.get("condition"),
            "wind_kph":     raw_payload.get("wind_kph"),
            "precip_mm":    raw_payload.get("precip_mm"),
            "humidity":     raw_payload.get("humidity"),
            "xg_penalty":   raw_payload.get("xg_penalty", 0.0),
            "description":  raw_payload.get("description", ""),
        }]

    def validate(self, records: list[dict]) -> list[dict]:
        """Respinge, nu aruncă excepție (Regula #8: mai bine „necunoscut"
        decât o valoare geografic greșită persistată ca și cum ar fi
        corectă). Decizie explicită, proprietar produs — respinge:
        (1) `city` gol; (2) `kickoff_date` gol; (3) `city` identic
        (case-insensitive) cu numele unei ligi cunoscute
        (`mappings.LEAGUE_PROVIDERS`) — bug-ul demonstrat al fallback-ului
        `city = venue_city or league`."""
        from mappings import LEAGUE_PROVIDERS
        known_league_names = {lg.strip().lower() for lg in LEAGUE_PROVIDERS}

        valid: list[dict] = []
        for r in records:
            city = (r.get("city") or "").strip()
            kickoff_date = (r.get("kickoff_date") or "").strip()
            if not city:
                logger.warning("[WeatherForecastAdapter] city gol, exclus: %r", r)
                continue
            if not kickoff_date:
                logger.warning("[WeatherForecastAdapter] kickoff_date gol, exclus: %r", r)
                continue
            if city.lower() in known_league_names:
                logger.warning(
                    "[WeatherForecastAdapter] city='%s' e de fapt un nume de ligă, exclus: %r",
                    city, r,
                )
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_weather_forecast

        ok = True
        for r in records:
            success = upsert_weather_forecast(
                r["city"], r["kickoff_date"],
                r.get("temp_c"), r.get("condition"), r.get("wind_kph"),
                r.get("precip_mm"), r.get("humidity"), r.get("xg_penalty", 0.0), r.get("description"),
            )
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] Fără concept de coverage — WeatherAPI
        e un provider public, universal (fără restricții per ligă/plan).
        Suprascrierea de mai jos (True, identică cu default-ul din
        SyncAdapter) există explicit, nu implicit — tiparul din
        `elo_ratings_adapter.coverage_check()` (R-Sync-4)."""
        return True
