"""
================================================================================
FOOTBALL ORACLE — TheSportsDB Fixture Adapter (R-Sync-7a, ADR-039)
================================================================================
Descoperire meciuri, sursa TheSportsDB (pasul 5 din `get_matches_for_week()`,
fallback per-ligă, rămâne live până la R-Sync-7b). `fetch()` reutilizează
`oracle_api.get_tsdb_matches_raw()` (pură adăugire peste
`_fetch_matches_tsdb()`, deja funcțională).

Singurul adaptor care furnizează `tsdb_home_team_id`/`tsdb_away_team_id`
— cheia care deblochează TheSportsDB team stats la R-Sync-8
(`get_team_stats(team_id)`).

`venue_city` de la TSDB e mereu gol (reparat la sursă, R-Sync-5 — câmpul
`strVenue` e numele stadionului, nu al orașului, exclus deliberat).
================================================================================
"""
from __future__ import annotations

from fixture_discovery_common import persist_fixture_records, validate_fixture_records
from sync_adapter import SyncAdapter


class TsdbFixtureAdapter(SyncAdapter):
    provider_id = "tsdb"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> list[dict] | None:
        """`params`: `{"league_id", "league_name"}`."""
        return self._api.get_tsdb_matches_raw(params["league_id"], params["league_name"])

    def normalize(self, raw_payload: list[dict] | None) -> list[dict]:
        if not raw_payload:
            return []
        records: list[dict] = []
        for m in raw_payload:
            records.append({
                "home_team": m.get("home_team", ""),
                "away_team": m.get("away_team", ""),
                "kickoff_date": m.get("kickoff_date", ""),
                "league": m.get("league", ""),
                "kickoff_utc": m.get("kickoff_utc") or None,
                "venue_city": m.get("venue_city") or None,
                "status": m.get("status") or None,
                "tsdb_home_team_id": m.get("home_team_id") or None,
                "tsdb_away_team_id": m.get("away_team_id") or None,
            })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        return validate_fixture_records(records, "TsdbFixtureAdapter")

    def persist(self, records: list[dict]) -> bool:
        return persist_fixture_records(records, self.provider_id)

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT] Coverage deja gatată la sursă —
        `sync_scheduled_fixtures.py` iterează exclusiv
        `mappings.TSDB_LEAGUE_IDS`."""
        return True
