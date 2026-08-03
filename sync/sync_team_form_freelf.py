"""
================================================================================
FOOTBALL ORACLE — Sync Team Form FreeLF (R-Sync-6, ADR-039)
================================================================================
Module: sync/sync_team_form_freelf.py

Punctul de intrare Sync Layer pentru standings/formă (Free Live Football)
— înlocuiește Level 0+1 eliminate din cascada
`oracle_engine._build_profile()`. Sincronizare PE LIGĂ — iterează
exclusiv `mappings.FREE_LF_LEAGUE_IDS` (liga → cod intern FreeLF), câte
un `SyncTask` per ligă, fiecare aducând tabelul complet de clasament
(toate echipele) într-o singură cerere.

Rulare:
    python -m sync.sync_team_form_freelf
    (sau apelat programatic din sync/run_daily.py — neatins aici, cablarea
    în orchestrarea zilnică rămâne un pas separat, ulterior)
================================================================================
"""
from __future__ import annotations

import logging

from freelf_form_adapter import FreeLfFormAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.TeamFormFreeLF")


def _make_task_runner(adapter: FreeLfFormAdapter, league: str):
    def _run() -> None:
        raw = adapter.fetch({"league": league})
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run() -> list:
    from mappings import FREE_LF_LEAGUE_IDS
    from database.queries import get_flashscore_covered_standings_leagues

    adapter = FreeLfFormAdapter()
    orchestrator = get_sync_orchestrator()

    # [ADAUGAT Pasul 1 Master Repair Plan, ADR-045 — Single Owner] Ligile
    # pentru care Flashscore are deja un clasament recent nu mai sunt
    # sincronizate de FreeLF. Fallback neschimbat pentru restul ligilor.
    flashscore_covered = get_flashscore_covered_standings_leagues()

    logger.info("[TeamFormFreeLF] %d ligi de sincronizat (%d acoperite deja de Flashscore, sărite)",
                len(FREE_LF_LEAGUE_IDS), len(flashscore_covered & set(FREE_LF_LEAGUE_IDS)))

    for league in FREE_LF_LEAGUE_IDS:
        if league in flashscore_covered:
            continue
        task_name = f"team_form_freelf:{league}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P3,
            run=_make_task_runner(adapter, league),
            # Coverage deja gatată la sursă — se iterează exclusiv ligile
            # din FREE_LF_LEAGUE_IDS (vezi freelf_form_adapter.coverage_check()).
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = run()
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
