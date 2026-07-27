"""
================================================================================
FOOTBALL ORACLE — Fixture Discovery Common (R-Sync-7a, ADR-039)
================================================================================
Cod partajat de cei 6 adaptori de descoperire a meciurilor
(freelf/odds_api/footballdata/espn/tsdb/apifootball_fixture_adapter.py).

`validate()`/`persist()` sunt IDENTICE pentru toți cei 6 — aceeași
identitate canonică (ADR-024/025), același RPC de merge
(`upsert_scheduled_fixture_merge`, migrare 023). DOAR `fetch()`/
`normalize()` diferă per provider (forma răspunsului brut). Extras aici
ca funcții partajate, nu ca bază de clasă — evită duplicarea a 6 copii
identice ale acestei logici (justificat: 6 implementări reale simultane,
nu abstracție prematură).
================================================================================
"""
from __future__ import annotations

import logging

logger = logging.getLogger("FootballOracle.SyncAdapters.FixtureDiscovery")


def validate_fixture_records(records: list[dict], adapter_name: str) -> list[dict]:
    """Exclude, nu aruncă excepție — un rând fără echipe/dată valide nu
    poate fi persistat ca identitate de meci (Regula #8)."""
    valid: list[dict] = []
    for r in records:
        if not r.get("home_team") or not r.get("away_team"):
            logger.warning("[%s] echipe lipsă, exclus: %r", adapter_name, r)
            continue
        if not r.get("kickoff_date"):
            logger.warning("[%s] kickoff_date lipsă, exclus: %r", adapter_name, r)
            continue
        valid.append(r)
    return valid


def persist_fixture_records(records: list[dict], provider_id: str) -> bool:
    """Un singur RPC (`upsert_scheduled_fixture_merge`, prin
    `database.queries.upsert_scheduled_fixture`) decide TOATĂ logica de
    merge (FixtureMergePolicy) — adaptorul trimite doar câmpurile pe care
    le are, restul rămân `None`/`NULL`, ignorate de RPC."""
    from database.queries import upsert_scheduled_fixture

    ok = True
    for r in records:
        success = upsert_scheduled_fixture(
            home_team=r["home_team"], away_team=r["away_team"], kickoff_date=r["kickoff_date"],
            provider_id=provider_id,
            league=r.get("league"), kickoff_utc=r.get("kickoff_utc"), venue_city=r.get("venue_city"),
            status=r.get("status"),
            freelf_event_id=r.get("freelf_event_id"),
            freelf_home_team_id=r.get("freelf_home_team_id"),
            freelf_away_team_id=r.get("freelf_away_team_id"),
            freelf_coverage_level=r.get("freelf_coverage_level"),
            odds_api_event_id=r.get("odds_api_event_id"),
            odds_api_sport_key=r.get("odds_api_sport_key"),
            apifootball_fixture_id=r.get("apifootball_fixture_id"),
            apifootball_home_team_id=r.get("apifootball_home_team_id"),
            apifootball_away_team_id=r.get("apifootball_away_team_id"),
            tsdb_home_team_id=r.get("tsdb_home_team_id"),
            tsdb_away_team_id=r.get("tsdb_away_team_id"),
            fd_home_team_id=r.get("fd_home_team_id"),
            fd_away_team_id=r.get("fd_away_team_id"),
            espn_home_team_id=r.get("espn_home_team_id"),
            espn_away_team_id=r.get("espn_away_team_id"),
        )
        ok = ok and success
    return ok
