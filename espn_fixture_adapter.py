"""
================================================================================
FOOTBALL ORACLE — ESPN Fixture Adapter (R-Sync-7a, ADR-039)
================================================================================
Descoperire meciuri, sursa ESPN (pasul 4 din `get_matches_for_week()`,
fallback, rămâne live până la R-Sync-7b). Singura responsabilitate a
ESPN în tot proiectul (confirmat exhaustiv, audit R-Sync-3 §6b). `fetch()`
reutilizează `oracle_api.get_espn_matches_raw()` (pură adăugire peste
`_fetch_matches_espn()`, deja funcțională).
================================================================================
"""
from __future__ import annotations

from fixture_discovery_common import persist_fixture_records, validate_fixture_records
from sync_adapter import SyncAdapter


class EspnFixtureAdapter(SyncAdapter):
    provider_id = "espn"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> list[dict] | None:
        """`params`: `{"league", "target_date"}`."""
        return self._api.get_espn_matches_raw(params["league"], params["target_date"])

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
                "espn_home_team_id": m.get("home_team_id") or None,
                "espn_away_team_id": m.get("away_team_id") or None,
            })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        return validate_fixture_records(records, "EspnFixtureAdapter")

    def persist(self, records: list[dict]) -> bool:
        return persist_fixture_records(records, self.provider_id)

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT] Coverage deja gatată la sursă —
        `sync_scheduled_fixtures.py` iterează exclusiv
        `mappings.ESPN_LEAGUE_SLUGS`."""
        return True
