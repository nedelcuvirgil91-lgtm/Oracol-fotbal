"""
================================================================================
FOOTBALL ORACLE — football-data.org Fixture Adapter (R-Sync-7a, ADR-039)
================================================================================
Descoperire meciuri, sursa football-data.org (pasul 3 din
`get_matches_for_week()`, fallback, rămâne live până la R-Sync-7b).
`fetch()` reutilizează `oracle_api.get_football_data_matches_raw()`
(pură adăugire peste `_fetch_matches_fd()`, deja funcțională).

Explicit NU normalizează `league` — GĂSIT LA AUDIT R-Sync-7 (nu ascuns):
`_fetch_matches_fd()` întoarce numele brut al competiției
(`competition.name`), fără `normalize_league_name()` aplicat, singurul
provider cu acest gol. De asta `league`/`venue_city` de la
football-data.org au prioritate MAI MICĂ în FixtureMergePolicy (migrare
023) — nu se repară aici (ar fi o schimbare separată de scope, în afara
identității de meci), doar se documentează și se reflectă în rank.
================================================================================
"""
from __future__ import annotations

from fixture_discovery_common import persist_fixture_records, validate_fixture_records
from sync_adapter import SyncAdapter


class FootballDataFixtureAdapter(SyncAdapter):
    provider_id = "fd"

    def __init__(self, api=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api

    def fetch(self, params: dict) -> list[dict] | None:
        """`params`: `{"date_from", "date_to", "comp_codes"}`."""
        return self._api.get_football_data_matches_raw(
            params["date_from"], params["date_to"], params.get("comp_codes"),
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
                "fd_home_team_id": m.get("home_team_id") or None,
                "fd_away_team_id": m.get("away_team_id") or None,
            })
        return records

    def validate(self, records: list[dict]) -> list[dict]:
        return validate_fixture_records(records, "FootballDataFixtureAdapter")

    def persist(self, records: list[dict]) -> bool:
        return persist_fixture_records(records, self.provider_id)

    def coverage_check(self, context: dict) -> bool:
        """[DELIBERAT] Coverage deja gatată la sursă —
        `sync_scheduled_fixtures.py` iterează exclusiv
        `mappings.FD_COMPETITIONS`."""
        return True
