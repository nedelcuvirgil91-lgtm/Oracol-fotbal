"""
================================================================================
FOOTBALL ORACLE — Sync Match Statistics (Sprint 1, ADR-039)
================================================================================
Module: sync/sync_match_statistics.py

Punctul de intrare Sync Layer pentru posesie + xG real post-meci (owner nou,
FreeLF) — completează meciurile deja încheiate (owner `actual_*`:
sync_results) care încă nu au statistici. Sincronizare ZILNICĂ pe fereastră
scurtă (implicit 2 zile) — separată deliberat de backfill-ul istoric
(`sync/backfill_match_stats.py`, extins separat), per politica din
`DATA_WAREHOUSE_ARCHITECTURE_ETAPA_B_2026-07-27.md §1`.

Rulare:
    python -m sync.sync_match_statistics [--days-back N]
    (sau apelat din `sync/run_daily.py`, ca pas declarat cu dependență pe
    rezultatele zilei precedente — vezi `PIPELINE_STEPS` acolo)
================================================================================
"""
from __future__ import annotations

import argparse
import logging

from match_statistics_adapter import MatchStatisticsAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.MatchStatistics")


def _matches_missing_stats(days_back: int = 2) -> list[dict]:
    from database.queries import get_finished_matches_missing_stats
    return get_finished_matches_missing_stats(days_back=days_back)


def _make_task_runner(adapter: MatchStatisticsAdapter, match: dict):
    def _run() -> None:
        raw = adapter.fetch({
            "home_team": match["home_team"], "away_team": match["away_team"],
            "kickoff_date": match["kickoff_date"], "league": match["league"],
        })
        if raw is None:
            logger.debug("[MatchStatistics] fără statistici pentru %s vs %s (%s)",
                         match["home_team"], match["away_team"], match["kickoff_date"])
            return
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run(days_back: int = 2) -> list:
    adapter = MatchStatisticsAdapter()
    orchestrator = get_sync_orchestrator()

    matches = _matches_missing_stats(days_back)
    logger.info("[MatchStatistics] %d meciuri fără statistici (ultimele %d zile)", len(matches), days_back)

    for match in matches:
        task_name = f"match_stats:{match['home_team']}_vs_{match['away_team']}_{match['kickoff_date']}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P1,
            run=_make_task_runner(adapter, match),
            # Coverage deja gatată intern (resolve_freelf_finished_match_id
            # -> FREE_LF_LEAGUE_IDS) — tiparul deja folosit de
            # ApiFootballHealthAdapter (sync_team_health.py).
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare statistici meci (posesie/xG real, FreeLF)")
    parser.add_argument("--days-back", type=int, default=2)
    args = parser.parse_args()

    results = run(days_back=args.days_back)
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
