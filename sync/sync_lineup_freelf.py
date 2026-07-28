"""
================================================================================
FOOTBALL ORACLE — Sync Lineup Free Live Football (R-Sync-10, ADR-039)
================================================================================
Module: sync/sync_lineup_freelf.py

Punctul de intrare Sync Layer pentru aliniamente + absențe confirmate Free
Live Football — înlocuiește ultimul apel live rămas care MODIFICA efectiv
predicția servită (`injury_manager.get_lineup_absences()`,
`oracle_engine.py`). Determină fixture-urile de sincronizat citind
`scheduled_fixtures` (`database.queries.get_upcoming_freelf_fixtures_for_
lineup()`) — NU mai caută event_id-ul live; vine deja gata rezolvat din
`FreelfFixtureAdapter` (R-Sync-7a).

Cadență DEDICATĂ — NU parte din `run_daily.py` (o dată/zi, prea rar pentru
date care se confirmă aproape de kickoff). Rulează separat, la 15 minute
(`.github/workflows/lineup_sync.yml`), doar pentru fixture-urile din
fereastra apropiată de kickoff (implicit T-15min .. T+240min, fereastră
deliberat largă — vezi `get_upcoming_freelf_fixtures_for_lineup()`
docstring, fereastra reală de publicare FreeLF nu e încă măsurată empiric,
cota fiind cronic epuizată; instrumentarea `*_first_available_at` din
migrarea 030 acumulează dovada reală în timp).

Rulare:
    python -m sync.sync_lineup_freelf [--window-minutes N]
    (sau apelat programatic din .github/workflows/lineup_sync.yml)
================================================================================
"""
from __future__ import annotations

import argparse
import logging

from freelf_lineup_adapter import FreelfLineupAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.LineupFreelf")


def _fixtures_needing_sync(window_minutes_ahead: int = 240) -> list[dict]:
    from database.queries import get_upcoming_freelf_fixtures_for_lineup

    return get_upcoming_freelf_fixtures_for_lineup(window_minutes_ahead=window_minutes_ahead)


def _make_task_runner(adapter: FreelfLineupAdapter, home_team: str, away_team: str, kickoff_date: str, freelf_event_id: str):
    def _run() -> None:
        raw = adapter.fetch({
            "home_team_canonical": home_team, "away_team_canonical": away_team,
            "kickoff_date": kickoff_date, "freelf_event_id": freelf_event_id,
        })
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run(window_minutes_ahead: int = 240) -> list:
    adapter = FreelfLineupAdapter()
    orchestrator = get_sync_orchestrator()

    fixtures = _fixtures_needing_sync(window_minutes_ahead)
    logger.info("[LineupFreelf] %d fixture-uri de sincronizat (fereastră kickoff)", len(fixtures))

    for fx in fixtures:
        home_team = fx["home_team_canonical"]
        away_team = fx["away_team_canonical"]
        kickoff_date = fx["kickoff_date"]
        freelf_event_id = fx["freelf_event_id"]
        task_name = f"lineup_freelf:{home_team}-vs-{away_team}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P1,
            run=_make_task_runner(adapter, home_team, away_team, kickoff_date, freelf_event_id),
            # Coverage deja gatată la sursă — vezi
            # FreelfLineupAdapter.coverage_check().
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare aliniamente (Free Live Football)")
    parser.add_argument("--window-minutes", type=int, default=240)
    args = parser.parse_args()

    results = run(window_minutes_ahead=args.window_minutes)
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
