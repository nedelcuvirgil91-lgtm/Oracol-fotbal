"""
================================================================================
FOOTBALL ORACLE — Sync Team Stats TheSportsDB (R-Sync-8, ADR-039)
================================================================================
Module: sync/sync_team_stats_tsdb.py

Punctul de intrare Sync Layer pentru ultimele evenimente TheSportsDB per
echipă — înlocuiește Level 4 eliminat din cascada
`oracle_engine._build_profile()` (`self.api.get_team_stats(team_id,
league)`). Determină echipele de sincronizat citind `scheduled_fixtures`
(`database.queries.get_teams_with_tsdb_id()`) — NU mai caută echipa live;
`tsdb_home_team_id`/`tsdb_away_team_id` vin deja gata rezolvate din
`TsdbFixtureAdapter` (R-Sync-7a, pipeline step `scheduled_fixtures`, care
trebuie să ruleze înainte de acest pas).

Rulare:
    python -m sync.sync_team_stats_tsdb [--days-ahead N]
    (sau apelat programatic din sync/run_daily.py, DUPĂ pasul
    `scheduled_fixtures`)
================================================================================
"""
from __future__ import annotations

import argparse
import logging

from tsdb_team_stats_adapter import TsdbTeamStatsAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.TeamStatsTsdb")


def _teams_needing_sync(days_ahead: int = 14) -> list[dict]:
    from database.queries import get_teams_with_tsdb_id

    return get_teams_with_tsdb_id(days_ahead=days_ahead)


def _make_task_runner(adapter: TsdbTeamStatsAdapter, team_name: str, tsdb_team_id: str):
    def _run() -> None:
        raw = adapter.fetch({
            "team_name_canonical": team_name, "tsdb_team_id": tsdb_team_id,
        })
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run(days_ahead: int = 14) -> list:
    adapter = TsdbTeamStatsAdapter()
    orchestrator = get_sync_orchestrator()

    teams = _teams_needing_sync(days_ahead)
    logger.info("[TeamStatsTsdb] %d echipe de sincronizat", len(teams))

    for team in teams:
        team_name = team["team_name"]
        tsdb_team_id = team["tsdb_team_id"]
        task_name = f"team_stats_tsdb:{team_name}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P3,
            run=_make_task_runner(adapter, team_name, tsdb_team_id),
            # Coverage deja gatată la sursă — vezi
            # TsdbTeamStatsAdapter.coverage_check().
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare team stats (TheSportsDB)")
    parser.add_argument("--days-ahead", type=int, default=14)
    args = parser.parse_args()

    results = run(days_ahead=args.days_ahead)
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
