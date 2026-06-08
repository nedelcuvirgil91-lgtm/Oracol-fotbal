"""
================================================================================
FOOTBALL ORACLE — API Integration Module
================================================================================
Module  : oracle_api.py
Purpose : Centralised HTTP client for API-Football, Anthropic Claude, and
          OpenWeatherMap.  All responses are returned as clean Python dicts/
          lists ready for Pandas ingestion.  Nothing is persisted here —
          persistence (JSON / CSV) is handled upstream by the Oracle engine.
Author  : Football Oracle — Private Single-User Build
================================================================================
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timezone
from typing import Any

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ─────────────────────────────────────────────────────────────────────────────
# HARDCODED CREDENTIALS  (single-user private build — do NOT commit to git)
# ─────────────────────────────────────────────────────────────────────────────
API_FOOTBALL_KEY: str = "b0e2ab9bcda1d9f4c5ddfe1063c81cd7"
API_FOOTBALL_URL: str = "https://v3.football.api-sports.io"

CLAUDE_API_KEY: str = (
    "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"
)

WEATHER_API_KEY: str = "48a5b54b8ced45cc924153231263005"
WEATHER_API_URL: str = "http://api.weatherapi.com/v1"

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.API")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _build_retry_session(
    retries: int = 3,
    backoff_factor: float = 0.4,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> Session:
    """Return a requests.Session with automatic retry logic."""
    session = Session()
    retry = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=status_forcelist,
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _check_response(response: Response, endpoint: str) -> dict[str, Any] | None:
    """
    Validate HTTP status and API-Football internal error codes.
    Returns the parsed JSON body on success, or None on failure.
    """
    if response.status_code == 429:
        logger.error(
            "[%s] Rate-limit exceeded (HTTP 429). "
            "Wait before retrying or upgrade your API plan.",
            endpoint,
        )
        return None

    if response.status_code == 403:
        logger.error(
            "[%s] Forbidden (HTTP 403). Check your API key.", endpoint
        )
        return None

    if not response.ok:
        logger.error(
            "[%s] Unexpected HTTP %s — %s",
            endpoint,
            response.status_code,
            response.text[:200],
        )
        return None

    try:
        body: dict[str, Any] = response.json()
    except ValueError:
        logger.error("[%s] Response is not valid JSON.", endpoint)
        return None

    # API-Football wraps errors in the response body even on HTTP 200
    errors = body.get("errors", {})
    if errors:
        logger.error("[%s] API-Football error payload: %s", endpoint, errors)
        return None

    results: int = body.get("results", 0)
    logger.info("[%s] Success — %d result(s) returned.", endpoint, results)
    return body


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class FootballOracleAPI:
    """
    Centralised API client for Football Oracle.

    All public methods return clean Python structures (list[dict] or dict).
    On error they return an empty list [] or empty dict {} so callers can
    proceed safely without extra None-checks.
    """

    # Bookmaker ID for Bet365 on API-Football
    BET365_BOOKMAKER_ID: int = 1
    # Bet-type label for the 1X2 (Match Winner) market
    MARKET_1X2: str = "Match Winner"

    def __init__(self) -> None:
        self._session: Session = _build_retry_session()

        # API-Football headers
        self._af_headers: dict[str, str] = {
            "x-apisports-key": API_FOOTBALL_KEY,
            "Accept": "application/json",
        }

        # Weather API base params
        self._weather_key: str = WEATHER_API_KEY

        logger.info("FootballOracleAPI initialised successfully.")

    # ──────────────────────────────────────────────────────────────────────
    # PRIVATE UTILITIES
    # ──────────────────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """
        Generic GET wrapper for API-Football.
        Returns the full parsed body dict, or None on failure.
        """
        url = f"{API_FOOTBALL_URL}/{endpoint}"
        logger.info("GET %s  params=%s", url, params)
        try:
            response = self._session.get(
                url, headers=self._af_headers, params=params, timeout=15
            )
            return _check_response(response, endpoint)
        except requests.exceptions.ConnectionError as exc:
            logger.error("[%s] Connection error: %s", endpoint, exc)
        except requests.exceptions.Timeout:
            logger.error("[%s] Request timed out after 15 s.", endpoint)
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Unexpected requests error: %s", endpoint, exc)
        return None

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIC METHODS — PRE-MATCH DATA
    # ──────────────────────────────────────────────────────────────────────

    def get_fixtures_for_today(self, league_ids: list[int]) -> list[dict[str, Any]]:
        """
        Fetch today's fixtures for every league ID in *league_ids*.

        Parameters
        ----------
        league_ids : list[int]
            E.g. [283, 135, 39] for Romania SuperLiga, Serie A, Premier League.

        Returns
        -------
        list[dict]
            Flat list of fixture objects from the API-Football response.
            Each dict contains fixture details, teams, venue, status, etc.
        """
        today_str: str = date.today().isoformat()   # "YYYY-MM-DD"
        all_fixtures: list[dict[str, Any]] = []

        for league_id in league_ids:
            logger.info(
                "Fetching fixtures for league_id=%d on %s …", league_id, today_str
            )
            body = self._get(
                "fixtures",
                params={"league": league_id, "date": today_str},
            )
            if body is None:
                logger.warning("Skipping league_id=%d — no data returned.", league_id)
                continue

            fixtures: list[dict] = body.get("response", [])
            logger.info(
                "league_id=%d → %d fixture(s) found.", league_id, len(fixtures)
            )
            all_fixtures.extend(fixtures)

        logger.info(
            "Total fixtures fetched across %d league(s): %d",
            len(league_ids),
            len(all_fixtures),
        )
        return all_fixtures

    # ──────────────────────────────────────────────────────────────────────

    def get_standings(
        self, league_id: int, season: int
    ) -> list[dict[str, Any]]:
        """
        Fetch the current standings table for a given league & season.

        Used internally for Team DNA / form index calculation (points per game,
        home vs away splits, goal difference, etc.).

        Parameters
        ----------
        league_id : int
        season    : int  — four-digit year, e.g. 2024

        Returns
        -------
        list[dict]
            The raw standings groups (usually one group for single-table
            leagues, multiple for group stages).
        """
        logger.info(
            "Fetching standings — league_id=%d, season=%d …", league_id, season
        )
        body = self._get(
            "standings",
            params={"league": league_id, "season": season},
        )
        if body is None:
            return []

        # Response structure: response[0].league.standings (list of groups)
        try:
            standings_groups: list[dict] = (
                body["response"][0]["league"]["standings"]
            )
            logger.info(
                "league_id=%d — %d standings group(s) parsed.",
                league_id,
                len(standings_groups),
            )
            return standings_groups
        except (IndexError, KeyError, TypeError) as exc:
            logger.error(
                "Could not parse standings for league_id=%d: %s", league_id, exc
            )
            return []

    # ──────────────────────────────────────────────────────────────────────

    def get_prematch_odds(self, fixture_id: int) -> dict[str, Any]:
        """
        Fetch pre-match bookmaker odds for a given fixture.

        Targets the **Bet365 (bookmaker_id=1)** 1X2 market specifically.
        Falls back to the first available bookmaker that offers 1X2 if
        Bet365 is not present.

        Parameters
        ----------
        fixture_id : int

        Returns
        -------
        dict with keys:
            "fixture_id"  : int
            "bookmaker"   : str   — bookmaker name used
            "home"        : float — decimal odds for home win
            "draw"        : float — decimal odds for draw
            "away"        : float — decimal odds for away win
            "raw"         : list  — full raw bets list from the bookmaker

        Returns empty dict {} if odds are unavailable.
        """
        logger.info("Fetching pre-match odds — fixture_id=%d …", fixture_id)
        body = self._get(
            "odds",
            params={
                "fixture": fixture_id,
                "bookmaker": self.BET365_BOOKMAKER_ID,
            },
        )

        if body is None or not body.get("response"):
            logger.warning(
                "No odds data for fixture_id=%d with Bet365. "
                "Retrying without bookmaker filter …",
                fixture_id,
            )
            # Retry without bookmaker filter to get any available odds
            body = self._get("odds", params={"fixture": fixture_id})
            if body is None or not body.get("response"):
                logger.error(
                    "No odds available at all for fixture_id=%d.", fixture_id
                )
                return {}

        try:
            odds_response: list[dict] = body["response"]
            bookmakers: list[dict] = odds_response[0].get("bookmakers", [])

            # Prefer Bet365; otherwise take the first bookmaker that has 1X2
            chosen_bk: dict | None = None
            for bk in bookmakers:
                if bk.get("id") == self.BET365_BOOKMAKER_ID:
                    chosen_bk = bk
                    break
            if chosen_bk is None:
                chosen_bk = bookmakers[0] if bookmakers else None

            if chosen_bk is None:
                logger.warning(
                    "fixture_id=%d — bookmaker list is empty.", fixture_id
                )
                return {}

            bk_name: str = chosen_bk.get("name", "Unknown")
            bets: list[dict] = chosen_bk.get("bets", [])

            # Find the 1X2 market
            market_1x2: dict | None = next(
                (b for b in bets if b.get("name") == self.MARKET_1X2), None
            )
            if market_1x2 is None:
                logger.warning(
                    "fixture_id=%d — '%s' market not found for bookmaker '%s'.",
                    fixture_id,
                    self.MARKET_1X2,
                    bk_name,
                )
                return {}

            values: list[dict] = market_1x2.get("values", [])
            odds_map: dict[str, float] = {}
            for v in values:
                label = v.get("value", "")      # "Home", "Draw", "Away"
                odd   = float(v.get("odd", 0))
                odds_map[label.lower()] = odd

            result: dict[str, Any] = {
                "fixture_id": fixture_id,
                "bookmaker":  bk_name,
                "home":       odds_map.get("home", 0.0),
                "draw":       odds_map.get("draw", 0.0),
                "away":       odds_map.get("away", 0.0),
                "raw":        bets,
            }
            logger.info(
                "fixture_id=%d — 1X2 odds from '%s': H=%.2f  D=%.2f  A=%.2f",
                fixture_id,
                bk_name,
                result["home"],
                result["draw"],
                result["away"],
            )
            return result

        except (IndexError, KeyError, TypeError, ValueError) as exc:
            logger.error(
                "Odds parsing error for fixture_id=%d: %s", fixture_id, exc
            )
            return {}

    # ──────────────────────────────────────────────────────────────────────

    def get_last_fixtures_stats(
        self, team_id: int, last_n: int = 5
    ) -> list[dict[str, Any]]:
        """
        Fetch detailed statistics for a team's last *last_n* completed matches.

        Metrics extracted per fixture:
          - Goals scored / conceded
          - Shots on target / total shots
          - Ball possession (%)
          - Passes accuracy (%)
          - Fouls, corners, offsides, yellow/red cards

        Parameters
        ----------
        team_id : int
        last_n  : int — default 5 (last five matches)

        Returns
        -------
        list[dict]
            One dict per fixture, each containing "fixture_meta" and
            "team_stats" sub-dicts ready for Pandas ingestion.
        """
        logger.info(
            "Fetching last %d fixtures + stats — team_id=%d …", last_n, team_id
        )

        # Step 1: fetch the last N finished fixtures for this team
        fixtures_body = self._get(
            "fixtures",
            params={"team": team_id, "last": last_n, "status": "FT"},
        )
        if fixtures_body is None:
            return []

        fixtures: list[dict] = fixtures_body.get("response", [])
        if not fixtures:
            logger.warning(
                "team_id=%d — no finished fixtures found.", team_id
            )
            return []

        logger.info(
            "team_id=%d — %d fixture(s) to process for stats.", team_id, len(fixtures)
        )

        enriched: list[dict[str, Any]] = []

        for fix in fixtures:
            fixture_id: int = fix["fixture"]["id"]
            fixture_date: str = fix["fixture"]["date"][:10]
            home_team: str = fix["teams"]["home"]["name"]
            away_team: str = fix["teams"]["away"]["name"]
            home_goals: int = fix["goals"]["home"] or 0
            away_goals: int = fix["goals"]["away"] or 0

            logger.info(
                "  → Stats for fixture_id=%d  [%s vs %s  %d-%d  on %s]",
                fixture_id,
                home_team,
                away_team,
                home_goals,
                away_goals,
                fixture_date,
            )

            # Step 2: fetch per-fixture statistics
            stats_body = self._get(
                "fixtures/statistics",
                params={"fixture": fixture_id, "team": team_id},
            )
            if stats_body is None:
                logger.warning(
                    "    Stats unavailable for fixture_id=%d.", fixture_id
                )
                continue

            stats_response: list[dict] = stats_body.get("response", [])
            if not stats_response:
                continue

            # The API returns one object per team; we already filtered by team_id
            raw_stats: list[dict] = stats_response[0].get("statistics", [])

            # Flatten the statistics list [{type, value}, …] into a dict
            stat_map: dict[str, Any] = {
                s["type"]: s["value"] for s in raw_stats
            }

            def _num(key: str) -> float:
                """Safely coerce a stat value to float (handles '55%', None)."""
                raw = stat_map.get(key)
                if raw is None:
                    return 0.0
                if isinstance(raw, str):
                    return float(raw.replace("%", "").strip() or 0)
                return float(raw)

            # Determine result from this team's perspective
            team_is_home: bool = fix["teams"]["home"]["id"] == team_id
            goals_for     = home_goals if team_is_home else away_goals
            goals_against = away_goals if team_is_home else home_goals
            if goals_for > goals_against:
                result_label = "W"
            elif goals_for < goals_against:
                result_label = "L"
            else:
                result_label = "D"

            enriched.append(
                {
                    "fixture_meta": {
                        "fixture_id":   fixture_id,
                        "date":         fixture_date,
                        "home_team":    home_team,
                        "away_team":    away_team,
                        "home_goals":   home_goals,
                        "away_goals":   away_goals,
                        "team_is_home": team_is_home,
                        "result":       result_label,
                        "goals_for":    goals_for,
                        "goals_against": goals_against,
                    },
                    "team_stats": {
                        "shots_on_goal":    _num("Shots on Goal"),
                        "shots_total":      _num("Total Shots"),
                        "possession_pct":   _num("Ball Possession"),
                        "passes_accuracy":  _num("Passes %"),
                        "fouls":            _num("Fouls"),
                        "corners":          _num("Corner Kicks"),
                        "offsides":         _num("Offsides"),
                        "yellow_cards":     _num("Yellow Cards"),
                        "red_cards":        _num("Red Cards"),
                        "saves":            _num("Goalkeeper Saves"),
                        "passes_total":     _num("Total passes"),
                        "blocked_shots":    _num("Blocked Shots"),
                    },
                }
            )

        logger.info(
            "team_id=%d — enriched stats ready for %d fixture(s).",
            team_id,
            len(enriched),
        )
        return enriched

    # ──────────────────────────────────────────────────────────────────────
    # BONUS — WEATHER (used for pitch-condition modelling)
    # ──────────────────────────────────────────────────────────────────────

    def get_weather_for_venue(
        self,
        city: str,
        match_date: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetch current or forecast weather for a venue city.

        Parameters
        ----------
        city       : str  — e.g. "Bucharest", "Milan"
        match_date : str  — "YYYY-MM-DD".  If today or None → current weather.
                            If future (≤14 days) → forecast.

        Returns
        -------
        dict with keys: temp_c, feels_like_c, condition, wind_kph,
                        precip_mm, humidity, is_day
        """
        target = match_date or date.today().isoformat()
        today  = date.today().isoformat()

        try:
            if target <= today:
                endpoint = f"{WEATHER_API_URL}/current.json"
                params   = {"key": self._weather_key, "q": city, "aqi": "no"}
                logger.info(
                    "Fetching CURRENT weather for '%s' …", city
                )
                resp = self._session.get(endpoint, params=params, timeout=10)
                if not resp.ok:
                    logger.error(
                        "Weather API error %s for city '%s'.", resp.status_code, city
                    )
                    return {}
                data = resp.json()
                current = data["current"]
                return {
                    "temp_c":       current["temp_c"],
                    "feels_like_c": current["feelslike_c"],
                    "condition":    current["condition"]["text"],
                    "wind_kph":     current["wind_kph"],
                    "precip_mm":    current["precip_mm"],
                    "humidity":     current["humidity"],
                    "is_day":       bool(current["is_day"]),
                }
            else:
                endpoint = f"{WEATHER_API_URL}/forecast.json"
                params   = {
                    "key": self._weather_key,
                    "q":   city,
                    "dt":  target,
                    "aqi": "no",
                    "alerts": "no",
                }
                logger.info(
                    "Fetching FORECAST weather for '%s' on %s …", city, target
                )
                resp = self._session.get(endpoint, params=params, timeout=10)
                if not resp.ok:
                    logger.error(
                        "Weather API error %s for city '%s'.", resp.status_code, city
                    )
                    return {}
                data = resp.json()
                day_fc = data["forecast"]["forecastday"][0]["day"]
                return {
                    "temp_c":       day_fc["avgtemp_c"],
                    "feels_like_c": day_fc["avgtemp_c"],          # forecast has no feelslike
                    "condition":    day_fc["condition"]["text"],
                    "wind_kph":     day_fc["maxwind_kph"],
                    "precip_mm":    day_fc["totalprecip_mm"],
                    "humidity":     day_fc["avghumidity"],
                    "is_day":       True,
                }

        except (KeyError, IndexError) as exc:
            logger.error(
                "Weather response parsing error for city '%s': %s", city, exc
            )
            return {}
        except requests.exceptions.RequestException as exc:
            logger.error("Weather request failed for '%s': %s", city, exc)
            return {}


# ─────────────────────────────────────────────────────────────────────────────
# DEMO / SMOKE-TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":

    print("\n" + "=" * 70)
    print("  FOOTBALL ORACLE — API Module Smoke Test")
    print("=" * 70 + "\n")

    api = FootballOracleAPI()

    # ── 1. Today's fixtures for selected leagues ──────────────────────────
    print("\n[TEST 1] Today's Fixtures — Romania SuperLiga (283) + Serie A (135)")
    print("-" * 60)
    fixtures = api.get_fixtures_for_today(league_ids=[283, 135])
    if fixtures:
        for f in fixtures[:3]:      # print first 3 to keep output readable
            home = f["teams"]["home"]["name"]
            away = f["teams"]["away"]["name"]
            kick = f["fixture"]["date"]
            print(f"  • {home} vs {away}  —  {kick}")
        if len(fixtures) > 3:
            print(f"  … and {len(fixtures) - 3} more fixture(s).")
    else:
        print("  No fixtures found for today (or API quota reached).")

    # ── 2. Standings — Serie A 2024 ───────────────────────────────────────
    print("\n[TEST 2] Standings — Serie A (135), Season 2024")
    print("-" * 60)
    standings_groups = api.get_standings(league_id=135, season=2024)
    if standings_groups:
        first_group: list[dict] = standings_groups[0]
        print(f"  Top 5 teams in group:")
        for entry in first_group[:5]:
            rank  = entry["rank"]
            team  = entry["team"]["name"]
            pts   = entry["points"]
            played = entry["all"]["played"]
            print(f"    {rank:>2}. {team:<28} {pts} pts  ({played} played)")
    else:
        print("  No standings data returned.")

    # ── 3. Pre-match odds — mock fixture ID ───────────────────────────────
    print("\n[TEST 3] Pre-Match Odds — Fixture ID 1035042 (example)")
    print("-" * 60)
    MOCK_FIXTURE_ID = 1035042      # Replace with a real upcoming fixture_id
    odds = api.get_prematch_odds(fixture_id=MOCK_FIXTURE_ID)
    if odds:
        print(f"  Bookmaker : {odds['bookmaker']}")
        print(f"  Home Win  : {odds['home']:.2f}")
        print(f"  Draw      : {odds['draw']:.2f}")
        print(f"  Away Win  : {odds['away']:.2f}")
    else:
        print("  No odds data returned for this fixture.")

    # ── 4. Last 5 fixture stats — Juventus (team_id=496) ─────────────────
    print("\n[TEST 4] Last 5 Match Stats — Juventus (team_id=496)")
    print("-" * 60)
    MOCK_TEAM_ID = 496              # Juventus on API-Football
    stats_list = api.get_last_fixtures_stats(team_id=MOCK_TEAM_ID, last_n=5)
    if stats_list:
        for item in stats_list:
            meta  = item["fixture_meta"]
            stats = item["team_stats"]
            print(
                f"  [{meta['date']}] {meta['home_team']} vs {meta['away_team']}  "
                f"({meta['home_goals']}-{meta['away_goals']})  "
                f"Result={meta['result']}  "
                f"Shots={stats['shots_total']:.0f}  "
                f"Possession={stats['possession_pct']:.0f}%"
            )
    else:
        print("  No stats returned for this team.")

    # ── 5. Weather — Bucharest ────────────────────────────────────────────
    print("\n[TEST 5] Weather — Bucharest (current)")
    print("-" * 60)
    weather = api.get_weather_for_venue(city="Bucharest")
    if weather:
        print(f"  Condition  : {weather['condition']}")
        print(f"  Temperature: {weather['temp_c']} °C (feels like {weather['feels_like_c']} °C)")
        print(f"  Wind       : {weather['wind_kph']} km/h")
        print(f"  Precip     : {weather['precip_mm']} mm")
        print(f"  Humidity   : {weather['humidity']}%")
    else:
        print("  No weather data returned.")

    print("\n" + "=" * 70)
    print("  Smoke test complete.")
    print("=" * 70 + "\n")
