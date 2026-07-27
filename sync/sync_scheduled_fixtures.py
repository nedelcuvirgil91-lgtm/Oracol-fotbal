"""
================================================================================
FOOTBALL ORACLE — Sync Scheduled Fixtures (R-Sync-7a, ADR-039)
================================================================================
Module: sync/sync_scheduled_fixtures.py

Punctul de intrare Sync Layer pentru descoperirea meciurilor — TOȚI cei 6
provideri (Universal Match Discovery Layer, audit §6b), niciunul
privilegiat: FreeLF, Odds API, football-data.org, ESPN, TheSportsDB,
API-Football. Populează `scheduled_fixtures` (migrare 023) prin
FixtureMergePolicy (RPC `upsert_scheduled_fixture_merge`) — merge la
nivel de câmp (o identitate canonică, N identificatori de provider), NU
first-wins (bug-ul demonstrat, dovedit prin simulare reală în auditul
R-Sync-7, al cascadei vechi `get_matches_for_week()`).

[R-Sync-7a — NU R-Sync-7b] Oracle Engine NU citește încă de aici — rămâne
pe `get_matches_for_week()` (cascada live veche, neschimbată) până la
R-Sync-7b, separat, cu comparație măsurată între cele două căi. Acest
script rulează în PARALEL cu calea veche, nu o înlocuiește.

Prioritatea `SyncTask` de mai jos e STRICT despre ordinea de EXECUȚIE a
sincronizării (competiție pentru buget/timp, in cadrul SyncOrchestrator)
— NU are nicio legătură cu FixtureMergePolicy (precedența pe calitate a
câmpurilor `league`/`venue_city`/`kickoff_utc` trăiește EXCLUSIV în RPC,
independent de ordinea de execuție, decizie explicită proprietar produs).

Rulare:
    python -m sync.sync_scheduled_fixtures [--days-ahead N]
    (sau apelat programatic din sync/run_daily.py — neatins aici, cablarea
    în orchestrarea zilnică rămâne un pas separat, ulterior)
================================================================================
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from apifootball_fixture_adapter import ApiFootballFixtureAdapter
from espn_fixture_adapter import EspnFixtureAdapter
from footballdata_fixture_adapter import FootballDataFixtureAdapter
from freelf_fixture_adapter import FreeLfFixtureAdapter
from odds_api_fixture_adapter import OddsApiFixtureAdapter
from sync_orchestrator import Priority, SyncTask, get_sync_orchestrator
from tsdb_fixture_adapter import TsdbFixtureAdapter

logger = logging.getLogger("FootballOracle.Sync.ScheduledFixtures")


def _make_task_runner(adapter, params: dict):
    def _run() -> None:
        raw = adapter.fetch(params)
        records = adapter.normalize(raw)
        records = adapter.validate(records)
        adapter.persist(records)
    return _run


def run(days_ahead: int = 7) -> list:
    from mappings import (
        API_FOOTBALL_LEAGUE_IDS, ESPN_LEAGUE_SLUGS, FD_COMPETITIONS,
        FREE_LF_LEAGUE_IDS, ODDS_SPORT_KEYS, TSDB_LEAGUE_IDS,
    )

    orchestrator = get_sync_orchestrator()
    today = date.today()
    date_from = today.isoformat()
    date_to = (today + timedelta(days=days_ahead)).isoformat()
    n_days = min(days_ahead, 7)

    # 1. Odds API — sursă primară, un task per ligă (sport_key).
    odds_adapter = OddsApiFixtureAdapter()
    for league, sport_key in ODDS_SPORT_KEYS.items():
        orchestrator.register_task(SyncTask(
            name=f"scheduled_fixtures:oddsapi:{league}",
            provider=odds_adapter.provider_id, priority=Priority.P2,
            run=_make_task_runner(odds_adapter, {"sport_key": sport_key, "days_ahead": days_ahead}),
            coverage_required=False,
        ))

    # 2. FreeLF — sursă primară, un task per (ligă, zi).
    freelf_adapter = FreeLfFixtureAdapter()
    for i in range(n_days):
        target = (today + timedelta(days=i)).isoformat()
        for league in FREE_LF_LEAGUE_IDS:
            orchestrator.register_task(SyncTask(
                name=f"scheduled_fixtures:freelf:{league}:{target}",
                provider=freelf_adapter.provider_id, priority=Priority.P2,
                run=_make_task_runner(freelf_adapter, {"target_date": target, "league": league}),
                coverage_required=False,
            ))

    # 3. football-data.org — fallback, un singur task, interval de date,
    #    toate ligile deodată (endpoint-ul suportă asta nativ).
    fd_adapter = FootballDataFixtureAdapter()
    fd_codes = list(FD_COMPETITIONS.values()) or None
    orchestrator.register_task(SyncTask(
        name="scheduled_fixtures:fd:all",
        provider=fd_adapter.provider_id, priority=Priority.P3,
        run=_make_task_runner(fd_adapter, {"date_from": date_from, "date_to": date_to, "comp_codes": fd_codes}),
        coverage_required=False,
    ))

    # 4. ESPN — fallback, un task per (ligă, zi).
    espn_adapter = EspnFixtureAdapter()
    for i in range(n_days):
        target = (today + timedelta(days=i)).isoformat()
        for league in ESPN_LEAGUE_SLUGS:
            orchestrator.register_task(SyncTask(
                name=f"scheduled_fixtures:espn:{league}:{target}",
                provider=espn_adapter.provider_id, priority=Priority.P3,
                run=_make_task_runner(espn_adapter, {"league": league, "target_date": target}),
                coverage_required=False,
            ))

    # 5. TheSportsDB — fallback, un task per ligă (endpoint-urile interne
    #    gestionează deja intervalul de date).
    tsdb_adapter = TsdbFixtureAdapter()
    for league, league_id in TSDB_LEAGUE_IDS.items():
        orchestrator.register_task(SyncTask(
            name=f"scheduled_fixtures:tsdb:{league}",
            provider=tsdb_adapter.provider_id, priority=Priority.P4,
            run=_make_task_runner(tsdb_adapter, {"league_id": league_id, "league_name": league}),
            coverage_required=False,
        ))

    # 6. API-Football — fallback ultim, un task per ligă, interval de date.
    apifootball_adapter = ApiFootballFixtureAdapter()
    for league in API_FOOTBALL_LEAGUE_IDS:
        orchestrator.register_task(SyncTask(
            name=f"scheduled_fixtures:apifootball:{league}",
            provider=apifootball_adapter.provider_id, priority=Priority.P5,
            run=_make_task_runner(apifootball_adapter, {
                "league": league, "date_from": date_from, "date_to": date_to,
            }),
            coverage_required=False,
        ))

    return orchestrator.run_pending()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare descoperire meciuri (Universal Match Discovery Layer)")
    parser.add_argument("--days-ahead", type=int, default=7)
    args = parser.parse_args()

    results = run(days_ahead=args.days_ahead)
    for r in results:
        logger.info("%s -> ran=%s reason=%s%s", r.task_name, r.ran, r.reason,
                     f" error={r.error}" if r.error else "")
