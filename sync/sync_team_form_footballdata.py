"""
================================================================================
FOOTBALL ORACLE — Sync Team Form football-data.org (R-Sync-3, ADR-039)
================================================================================
Module: sync/sync_team_form_footballdata.py

Punctul de intrare Sync Layer pentru formă/standings (football-data.org)
— înlocuiește Level 3 eliminat din cascada
`oracle_engine._build_profile()`. Sincronizare PE LIGĂ (nu pe echipă,
spre deosebire de `sync_team_health.py`) — iterează exclusiv
`mappings.FD_COMPETITIONS` (liga → cod competiție, deja filtrat, fără
`None`), câte un `SyncTask` per ligă, fiecare aducând tabelul complet de
clasament (toate echipele) într-o singură cerere.

Explicit NU descoperă meciuri — R-Sync-7, Universal Match Discovery
Layer, separat.

Rulare:
    python -m sync.sync_team_form_footballdata
    (sau apelat programatic din sync/run_daily.py — neatins aici, cablarea
    în orchestrarea zilnică rămâne un pas separat, ulterior)
================================================================================
"""
from __future__ import annotations

import logging

from footballdata_form_adapter import FootballDataFormAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.TeamFormFootballData")


def _make_task_runner(adapter: FootballDataFormAdapter, comp_code: str):
    def _run() -> None:
        raw = adapter.fetch({"comp_code": comp_code})
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run() -> list:
    from mappings import FD_COMPETITIONS

    adapter = FootballDataFormAdapter()
    orchestrator = get_sync_orchestrator()

    logger.info("[TeamFormFootballData] %d ligi de sincronizat", len(FD_COMPETITIONS))

    for league, comp_code in FD_COMPETITIONS.items():
        task_name = f"team_form_footballdata:{league}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P3,
            run=_make_task_runner(adapter, comp_code),
            # Coverage deja gatată la sursă — se iterează exclusiv ligile
            # din FD_COMPETITIONS (vezi footballdata_form_adapter.
            # coverage_check()).
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run()
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
