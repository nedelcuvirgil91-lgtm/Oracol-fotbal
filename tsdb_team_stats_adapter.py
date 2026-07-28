"""
================================================================================
FOOTBALL ORACLE — TheSportsDB Team Stats Adapter (R-Sync-8, ADR-039)
================================================================================
Ultimele evenimente (meciuri terminate) TheSportsDB per echipă — înlocuiește
Level 4 din cascada `oracle_engine._build_profile()`
(`self.api.get_team_stats(team_id, league)`) cu un flux
fetch → normalize → validate → persist, rulat DOAR de Sync Layer
(`sync/sync_team_stats_tsdb.py`), niciodată de Oracle Engine.

`fetch()` reutilizează EXACT `oracle_api.get_team_last_events_tsdb()`, deja
funcțională — nicio logică HTTP nouă (ADR-038, principiul „no defect, no
rewrite"), inclusiv formulele proxy existente (`shots_on_goal`,
`possession` — GĂSIT LA AUDIT, nu reparat aici, vezi migrarea 028).

Diferență structurală față de `apifootball_health_adapter.py` (R-Sync-2):
acolo `team_id` se rezolvă live, per echipă (`resolve_team_id()`), la
cerere. Aici `tsdb_team_id` vine deja gata rezolvat din
`scheduled_fixtures.tsdb_home_team_id`/`tsdb_away_team_id` (populate de
`TsdbFixtureAdapter`, R-Sync-7a) — Sync Layer NU mai caută echipa, doar
citește identificatorul deja descoperit.
================================================================================
"""
from __future__ import annotations

import logging

from sync_adapter import SyncAdapter

logger = logging.getLogger("FootballOracle.SyncAdapters.TsdbTeamStats")


class TsdbTeamStatsAdapter(SyncAdapter):
    provider_id = "thesportsdb"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> dict | None:
        """`params`: `{"team_name_canonical", "tsdb_team_id"}` — id deja
        prefixat `"tsdb_"`, exact forma cerută de
        `get_team_last_events_tsdb()`."""
        team_name = params["team_name_canonical"]
        tsdb_team_id = params["tsdb_team_id"]
        events = self._api.get_team_last_events_tsdb(tsdb_team_id)
        return {
            "team_name_canonical": team_name,
            "tsdb_team_id": tsdb_team_id,
            "events": events,
        }

    def normalize(self, raw_payload: dict | None) -> list[dict]:
        if not raw_payload:
            return []
        team_name = raw_payload.get("team_name_canonical")
        if not team_name:
            return []
        return [{
            "team_name": team_name,
            "tsdb_team_id": raw_payload.get("tsdb_team_id", ""),
            "events": raw_payload.get("events") or [],
        }]

    def validate(self, records: list[dict]) -> list[dict]:
        """Exclude, nu aruncă excepție — un rând fără `team_name` sau fără
        evenimente reale nu poate produce formă utilizabilă (Regula #8: mai
        bine lipsă decât inventat)."""
        valid: list[dict] = []
        for r in records:
            if not r.get("team_name"):
                logger.warning("[TsdbTeamStatsAdapter] rând fără team_name, exclus: %r", r)
                continue
            if not r.get("events"):
                continue
            valid.append(r)
        return valid

    def persist(self, records: list[dict]) -> bool:
        from database.queries import upsert_team_stats_tsdb

        ok = True
        for r in records:
            success = upsert_team_stats_tsdb(r["team_name"], r["tsdb_team_id"], r["events"])
            ok = ok and success
        return ok

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT, nu omisiune] NU consultă Coverage Cache — coverage e
        deja aplicată corect, la nivelul corect: `sync/sync_team_stats_tsdb.py`
        iterează exclusiv echipele deja prezente în `scheduled_fixtures` cu
        un `tsdb_*_team_id` populat (o ligă neacoperită de TheSportsDB
        discovery nu produce niciodată un astfel de rând). Suprascrierea de
        mai jos (True, identică cu default-ul din SyncAdapter) există
        explicit, nu implicit — exact tiparul din
        `apifootball_health_adapter.coverage_check()` (R-Sync-2) și
        `footballdata_form_adapter.coverage_check()` (R-Sync-3)."""
        return True
