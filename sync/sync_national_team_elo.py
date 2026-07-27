"""
================================================================================
FOOTBALL ORACLE — Sync National Team ELO (R-Sync-4, ADR-039)
================================================================================
Module: sync/sync_national_team_elo.py

Punctul de intrare Sync Layer pentru ELO-ul echipelor naționale
(eloratings.net) — înlocuiește fallback-ul live eliminat din cascada de
ELO a `oracle_engine._build_profile()`. Un singur `SyncTask` — un scrape
produce TOATE echipele naționale cunoscute deodată, spre deosebire de
`sync_team_health.py` (per echipă) sau `sync_team_form_footballdata.py`
(per ligă).

Corecție de scope (audit §6c): eloratings.net, NU TheSportsDB.

Rulare:
    python -m sync.sync_national_team_elo
    (sau apelat programatic din sync/run_daily.py — neatins aici, cablarea
    în orchestrarea zilnică rămâne un pas separat, ulterior)
================================================================================
"""
from __future__ import annotations

import logging

from elo_ratings_adapter import EloRatingsAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.NationalTeamElo")


def _make_task_runner(adapter: EloRatingsAdapter):
    def _run() -> None:
        raw = adapter.fetch({})
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run() -> list:
    adapter = EloRatingsAdapter()
    orchestrator = get_sync_orchestrator()

    orchestrator.register_task(SyncTask(
        name="national_team_elo",
        provider=adapter.provider_id,
        priority=Priority.P3,
        run=_make_task_runner(adapter),
        # Fara concept de coverage — vezi elo_ratings_adapter.coverage_check().
        coverage_required=False,
    ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run()
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
