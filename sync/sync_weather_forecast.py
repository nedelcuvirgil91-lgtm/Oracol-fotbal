"""
================================================================================
FOOTBALL ORACLE — Sync Weather Forecast (R-Sync-5, ADR-039)
================================================================================
Module: sync/sync_weather_forecast.py

Punctul de intrare Sync Layer pentru prognoza meteo (WeatherAPI) —
înlocuiește apelul live, necondiționat, eliminat din
`oracle_engine.evaluate_match()`. Sincronizare pe perechi (oraș, dată)
distincte, extrase din meciurile din următoarele `days_ahead` zile (audit
§4: „de câteva ori/zi, doar pentru meciuri în următoarele 48h" —
`days_ahead=2` implicit).

Descoperirea meciurilor („ce meciuri există, cu ce oraș/dată") folosește
azi calea EXISTENTĂ (`oracle_api.FootballOracleAPI.get_matches_for_week`)
— la fel ca `sync_team_health.py` (R-Sync-2); migrarea descoperirii de
meciuri la Supabase e R-Sync-7, separat, neatinsă aici. Acest script
rulează DIN Sync Layer, unde apelul către provideri e explicit permis
(ADR-039, principiul 1).

Nicio pre-filtrare a orașelor evident greșite aici — responsabilitatea
aceea e exclusiv a `WeatherForecastAdapter.validate()` (un singur loc,
nu duplicat).

Rulare:
    python -m sync.sync_weather_forecast [--days-ahead N]
    (sau apelat programatic din sync/run_daily.py — neatins aici, cablarea
    în orchestrarea zilnică rămâne un pas separat, ulterior)
================================================================================
"""
from __future__ import annotations

import argparse
import logging

from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator
from weather_forecast_adapter import WeatherForecastAdapter

logger = logging.getLogger("FootballOracle.Sync.WeatherForecast")


def _pairs_needing_sync(days_ahead: int = 2) -> list[tuple[str, str]]:
    """Perechi (oraș, dată) distincte din meciurile din următoarele
    `days_ahead` zile — nicio filtrare aici, doar deduplicare."""
    from oracle_api import FootballOracleAPI

    api = FootballOracleAPI()
    matches = api.get_matches_for_week(days_ahead=days_ahead)
    pairs: set[tuple[str, str]] = set()
    for m in matches:
        city = m.get("venue_city", "") or ""
        kickoff_date = m.get("kickoff_date", "") or ""
        pairs.add((city, kickoff_date))
    return sorted(pairs)


def _make_task_runner(adapter: WeatherForecastAdapter, city: str, kickoff_date: str):
    def _run() -> None:
        raw = adapter.fetch({"city": city, "kickoff_date": kickoff_date})
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run(days_ahead: int = 2) -> list:
    adapter = WeatherForecastAdapter()
    orchestrator = get_sync_orchestrator()

    pairs = _pairs_needing_sync(days_ahead)
    logger.info("[WeatherForecast] %d perechi (oraș, dată) de sincronizat", len(pairs))

    for city, kickoff_date in pairs:
        task_name = f"weather_forecast:{city}:{kickoff_date}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P2,
            run=_make_task_runner(adapter, city, kickoff_date),
            # Fara concept de coverage — vezi weather_forecast_adapter.coverage_check().
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare prognoză meteo (WeatherAPI)")
    parser.add_argument("--days-ahead", type=int, default=2)
    args = parser.parse_args()

    results = run(days_ahead=args.days_ahead)
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
