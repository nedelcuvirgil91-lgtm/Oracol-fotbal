"""
================================================================================
FOOTBALL ORACLE — API-Football Fixture Adapter (R-Sync-7a, ADR-039)
================================================================================
Descoperire meciuri, sursa API-Football (pasul 6 din `get_matches_for_week()`,
fallback ultim, rămâne live până la R-Sync-7b). Confirmat la audit R-Sync-3
§6b: `_fetch_matches_api_football()` e literalmente pasul 6 din aceeași
funcție pe care ceilalți 5 adaptori de discovery o țintesc — API-Football
NU e un caz special doar pentru că injuries/coaches ale lui au migrat deja
(R-Sync-2). `fetch()` reutilizează `oracle_api.get_api_football_matches_raw()`
(pură adăugire peste `_fetch_matches_api_football()`, deja funcțională).
================================================================================
"""
from __future__ import annotations

from fixture_discovery_common import persist_fixture_records, validate_fixture_records
from sync_adapter import SyncAdapter


class ApiFootballFixtureAdapter(SyncAdapter):
    provider_id = "apifootball"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> list[dict] | None:
        """`params`: `{"league", "date_from", "date_to"}`."""
        return self._api.get_api_football_matches_raw(
            params["league"], params["date_from"], params["date_to"],
        )

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
                "apifootball_fixture_id": m.get("fixture_id") or None,
                "apifootball_home_team_id": m.get("home_team_id") or None,
                "apifootball_away_team_id": m.get("away_team_id") or None,
            })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        return validate_fixture_records(records, "ApiFootballFixtureAdapter")

    def persist(self, records: list[dict]) -> bool:
        return persist_fixture_records(records, self.provider_id)

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT] Coverage deja gatată la sursă —
        `sync_scheduled_fixtures.py` iterează exclusiv
        `mappings.API_FOOTBALL_LEAGUE_IDS`."""
        return True
