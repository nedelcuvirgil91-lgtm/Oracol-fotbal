"""
================================================================================
FOOTBALL ORACLE — Sync Odds API Recent Results (R-Sync-6, ADR-039)
================================================================================
Module: sync/sync_odds_recent_results.py

Punctul de intrare Sync Layer pentru meciurile terminate recente (Odds
API `/scores`) — sursă canonică unică pentru formă ȘI H2H (audit R-Sync-6,
opțiunea A). Sincronizare PE LIGĂ — iterează exclusiv
`mappings.ODDS_SPORT_KEYS`, câte un `SyncTask` per ligă.

NU atinge calea Frozen de persistare a cotelor pre-meci
(`services/odds_persistence_service.py`, ADR-005/006) — complet separată,
scoruri de meciuri terminate, nu cote.

Rulare:
    python -m sync.sync_odds_recent_results
    (sau apelat programatic din sync/run_daily.py — neatins aici, cablarea
    în orchestrarea zilnică rămâne un pas separat, ulterior)
================================================================================
"""
from __future__ import annotations

import logging

from odds_api_recent_results_adapter import OddsApiRecentResultsAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.OddsApiRecentResults")


def _make_task_runner(adapter: OddsApiRecentResultsAdapter, sport_key: str):
    def _run() -> None:
        raw = adapter.fetch({"sport_key": sport_key})
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run() -> list:
    from mappings import ODDS_SPORT_KEYS

    adapter = OddsApiRecentResultsAdapter()
    orchestrator = get_sync_orchestrator()

    logger.info("[OddsApiRecentResults] %d ligi de sincronizat", len(ODDS_SPORT_KEYS))

    for league, sport_key in ODDS_SPORT_KEYS.items():
        task_name = f"odds_recent_results:{league}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P3,
            run=_make_task_runner(adapter, sport_key),
            # Coverage deja gatată la sursă — se iterează exclusiv ligile
            # din ODDS_SPORT_KEYS (vezi
            # odds_api_recent_results_adapter.coverage_check()).
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run()
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
