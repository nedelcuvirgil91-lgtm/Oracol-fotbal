"""
================================================================================
FOOTBALL ORACLE — Sync H2H Free Live Football (R-Sync-9, ADR-039)
================================================================================
Module: sync/sync_h2h_freelf.py

Punctul de intrare Sync Layer pentru confruntări directe (H2H) Free Live
Football — înlocuiește ultimul apel live rămas, eliminabil, din
`oracle_engine._build_h2h()` (`self.api.get_h2h(event_id, home_name,
away_name)`). Determină fixture-urile de sincronizat citind
`scheduled_fixtures` (`database.queries.get_freelf_fixtures_needing_h2h()`)
— NU mai caută event_id-ul live; vine deja gata rezolvat din
`FreelfFixtureAdapter` (R-Sync-7a, pipeline step `scheduled_fixtures`, care
trebuie să ruleze înainte de acest pas).

Rulare:
    python -m sync.sync_h2h_freelf [--days-ahead N]
    (sau apelat programatic din sync/run_daily.py, DUPĂ pasul
    `scheduled_fixtures`)
================================================================================
"""
from __future__ import annotations

import argparse
import logging

from freelf_h2h_adapter import FreelfH2hAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.H2hFreelf")


def _fixtures_needing_sync(days_ahead: int = 14) -> list[dict]:
    from database.queries import get_freelf_fixtures_needing_h2h

    return get_freelf_fixtures_needing_h2h(days_ahead=days_ahead)


def _make_task_runner(adapter: FreelfH2hAdapter, home_team: str, away_team: str, freelf_event_id: str):
    def _run() -> None:
        raw = adapter.fetch({
            "home_team_canonical": home_team, "away_team_canonical": away_team,
            "freelf_event_id": freelf_event_id,
        })
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run(days_ahead: int = 14) -> list:
    adapter = FreelfH2hAdapter()
    orchestrator = get_sync_orchestrator()

    fixtures = _fixtures_needing_sync(days_ahead)
    logger.info("[H2hFreelf] %d fixture-uri de sincronizat", len(fixtures))

    for fx in fixtures:
        home_team = fx["home_team_canonical"]
        away_team = fx["away_team_canonical"]
        freelf_event_id = fx["freelf_event_id"]
        task_name = f"h2h_freelf:{home_team}-vs-{away_team}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P3,
            run=_make_task_runner(adapter, home_team, away_team, freelf_event_id),
            # Coverage deja gatată la sursă — vezi
            # FreelfH2hAdapter.coverage_check().
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare H2H (Free Live Football)")
    parser.add_argument("--days-ahead", type=int, default=14)
    args = parser.parse_args()

    results = run(days_ahead=args.days_ahead)
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
