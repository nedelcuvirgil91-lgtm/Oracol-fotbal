"""
================================================================================
FOOTBALL ORACLE — Odds API Fixture Adapter (R-Sync-7a, ADR-039)
================================================================================
Descoperire meciuri, sursa Odds API (pasul 1 din `get_matches_for_week()`,
sursă PRIMARĂ, rămâne live până la R-Sync-7b). `fetch()` reutilizează
`oracle_api.get_odds_api_events_raw()` (pură adăugire peste
`_fetch_events_odds_api()`, deja funcțională).

Singurul adaptor care furnizează `odds_api_event_id`/`odds_api_sport_key`
— folosite de `_attach_odds()` (calea Frozen de cote, ADR-005/006),
NEATINSĂ aici — R-Sync-7a doar persistă identitatea, nu schimbă cotele.
================================================================================
"""
from __future__ import annotations

from fixture_discovery_common import persist_fixture_records, validate_fixture_records
from sync_adapter import SyncAdapter


class OddsApiFixtureAdapter(SyncAdapter):
    provider_id = "oddsapi"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> list[dict] | None:
        """`params`: `{"sport_key", "days_ahead"}`."""
        return self._api.get_odds_api_events_raw(params["sport_key"], params.get("days_ahead", 7))

    def normalize(self, raw_payload: list[dict] | None) -> list[dict]:
        if not raw_payload:
            return []
        records: list[dict] = []
        for m in raw_payload:
            odds_id = m.get("_odds_api_id")
            records.append({
                "home_team": m.get("home_team", ""),
                "away_team": m.get("away_team", ""),
                "kickoff_date": m.get("kickoff_date", ""),
                "league": m.get("league", ""),
                "kickoff_utc": m.get("kickoff_utc") or None,
                "venue_city": m.get("venue_city") or None,
                "status": m.get("status") or None,
                "odds_api_event_id": str(odds_id) if odds_id is not None else None,
                "odds_api_sport_key": m.get("_sport_key") or None,
            })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        return validate_fixture_records(records, "OddsApiFixtureAdapter")

    def persist(self, records: list[dict]) -> bool:
        return persist_fixture_records(records, self.provider_id)

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT] Coverage deja gatată la sursă —
        `sync_scheduled_fixtures.py` iterează exclusiv
        `mappings.ODDS_SPORT_KEYS`."""
        return True
