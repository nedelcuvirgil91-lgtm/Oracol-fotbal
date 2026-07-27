"""
================================================================================
FOOTBALL ORACLE — FreeLF Fixture Adapter (R-Sync-7a, ADR-039)
================================================================================
Descoperire meciuri, sursa Free Live Football (pasul 2 din
`get_matches_for_week()`, sursă PRIMARĂ, rămâne live până la R-Sync-7b).
`fetch()` reutilizează `oracle_api.get_freelf_matches_raw()` (pură
adăugire peste `_fetch_freelf_matches()`, deja funcțională).

Singurul adaptor de discovery care furnizează `freelf_event_id` — cheia
care deblochează FreeLF H2H la R-Sync-8 (`self.api.get_h2h(event_id)`).
================================================================================
"""
from __future__ import annotations

from fixture_discovery_common import persist_fixture_records, validate_fixture_records
from sync_adapter import SyncAdapter


class FreeLfFixtureAdapter(SyncAdapter):
    provider_id = "freelf"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> list[dict] | None:
        """`params`: `{"target_date", "league"}`."""
        return self._api.get_freelf_matches_raw(params["target_date"], params["league"])

    def normalize(self, raw_payload: list[dict] | None) -> list[dict]:
        if not raw_payload:
            return []
        records: list[dict] = []
        for m in raw_payload:
            event_id = m.get("_freelf_event_id")
            records.append({
                "home_team": m.get("home_team", ""),
                "away_team": m.get("away_team", ""),
                "kickoff_date": m.get("kickoff_date", ""),
                "league": m.get("league", ""),
                "kickoff_utc": m.get("kickoff_utc") or None,
                "venue_city": m.get("venue_city") or None,
                "status": m.get("status") or None,
                "freelf_event_id": str(event_id) if event_id is not None else None,
                "freelf_home_team_id": m.get("home_team_id") or None,
                "freelf_away_team_id": m.get("away_team_id") or None,
                "freelf_coverage_level": m.get("coverage_level") or None,
            })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        return validate_fixture_records(records, "FreeLfFixtureAdapter")

    def persist(self, records: list[dict]) -> bool:
        return persist_fixture_records(records, self.provider_id)

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT] Coverage deja gatată la sursă —
        `sync_scheduled_fixtures.py` iterează exclusiv
        `mappings.FREE_LF_LEAGUE_IDS`."""
        return True
