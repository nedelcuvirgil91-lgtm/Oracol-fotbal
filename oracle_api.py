"""
================================================================================
FOOTBALL ORACLE — API Integration Module
================================================================================
Module  : oracle_api.py
Season  : 2026  (World Cup 2026 compatible)
Purpose : Centralised HTTP client for API-Football, WeatherAPI.
          All responses returned as clean Python dicts/lists for Pandas.
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
# HARDCODED CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────
API_FOOTBALL_KEY: str = "c4e7610bf0334935d0f90801863e1801"
API_FOOTBALL_URL: str = "https://v3.football.api-sports.io"

CLAUDE_API_KEY: str = (
    "sk-ant-api03-7BpVPcu5LlZ-N_M0TN7Y7c6cdKfgC70-"
    "enal2gR4ASopn1h9wFkBlsJcLYP8qjv52CUww8pSdb6e-fFft8MD7Q-HO6OoAAA"
)

WEATHER_API_KEY: str = "48a5b54b8ced45cc924153231263005"
WEATHER_API_URL: str = "http://api.weatherapi.com/v1"

# Default season — World Cup 2026 era
DEFAULT_SEASON: int = 2026

# World Cup 2026 league IDs (API-Football)
WORLD_CUP_2026_IDS: list[int] = [1]   # ID 1 = FIFA World Cup on API-Football

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
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
    if response.status_code == 429:
        logger.error("[%s] Rate-limit exceeded (HTTP 429).", endpoint)
        return None
    if response.status_code == 403:
        logger.error("[%s] Forbidden (HTTP 403). Check your API key.", endpoint)
        return None
    if not response.ok:
        logger.error("[%s] HTTP %s — %s", endpoint, response.status_code, response.text[:200])
        return None
    try:
        body: dict[str, Any] = response.json()
    except ValueError:
        logger.error("[%s] Response is not valid JSON.", endpoint)
        return None
    errors = body.get("errors", {})
    if errors:
        logger.error("[%s] API-Football error: %s", endpoint, errors)
        return None
    results: int = body.get("results", 0)
    logger.info("[%s] OK — %d result(s).", endpoint, results)
    return body


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class FootballOracleAPI:
    """
    Centralised API client for Football Oracle.
    All public methods return [] or {} on error — never None.
    Season default: 2026 (World Cup 2026 compatible).
    """

    BET365_BOOKMAKER_ID: int = 1
    MARKET_1X2: str = "Match Winner"

    def __init__(self) -> None:
        self._session: Session = _build_retry_session()
        self._af_headers: dict[str, str] = {
            "x-apisports-key": API_FOOTBALL_KEY,
            "Accept": "application/json",
        }
        self._weather_key: str = WEATHER_API_KEY
        logger.info(
            "FootballOracleAPI initialised — Default season: %d", DEFAULT_SEASON
        )

    # ──────────────────────────────────────────────────────────────────────
    # PRIVATE
    # ──────────────────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
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
            logger.error("[%s] Timed out.", endpoint)
        except requests.exceptions.RequestException as exc:
            logger.error("[%s] Request error: %s", endpoint, exc)
        return None

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIC — PRE-MATCH DATA
    # ──────────────────────────────────────────────────────────────────────

    def get_fixtures_for_today(
        self,
        league_ids: list[int],
        season: int = DEFAULT_SEASON,
    ) -> list[dict[str, Any]]:
        """
        Fetch today's fixtures for every league ID provided.
        Season is required by API-Football v3 — defaults to 2026.

        Parameters
        ----------
        league_ids : list[int]  e.g. [283, 135, 39, 1]
        season     : int        e.g. 2026
        """
        today_str: str = date.today().isoformat()
        all_fixtures: list[dict[str, Any]] = []

        for league_id in league_ids:
            logger.info(
                "Fixtures for league=%d season=%d on %s …",
                league_id, season, today_str,
            )
            body = self._get(
                "fixtures",
                params={
                    "league": league_id,
                    "season": season,
                    "date":   today_str,
                },
            )
            if body is None:
                logger.warning("Skipping league=%d — no data.", league_id)
                continue
            fixtures = body.get("response", [])
            logger.info("league=%d → %d fixture(s).", league_id, len(fixtures))
            all_fixtures.extend(fixtures)

        logger.info(
            "Total fixtures across %d league(s): %d", len(league_ids), len(all_fixtures)
        )
        return all_fixtures

    def get_standings(
        self, league_id: int, season: int = DEFAULT_SEASON
    ) -> list[dict[str, Any]]:
        """
        Fetch standings for a given league & season.
        Default season = 2026.
        """
        logger.info("Standings — league=%d, season=%d …", league_id, season)
        body = self._get("standings", params={"league": league_id, "season": season})
        if body is None:
            return []
        try:
            groups: list[dict] = body["response"][0]["league"]["standings"]
            logger.info("league=%d — %d group(s).", league_id, len(groups))
            return groups
        except (IndexError, KeyError, TypeError) as exc:
            logger.error("Standings parse error league=%d: %s", league_id, exc)
            return []

    def get_prematch_odds(self, fixture_id: int) -> dict[str, Any]:
        """
        Fetch 1X2 odds from Bet365. Falls back to first available bookmaker.
        Returns dict with home/draw/away decimal odds, or {}.
        """
        logger.info("Odds — fixture=%d …", fixture_id)
        body = self._get(
            "odds",
            params={"fixture": fixture_id, "bookmaker": self.BET365_BOOKMAKER_ID},
        )
        if body is None or not body.get("response"):
            logger.warning("No Bet365 odds for fixture=%d. Retrying without filter…", fixture_id)
            body = self._get("odds", params={"fixture": fixture_id})
            if body is None or not body.get("response"):
                logger.error("No odds for fixture=%d.", fixture_id)
                return {}

        try:
            bookmakers: list[dict] = body["response"][0].get("bookmakers", [])
            chosen = next(
                (b for b in bookmakers if b.get("id") == self.BET365_BOOKMAKER_ID),
                bookmakers[0] if bookmakers else None,
            )
            if chosen is None:
                return {}

            bets = chosen.get("bets", [])
            market = next((b for b in bets if b.get("name") == self.MARKET_1X2), None)
            if market is None:
                return {}

            odds_map: dict[str, float] = {}
            for v in market.get("values", []):
                odds_map[v.get("value", "").lower()] = float(v.get("odd", 0))

            result = {
                "fixture_id": fixture_id,
                "bookmaker":  chosen.get("name", "Unknown"),
                "home":       odds_map.get("home", 0.0),
                "draw":       odds_map.get("draw", 0.0),
                "away":       odds_map.get("away", 0.0),
                "raw":        bets,
            }
            logger.info(
                "fixture=%d odds: H=%.2f D=%.2f A=%.2f",
                fixture_id, result["home"], result["draw"], result["away"],
            )
            return result

        except (IndexError, KeyError, TypeError, ValueError) as exc:
            logger.error("Odds parse error fixture=%d: %s", fixture_id, exc)
            return {}

    def get_last_fixtures_stats(
        self, team_id: int, last_n: int = 5, season: int = DEFAULT_SEASON
    ) -> list[dict[str, Any]]:
        """
        Fetch stats for the last N finished matches for a team.
        Includes season parameter for 2026 compatibility.

        Returns list of dicts with fixture_meta + team_stats.
        """
        logger.info(
            "Last %d stats — team=%d, season=%d …", last_n, team_id, season
        )
        fixtures_body = self._get(
            "fixtures",
            params={"team": team_id, "last": last_n, "status": "FT", "season": season},
        )
        if fixtures_body is None:
            return []

        fixtures = fixtures_body.get("response", [])
        if not fixtures:
            # Fallback: try without season filter (some national team data)
            logger.warning(
                "No FT fixtures for team=%d season=%d. Trying without season…",
                team_id, season,
            )
            fixtures_body = self._get(
                "fixtures",
                params={"team": team_id, "last": last_n, "status": "FT"},
            )
            if fixtures_body is None:
                return []
            fixtures = fixtures_body.get("response", [])

        if not fixtures:
            logger.warning("team=%d — no finished fixtures found.", team_id)
            return []

        logger.info("team=%d — %d fixture(s) to process.", team_id, len(fixtures))
        enriched: list[dict[str, Any]] = []

        for fix in fixtures:
            fixture_id: int = fix["fixture"]["id"]
            fixture_date: str = fix["fixture"]["date"][:10]
            home_team: str = fix["teams"]["home"]["name"]
            away_team: str = fix["teams"]["away"]["name"]
            home_goals: int = fix["goals"]["home"] or 0
            away_goals: int = fix["goals"]["away"] or 0

            stats_body = self._get(
                "fixtures/statistics",
                params={"fixture": fixture_id, "team": team_id},
            )
            if stats_body is None:
                continue

            stats_response = stats_body.get("response", [])
            if not stats_response:
                continue

            raw_stats = stats_response[0].get("statistics", [])
            stat_map: dict[str, Any] = {s["type"]: s["value"] for s in raw_stats}

            def _num(key: str) -> float:
                raw = stat_map.get(key)
                if raw is None:
                    return 0.0
                if isinstance(raw, str):
                    return float(raw.replace("%", "").strip() or 0)
                return float(raw)

            team_is_home: bool = fix["teams"]["home"]["id"] == team_id
            goals_for     = home_goals if team_is_home else away_goals
            goals_against = away_goals if team_is_home else home_goals
            if goals_for > goals_against:
                result_label = "W"
            elif goals_for < goals_against:
                result_label = "L"
            else:
                result_label = "D"

            enriched.append({
                "fixture_meta": {
                    "fixture_id":    fixture_id,
                    "date":          fixture_date,
                    "home_team":     home_team,
                    "away_team":     away_team,
                    "home_goals":    home_goals,
                    "away_goals":    away_goals,
                    "team_is_home":  team_is_home,
                    "result":        result_label,
                    "goals_for":     goals_for,
                    "goals_against": goals_against,
                },
                "team_stats": {
                    "shots_on_goal":   _num("Shots on Goal"),
                    "shots_total":     _num("Total Shots"),
                    "possession_pct":  _num("Ball Possession"),
                    "passes_accuracy": _num("Passes %"),
                    "fouls":           _num("Fouls"),
                    "corners":         _num("Corner Kicks"),
                    "offsides":        _num("Offsides"),
                    "yellow_cards":    _num("Yellow Cards"),
                    "red_cards":       _num("Red Cards"),
                    "saves":           _num("Goalkeeper Saves"),
                    "passes_total":    _num("Total passes"),
                    "blocked_shots":   _num("Blocked Shots"),
                },
            })

        logger.info("team=%d — enriched %d fixtures.", team_id, len(enriched))
        return enriched

    # ──────────────────────────────────────────────────────────────────────
    # WEATHER
    # ──────────────────────────────────────────────────────────────────────

    def get_weather_for_venue(
        self, city: str, match_date: str | None = None
    ) -> dict[str, Any]:
        """
        Current or forecast weather for a venue city.
        Returns dict with temp_c, condition, wind_kph, precip_mm, humidity.
        """
        target = match_date or date.today().isoformat()
        today  = date.today().isoformat()

        try:
            if target <= today:
                endpoint = f"{WEATHER_API_URL}/current.json"
                params   = {"key": self._weather_key, "q": city, "aqi": "no"}
                resp = self._session.get(endpoint, params=params, timeout=10)
                if not resp.ok:
                    return {}
                cur = resp.json()["current"]
                return {
                    "temp_c":       cur["temp_c"],
                    "feels_like_c": cur["feelslike_c"],
                    "condition":    cur["condition"]["text"],
                    "wind_kph":     cur["wind_kph"],
                    "precip_mm":    cur["precip_mm"],
                    "humidity":     cur["humidity"],
                    "is_day":       bool(cur["is_day"]),
                }
            else:
                endpoint = f"{WEATHER_API_URL}/forecast.json"
                params   = {
                    "key": self._weather_key, "q": city,
                    "dt": target, "aqi": "no", "alerts": "no",
                }
                resp = self._session.get(endpoint, params=params, timeout=10)
                if not resp.ok:
                    return {}
                day = resp.json()["forecast"]["forecastday"][0]["day"]
                return {
                    "temp_c":       day["avgtemp_c"],
                    "feels_like_c": day["avgtemp_c"],
                    "condition":    day["condition"]["text"],
                    "wind_kph":     day["maxwind_kph"],
                    "precip_mm":    day["totalprecip_mm"],
                    "humidity":     day["avghumidity"],
                    "is_day":       True,
                }

        except (KeyError, IndexError) as exc:
            logger.error("Weather parse error '%s': %s", city, exc)
            return {}
        except requests.exceptions.RequestException as exc:
            logger.error("Weather request failed '%s': %s", city, exc)
            return {}


# ─────────────────────────────────────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  FOOTBALL ORACLE API — Smoke Test (Season 2026)")
    print("=" * 65 + "\n")

    api = FootballOracleAPI()

    print("[1] Today's Fixtures — Romania SuperLiga (283) + Serie A (135)")
    fixtures = api.get_fixtures_for_today([283, 135])
    for f in fixtures[:3]:
        print(f"  • {f['teams']['home']['name']} vs {f['teams']['away']['name']}")
    print(f"  Total: {len(fixtures)} fixtures\n")

    print("[2] Standings — Serie A (135), Season 2026")
    grp = api.get_standings(135, season=2026)
    if grp:
        for e in grp[0][:3]:
            print(f"  {e['rank']}. {e['team']['name']} — {e['points']} pts")
    print()

    print("[3] Weather — Bucharest")
    w = api.get_weather_for_venue("Bucharest")
    if w:
        print(f"  {w['condition']}, {w['temp_c']}°C, Rain={w['precip_mm']}mm")
    print()

    print("=" * 65 + "\n")
