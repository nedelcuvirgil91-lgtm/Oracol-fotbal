"""
================================================================================
FOOTBALL ORACLE — Sync Team Health (R-Sync-2, ADR-039)
================================================================================
Module: sync/sync_team_health.py

Punctul de intrare Sync Layer pentru starea de sănătate a echipelor
(injuries+coaches, API-Football) — înlocuiește calea inline eliminată din
`oracle_engine.evaluate_match()`. Determină echipele de sincronizat (P1:
echipe cu meciuri în următoarele `days_ahead` zile — audit API-Football
§5, consumatorul real de cotă), înregistrează câte un `SyncTask` per
echipă în Sync Orchestrator, rulează.

Descoperirea meciurilor („ce echipe joacă în curând") folosește azi calea
EXISTENTĂ (`oracle_api.FootballOracleAPI.get_matches_for_week`) —
migrarea descoperirii de meciuri la Supabase e R-Sync-7, separat,
neatinsă aici (ADR-039 audit §6, pasul 8). Acest script rulează DIN Sync
Layer, unde apelul către provideri e explicit permis (ADR-039, principiul 1
— doar Oracle Engine/ML/Feature Engineering nu au voie, nu Sync Layer).

Rulare:
    python -m sync.sync_team_health [--days-ahead N]
    (sau apelat programatic din sync/run_daily.py — neatins aici, cablarea
    în orchestrarea zilnică rămâne un pas separat, ulterior)
================================================================================
"""
from __future__ import annotations

import argparse
import logging
from datetime import date

from apifootball_health_adapter import ApiFootballHealthAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator

logger = logging.getLogger("FootballOracle.Sync.TeamHealth")


def _teams_needing_sync(days_ahead: int = 2) -> list[dict]:
    """Echipe cu meciuri programate în următoarele `days_ahead` zile —
    P1, consumatorul real de cotă (audit API-Football §5)."""
    from oracle_api import FootballOracleAPI

    api = FootballOracleAPI()
    matches = api.get_matches_for_week(days_ahead=days_ahead)
    teams: dict[str, str] = {}
    for m in matches:
        for side in ("home_team", "away_team"):
            name = m.get(side)
            if name and name not in teams:
                teams[name] = m.get("league", "")
    return [{"team_name": name, "league": league} for name, league in teams.items()]


def _make_task_runner(adapter: ApiFootballHealthAdapter, team_name: str, league: str, season: int):
    def _run() -> None:
        team_id = adapter.resolve_team_id(team_name)
        if team_id is None:
            logger.debug("[TeamHealth] nu s-a putut rezolva team_id pentru %s", team_name)
            return
        raw = adapter.fetch({
            "team_name": team_name, "team_id": team_id,
            "league": league, "season": season,
        })
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run(days_ahead: int = 2) -> list:
    adapter = ApiFootballHealthAdapter()
    orchestrator = get_sync_orchestrator()
    season = date.today().year

    teams = _teams_needing_sync(days_ahead)
    logger.info("[TeamHealth] %d echipe de sincronizat", len(teams))

    for team in teams:
        team_name = team["team_name"]
        league = team["league"]
        task_name = f"team_health:{team_name}"
        orchestrator.register_task(SyncTask(
            name=task_name,
            provider=adapter.provider_id,
            priority=Priority.P1,
            run=_make_task_runner(adapter, team_name, league, season),
            # Coverage deja gatată intern de get_injuries()/get_coaches()
            # (_covered(), football_providers.py) — nu se dublează printr-un
            # al doilea mecanism (Coverage Cache, migrare 016, deliberat
            # neatinsă aici, vezi apifootball_health_adapter.py).
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare stare sănătate echipe (API-Football)")
    parser.add_argument("--days-ahead", type=int, default=2)
    args = parser.parse_args()

    results = run(days_ahead=args.days_ahead)
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
