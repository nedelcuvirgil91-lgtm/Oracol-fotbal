"""
================================================================================
FOOTBALL ORACLE — Hybrid API Layer v2.2
================================================================================
Module  : oracle_api.py

CHANGES v2.2 (SportAPI integration):
  - SportAPI (sportapi7.p.rapidapi.com) added as primary stats source
  - _fetch_sportapi_team_stats()    → team_seasonstatistics (real xG data)
  - _fetch_sportapi_team_events()   → team recent form (last N matches)
  - _fetch_sportapi_h2h()           → H2H via event/{id}/h2h/events
  - _resolve_sportapi_team_id()     → name→ID via scheduled-events lookup
  - SportAPI ID cache (disc) to avoid repeated lookups
  - All mappings imported from mappings.py
  - normalize_team_name() + match_key() dedup everywhere
  - _validate_api_keys() at startup
  - ELO disc cache 24h
  - /scores Odds API for recent form fallback

  STATS CASCADE (per team):
    0. SportAPI team_seasonstatistics  ← NEW PRIMARY
    1. SportAPI team_events (recent)   ← NEW
    2. Odds API /scores (recent form)
    3. fd.org standings
    4. TheSportsDB last events
    5. ELO sigmoid (always blended)
    6. Neutral defaults

  H2H CASCADE:
    0. SportAPI event/{id}/h2h/events  ← NEW PRIMARY
    1. Odds API /scores (fallback)

  MATCHES CASCADE:
    1. The Odds API /events
    2. football-data.org
    3. ESPN public API
    4. TheSportsDB
    5. Demo mode

================================================================================
"""

from __future__ import annotations

import json
import logging
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

from mappings import (
    ODDS_SPORT_KEYS,
    SPORT_KEY_TO_LEAGUE,
    FD_COMPETITIONS,
    ESPN_LEAGUE_SLUGS,
    TSDB_LEAGUE_IDS,
    LEAGUE_BASELINES,
    ELO_RATINGS_FALLBACK,
    normalize_team_name,
    match_key,
)

# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────
ODDS_API_KEY      = "b0e2ab9bcda1d9f4c5ddfe1063c81cd7"
FOOTBALL_DATA_KEY = "3934542be32c47f88a194f9eec0f44a1"
WEATHER_API_KEY   = "48a5b54b8ced45cc924153231263005"
SPORTAPI_KEY      = "2ff60d8248msh65d53a6d077e4abp145f79jsn980ab63d585f"

# ─────────────────────────────────────────────────────────────────────────────
# BASE URLs
# ─────────────────────────────────────────────────────────────────────────────
FOOTBALL_DATA_URL = "https://api.football-data.org/v4"
ODDS_API_URL      = "https://api.the-odds-api.com/v4"
THESPORTSDB_URL   = "https://www.thesportsdb.com/api/v1/json/3"
ESPN_API_URL      = "https://site.api.espn.com/apis/site/v2/sports/soccer"
WEATHER_URL       = "http://api.weatherapi.com/v1"
ELO_URL           = "https://www.eloratings.net"
SPORTAPI_URL      = "https://sportapi7.p.rapidapi.com/api/v1"
SPORTAPI_HOST     = "sportapi7.p.rapidapi.com"

DEFAULT_SEASON = 2026

# ─────────────────────────────────────────────────────────────────────────────
# SportAPI — league → uniqueTournamentId + seasonId
# Confirmed from JSON responses
# ─────────────────────────────────────────────────────────────────────────────
SPORTAPI_TOURNAMENTS: dict[str, dict] = {
    "Premier League":    {"id": 17,   "season": 61627},
    "La Liga":           {"id": 8,    "season": 61643},
    "Serie A":           {"id": 23,   "season": 61644},
    "Bundesliga":        {"id": 35,   "season": 77333},
    "Ligue 1":           {"id": 34,   "season": 61645},
    "Champions League":  {"id": 7,    "season": 76953},
    "Europa League":     {"id": 679,  "season": 76963},
    "Romania SuperLiga": {"id": 238,  "season": 63814},
    "World Cup 2026":    {"id": 16,   "season": 56672},
    "MLS":               {"id": 242,  "season": 57317},
}

# ─────────────────────────────────────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR          = Path(__file__).parent
CACHE_DIR         = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)
ELO_CACHE_PATH    = CACHE_DIR / "elo_cache.json"
SCORES_CACHE_PATH = CACHE_DIR / "scores_cache.json"
SPORTAPI_ID_CACHE = CACHE_DIR / "sportapi_ids.json"   # team name → SportAPI ID

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
# USER-AGENTS
# ─────────────────────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


def _ua() -> str:
    return random.choice(USER_AGENTS)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────────────────────────────────────

def _build_session() -> Session:
    s = Session()
    r = Retry(
        total=3, backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=["GET"], raise_on_status=False,
    )
    a = HTTPAdapter(max_retries=r)
    s.mount("https://", a)
    s.mount("http://",  a)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# DISC CACHE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _disc_load(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _disc_save(path: Path, data: dict) -> None:
    try:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as exc:
        logger.warning("[DiscCache] Save failed %s: %s", path.name, exc)


def _disc_fresh(path: Path, max_age_hours: int = 24) -> bool:
    try:
        if not path.exists():
            return False
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        return (
            datetime.now(timezone.utc) - mtime
        ).total_seconds() < max_age_hours * 3600
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# DEMO FIXTURES
# ─────────────────────────────────────────────────────────────────────────────
_WC2026_FIXTURES = [
    ("United States", "Serbia",     "2026-06-11", "21:00:00", "New York"),
    ("Panama",        "Morocco",    "2026-06-12", "18:00:00", "Los Angeles"),
    ("Mexico",        "Poland",     "2026-06-12", "21:00:00", "Dallas"),
    ("Saudi Arabia",  "Belgium",    "2026-06-13", "00:00:00", "Miami"),
    ("Brazil",        "Croatia",    "2026-06-13", "18:00:00", "San Francisco"),
    ("Japan",         "Colombia",   "2026-06-13", "21:00:00", "Seattle"),
    ("England",       "Netherlands","2026-06-14", "21:00:00", "Chicago"),
    ("Senegal",       "Iran",       "2026-06-14", "18:00:00", "Toronto"),
    ("France",        "Australia",  "2026-06-15", "21:00:00", "Montreal"),
    ("Denmark",       "Tunisia",    "2026-06-15", "18:00:00", "Kansas City"),
    ("Germany",       "Japan",      "2026-06-16", "21:00:00", "Boston"),
    ("Spain",         "Costa Rica", "2026-06-16", "18:00:00", "Philadelphia"),
    ("Argentina",     "Peru",       "2026-06-17", "21:00:00", "Atlanta"),
    ("Canada",        "Ecuador",    "2026-06-17", "18:00:00", "Vancouver"),
    ("Portugal",      "Ghana",      "2026-06-18", "21:00:00", "Guadalajara"),
    ("Uruguay",       "South Korea","2026-06-18", "18:00:00", "Monterrey"),
]
_MLS_FIXTURES = [
    ("Inter Miami",      "LA Galaxy",          "2026-06-11", "23:30:00", "Miami"),
    ("NYCFC",            "Seattle Sounders",   "2026-06-13", "23:30:00", "New York"),
    ("Portland Timbers", "San Jose Earthquakes","2026-06-14","02:30:00","Portland"),
    ("Atlanta United",   "Orlando City",       "2026-06-15", "23:00:00", "Atlanta"),
    ("Club de Foot Montréal","Toronto FC",     "2026-06-17", "23:30:00", "Montreal"),
]
_SUPERLIGA_FIXTURES = [
    ("FCSB",            "CFR Cluj",            "2026-06-14", "19:00:00", "Bucharest"),
    ("Rapid București", "Universitatea Craiova","2026-06-15","16:30:00","Bucharest"),
    ("Farul Constanța", "Petrolul Ploiești",   "2026-06-16", "20:00:00", "Constanta"),
]


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class FootballOracleAPI:
    """
    Hybrid data layer v2.2.
    SportAPI as primary stats source. Cascade fallbacks preserved.
    """

    def __init__(self) -> None:
        self._s   = _build_session()
        self._mem: dict[str, tuple[Any, datetime]] = {}
        self._ttl = 30
        self._dead_keys: set[str] = set()

        # Persistent disc caches
        self._elo_cache:      dict[str, int]  = _disc_load(ELO_CACHE_PATH)
        self._scores_cache:   dict[str, list] = _disc_load(SCORES_CACHE_PATH)
        self._sportapi_ids:   dict[str, int]  = _disc_load(SPORTAPI_ID_CACHE)

        self._active_sport_keys: set[str] = set()
        self._validate_api_keys()

        logger.info("FootballOracleAPI v2.2 (SportAPI edition) initialised.")

    # ══════════════════════════════════════════════════════════════════════
    # MEMORY CACHE
    # ══════════════════════════════════════════════════════════════════════

    def _cget(self, key: str) -> Any | None:
        if key in self._mem:
            v, ts = self._mem[key]
            ttl = 240 if key.startswith("odds_") else self._ttl
            if (datetime.now(timezone.utc) - ts).total_seconds() < ttl * 60:
                return v
        return None

    def _cset(self, key: str, val: Any) -> None:
        self._mem[key] = (val, datetime.now(timezone.utc))

    # ══════════════════════════════════════════════════════════════════════
    # LOW-LEVEL HTTP
    # ══════════════════════════════════════════════════════════════════════

    def _get(self, url: str, headers: dict | None = None,
             params: dict | None = None, timeout: int = 12) -> dict | list | None:
        try:
            r = self._s.get(
                url, headers=headers or {}, params=params or {}, timeout=timeout
            )
            if r.status_code == 404:
                logger.warning("[HTTP 404] %s", url[:80])
                return None
            if r.status_code == 403:
                logger.warning("[HTTP 403] %s", url[:80])
                return None
            if r.status_code == 429:
                logger.warning("[HTTP 429] Rate limit: %s", url[:80])
                return None
            if not r.ok:
                logger.warning("[HTTP %s] %s", r.status_code, url[:80])
                return None
            return r.json()
        except Exception as exc:
            logger.error("[HTTP] %s → %s", url[:80], exc)
            return None

    def _sportapi_get(self, path: str, params: dict | None = None) -> dict | None:
        """GET wrapper with SportAPI RapidAPI headers."""
        return self._get(
            f"{SPORTAPI_URL}/{path}",
            headers={
                "x-rapidapi-key":  SPORTAPI_KEY,
                "x-rapidapi-host": SPORTAPI_HOST,
            },
            params=params or {},
        )

    # ══════════════════════════════════════════════════════════════════════
    # STARTUP — API KEY VALIDATION
    # ══════════════════════════════════════════════════════════════════════

    def _validate_api_keys(self) -> None:
        data = self._get(
            f"{ODDS_API_URL}/sports",
            params={"apiKey": ODDS_API_KEY, "all": "true"},
        )
        if not isinstance(data, list):
            logger.warning("[Validate] Could not fetch sport keys.")
            return
        active = {s["key"] for s in data if not s.get("has_outrights", False)}
        self._active_sport_keys = active
        for league, sk in ODDS_SPORT_KEYS.items():
            if sk not in active:
                self._dead_keys.add(sk)
                logger.info("[Validate] Dead: %s → %s", league, sk)

    # ══════════════════════════════════════════════════════════════════════
    # SPORTAPI — TEAM ID RESOLVER
    # ══════════════════════════════════════════════════════════════════════

    def _resolve_sportapi_team_id(self, team_name: str, league: str) -> int | None:
        """
        Resolve canonical team name → SportAPI numeric team ID.

        Strategy:
        1. Check disc cache (sportapi_ids.json)
        2. Fetch scheduled events for today from SportAPI
        3. Match team name against homeTeam/awayTeam in events
        4. Save to disc cache
        """
        canonical = normalize_team_name(team_name)

        # Check cache first
        if canonical in self._sportapi_ids:
            return self._sportapi_ids[canonical]

        # ── Fetch today's events to find team IDs ──────────────────────────
        today_dt = date.today()
        today = f"{today_dt.year}/{today_dt.month:02d}/{today_dt.day:02d}"
        data = self._sportapi_get(f"sport/Football/scheduled-events/{today}")

        if not data or "events" not in data:
            # Try yesterday too
            yest_dt   = date.today() - timedelta(days=1)
            yesterday = f"{yest_dt.year}/{yest_dt.month:02d}/{yest_dt.day:02d}"
            data = self._sportapi_get(
                f"sport/Football/scheduled-events/{yesterday}"
            )

        if not data or "events" not in data:
            return None

        found: dict[str, int] = {}
        for ev in data.get("events", []):
            for side in ("homeTeam", "awayTeam"):
                team = ev.get(side, {})
                raw_name = team.get("name", "")
                tid = team.get("id")
                if raw_name and tid:
                    c = normalize_team_name(raw_name)
                    found[c] = int(tid)

        # Save all found teams to disc cache
        if found:
            self._sportapi_ids.update(found)
            _disc_save(SPORTAPI_ID_CACHE, self._sportapi_ids)

        return found.get(canonical)

    # ══════════════════════════════════════════════════════════════════════
    # SPORTAPI — TEAM SEASON STATISTICS  (primary stats source)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_sportapi_team_stats(
        self, team_id: int, league: str
    ) -> dict | None:
        """
        Fetch full season statistics from SportAPI.
        Returns processed dict ready for _build_profile().

        Uses team_seasonstatistics endpoint:
        GET /team/{id}/season/statistics?uniqueTournamentId=X&seasonId=Y&type=overall
        """
        tournament = SPORTAPI_TOURNAMENTS.get(league)
        if not tournament:
            return None

        cache_key = f"sportapi_stats_{team_id}_{league}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        data = self._sportapi_get(
            f"team/{team_id}/season/statistics",
            params={
                "uniqueTournamentId": tournament["id"],
                "seasonId":           tournament["season"],
                "type":               "overall",
            },
        )

        if not data or "statistics" not in data:
            self._cset(cache_key, None)
            return None

        s = data["statistics"]
        matches = int(s.get("matches", 1)) or 1

        result = {
            "matches":          matches,
            "avg_goals_for":    round(s.get("goalsScored",   0) / matches, 3),
            "avg_goals_against":round(s.get("goalsConceded", 0) / matches, 3),
            "avg_shots_on_target": round(s.get("shotsOnTarget", 0) / matches, 3),
            "avg_shots_total":  round(s.get("shots", 0) / matches, 3),
            "avg_possession":   round(float(s.get("averageBallPossession", 50.0)), 1),
            "big_chances_per_game": round(s.get("bigChances", 0) / matches, 3),
            "clean_sheets":     int(s.get("cleanSheets", 0)),
            "shots_on_target_against": round(
                s.get("shotsOnTargetAgainst", 0) / matches, 3
            ),
            "source": "sportapi-seasonstatistics",
        }

        logger.info(
            "[SportAPI-Stats] %s in %s: %.2f gf, %.2f ga, %.1f%% pos",
            team_id, league,
            result["avg_goals_for"],
            result["avg_goals_against"],
            result["avg_possession"],
        )

        self._cset(cache_key, result)
        return result

    # ══════════════════════════════════════════════════════════════════════
    # SPORTAPI — TEAM RECENT EVENTS  (form source)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_sportapi_team_events(
        self, team_id: int, last_n: int = 5
    ) -> list[dict]:
        """
        Fetch last N completed events for a team.
        GET /team/{id}/events/previous/0

        Returns list of normalised stat dicts for _build_profile().
        """
        cache_key = f"sportapi_events_{team_id}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        data = self._sportapi_get(f"team/{team_id}/events/previous/0")
        if not data or "events" not in data:
            self._cset(cache_key, [])
            return []

        results: list[dict] = []
        for ev in data["events"]:
            try:
                status = ev.get("status", {}).get("type", "")
                if status != "finished":
                    continue

                home_id  = ev.get("homeTeam", {}).get("id")
                hs = int(ev.get("homeScore", {}).get("current", 0) or 0)
                as_ = int(ev.get("awayScore", {}).get("current", 0) or 0)
                is_home = home_id == team_id

                gf = hs if is_home else as_
                ga = as_ if is_home else hs
                wc = ev.get("winnerCode", 0)

                if wc == 0 or wc == 3:
                    result = "D"
                elif (wc == 1 and is_home) or (wc == 2 and not is_home):
                    result = "W"
                else:
                    result = "L"

                ts = ev.get("startTimestamp", 0)
                ev_date = (
                    datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                    if ts else ""
                )

                results.append({
                    "date":          ev_date,
                    "result":        result,
                    "goals_for":     gf,
                    "goals_against": ga,
                    "shots_on_goal": round(gf * 3.5, 1),
                    "possession":    50.0,
                    "event_id":      ev.get("id"),
                })
            except (TypeError, ValueError):
                continue

        results = results[-last_n:]
        self._cset(cache_key, results)
        logger.info(
            "[SportAPI-Events] team %s: %d recent events.", team_id, len(results)
        )
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SPORTAPI — H2H
    # ══════════════════════════════════════════════════════════════════════

    def fetch_sportapi_h2h(
        self, event_id: int, home_name: str, away_name: str
    ) -> dict | None:
        """
        Fetch H2H events for a specific fixture.
        GET /event/{eventId}/h2h/events

        Returns H2H summary dict for oracle_engine._build_h2h().
        """
        cache_key = f"sportapi_h2h_{event_id}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        data = self._sportapi_get(f"event/{event_id}/h2h/events")
        if not data or "events" not in data:
            self._cset(cache_key, None)
            return None

        home_c = normalize_team_name(home_name)
        away_c = normalize_team_name(away_name)

        meetings: list[dict] = []
        for ev in data["events"][:10]:  # last 10 max
            try:
                status = ev.get("status", {}).get("type", "")
                if status != "finished":
                    continue

                h_name = normalize_team_name(ev.get("homeTeam", {}).get("name", ""))
                a_name = normalize_team_name(ev.get("awayTeam", {}).get("name", ""))
                hs = int(ev.get("homeScore", {}).get("current", 0) or 0)
                as_ = int(ev.get("awayScore", {}).get("current", 0) or 0)

                is_home_first = h_name == home_c
                gf = hs if is_home_first else as_
                ga = as_ if is_home_first else hs

                wc = ev.get("winnerCode", 0)
                if wc == 3 or wc == 0:
                    outcome = "D"
                elif (wc == 1 and is_home_first) or (wc == 2 and not is_home_first):
                    outcome = "H"
                else:
                    outcome = "A"

                meetings.append({
                    "outcome":    outcome,
                    "home_goals": gf,
                    "away_goals": ga,
                })
            except (TypeError, ValueError):
                continue

        if not meetings:
            self._cset(cache_key, None)
            return None

        n          = len(meetings)
        home_wins  = sum(1 for m in meetings if m["outcome"] == "H")
        draws      = sum(1 for m in meetings if m["outcome"] == "D")
        away_wins  = sum(1 for m in meetings if m["outcome"] == "A")
        home_g_avg = round(sum(m["home_goals"] for m in meetings) / n, 2)
        away_g_avg = round(sum(m["away_goals"] for m in meetings) / n, 2)
        last_5     = [m["outcome"] for m in meetings[:5]]

        dominance    = (home_wins - away_wins) / n
        h2h_modifier = round(dominance * 0.15, 4)

        summary = (
            f"H2H ({n} meciuri): {home_wins}W {draws}D {away_wins}L  "
            f"| Goluri: {home_g_avg:.1f}–{away_g_avg:.1f}  "
            f"| Ultimele: {''.join(last_5)}"
        )

        result = {
            "meetings":       n,
            "home_wins":      home_wins,
            "draws":          draws,
            "away_wins":      away_wins,
            "home_goals_avg": home_g_avg,
            "away_goals_avg": away_g_avg,
            "last_5":         last_5,
            "h2h_modifier":   h2h_modifier,
            "summary":        summary,
        }

        self._cset(cache_key, result)
        logger.info("[SportAPI-H2H] %s vs %s: %s", home_name, away_name, summary)
        return result

    # ══════════════════════════════════════════════════════════════════════
    # SPORTAPI — SCHEDULED EVENTS (match source)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_sportapi_matches(
        self, target_date: str, league: str
    ) -> list[dict]:
        """
        Fetch scheduled matches from SportAPI for a specific date.
        Also populates _sportapi_ids cache as a side effect.
        """
        tournament = SPORTAPI_TOURNAMENTS.get(league)
        cache_key  = f"sportapi_matches_{target_date}_{league}"
        cached     = self._cget(cache_key)
        if cached is not None:
            return cached

        target_dt  = date.fromisoformat(target_date)
        date_fmt   = f"{target_dt.year}/{target_dt.month:02d}/{target_dt.day:02d}"
        data = self._sportapi_get(f"sport/Football/scheduled-events/{date_fmt}")
        if not data or "events" not in data:
            self._cset(cache_key, [])
            return []

        results: list[dict] = []
        for ev in data.get("events", []):
            try:
                # Filter by league if we have tournament info
                if tournament:
                    ev_tournament_id = ev.get("uniqueTournament", {}).get("id")
                    if ev_tournament_id != tournament["id"]:
                        continue

                status = ev.get("status", {}).get("type", "")
                if status not in ("notstarted", "inprogress"):
                    continue

                home_raw = ev.get("homeTeam", {}).get("name", "")
                away_raw = ev.get("awayTeam", {}).get("name", "")
                home_id  = ev.get("homeTeam", {}).get("id")
                away_id  = ev.get("awayTeam", {}).get("id")

                home = normalize_team_name(home_raw)
                away = normalize_team_name(away_raw)

                if not home or not away:
                    continue

                # Cache team IDs
                if home_id:
                    self._sportapi_ids[home] = int(home_id)
                if away_id:
                    self._sportapi_ids[away] = int(away_id)

                ts   = ev.get("startTimestamp", 0)
                ko_utc = (
                    datetime.fromtimestamp(ts, tz=timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ")
                    if ts else f"{target_date}T00:00:00Z"
                )

                results.append({
                    "fixture_id":        f"sportapi_{ev['id']}",
                    "home_team":         home,
                    "away_team":         away,
                    "home_team_id":      f"sportapi_{home_id}",
                    "away_team_id":      f"sportapi_{away_id}",
                    "_sportapi_home_id": home_id,
                    "_sportapi_away_id": away_id,
                    "_sportapi_event_id":ev["id"],
                    "kickoff_utc":       ko_utc,
                    "kickoff_date":      target_date,
                    "league":            league,
                    "season":            DEFAULT_SEASON,
                    "venue_city":        ev.get("venue", {}).get("city", {}).get("name", ""),
                    "status":            "scheduled",
                    "home_odds":         None,
                    "draw_odds":         None,
                    "away_odds":         None,
                    "odds_source":       None,
                    "source":            "sportapi",
                })
            except (KeyError, TypeError):
                continue

        if results:
            _disc_save(SPORTAPI_ID_CACHE, self._sportapi_ids)

        logger.info(
            "[SportAPI-Matches] %d events for %s on %s.",
            len(results), league, target_date,
        )
        self._cset(cache_key, results)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # PUBLIC — GET TEAM STATS (used by oracle_engine._build_profile)
    # ══════════════════════════════════════════════════════════════════════

    def get_sportapi_stats(
        self, team_name: str, league: str
    ) -> dict | None:
        """
        Primary stats entry point for oracle_engine.
        Returns season stats dict or None.
        """
        canonical = normalize_team_name(team_name)

        # Get SportAPI team ID (from cache or lookup)
        team_id = self._sportapi_ids.get(canonical)
        if not team_id:
            team_id = self._resolve_sportapi_team_id(canonical, league)

        if not team_id:
            logger.info(
                "[SportAPI] No ID for '%s' in %s.", team_name, league
            )
            return None

        return self._fetch_sportapi_team_stats(int(team_id), league)

    def get_sportapi_recent_form(
        self, team_name: str, last_n: int = 5
    ) -> list[dict]:
        """Recent form from SportAPI team events."""
        canonical = normalize_team_name(team_name)
        team_id   = self._sportapi_ids.get(canonical)
        if not team_id:
            return []
        return self._fetch_sportapi_team_events(int(team_id), last_n)

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE — The Odds API /events
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_events_odds_api(
        self, sport_key: str, days_ahead: int = 7
    ) -> list[dict]:
        if sport_key in self._dead_keys:
            return []

        cache_key = f"events_{sport_key}_{days_ahead}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)
        data = self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/events",
            params={
                "apiKey":            ODDS_API_KEY,
                "commenceTimeFrom":  now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "commenceTo": (
                    now + timedelta(days=days_ahead)
                ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )

        if data is None:
            self._dead_keys.add(sport_key)
            self._cset(cache_key, [])
            return []

        if not isinstance(data, list):
            self._cset(cache_key, [])
            return []

        league_name = SPORT_KEY_TO_LEAGUE.get(sport_key, sport_key)
        results: list[dict] = []

        for ev in data:
            try:
                ko   = ev.get("commence_time", "")
                home = normalize_team_name(ev["home_team"])
                away = normalize_team_name(ev["away_team"])
                results.append({
                    "fixture_id":   f"odds_{ev['id']}",
                    "home_team":    home,
                    "away_team":    away,
                    "home_team_id": None,
                    "away_team_id": None,
                    "kickoff_utc":  ko,
                    "kickoff_date": ko[:10] if ko else "",
                    "league":       league_name,
                    "season":       DEFAULT_SEASON,
                    "venue_city":   "",
                    "status":       "scheduled",
                    "home_odds":    None,
                    "draw_odds":    None,
                    "away_odds":    None,
                    "odds_source":  None,
                    "source":       "the-odds-api",
                    "_odds_api_id": ev["id"],
                    "_sport_key":   sport_key,
                })
            except (KeyError, TypeError):
                continue

        logger.info(
            "[OddsAPI-Events] %d events for %s.", len(results), sport_key
        )
        self._cset(cache_key, results)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE — Odds API /scores  (recent form fallback)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_scores_odds_api(
        self, sport_key: str, days_back: int = 3
    ) -> list[dict]:
        if sport_key in self._dead_keys:
            return []

        disc_key = f"{sport_key}_{days_back}"
        if _disc_fresh(SCORES_CACHE_PATH, max_age_hours=6):
            disc = _disc_load(SCORES_CACHE_PATH)
            if disc_key in disc:
                return disc[disc_key]

        data = self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/scores",
            params={"apiKey": ODDS_API_KEY, "daysFrom": days_back},
        )

        if not isinstance(data, list):
            return []

        results: list[dict] = []
        for ev in data:
            try:
                if not ev.get("completed"):
                    continue
                scores   = ev.get("scores") or []
                home_raw = ev.get("home_team", "")
                away_raw = ev.get("away_team", "")
                home     = normalize_team_name(home_raw)
                away     = normalize_team_name(away_raw)

                sm: dict[str, int] = {}
                for sc in scores:
                    sm[normalize_team_name(sc["name"])] = int(sc.get("score", 0))

                hs = sm.get(home, sm.get(home_raw, 0))
                as_ = sm.get(away, sm.get(away_raw, 0))
                ko  = ev.get("commence_time", "")

                results.append({
                    "home_team":   home,
                    "away_team":   away,
                    "home_score":  hs,
                    "away_score":  as_,
                    "kickoff_utc": ko,
                    "kickoff_date":ko[:10] if ko else "",
                    "league": SPORT_KEY_TO_LEAGUE.get(
                        ev.get("sport_key", ""), ""
                    ),
                    "source": "the-odds-api-scores",
                })
            except (KeyError, TypeError, ValueError):
                continue

        disc = _disc_load(SCORES_CACHE_PATH)
        disc[disc_key] = results
        _disc_save(SCORES_CACHE_PATH, disc)
        logger.info(
            "[OddsAPI-Scores] %d results for %s.", len(results), sport_key
        )
        return results

    def get_team_recent_form(
        self, team_name: str, league: str, days_back: int = 14
    ) -> list[dict]:
        """Recent form via Odds API /scores (fallback for nationals)."""
        canonical = normalize_team_name(team_name)
        sport_key = ODDS_SPORT_KEYS.get(league)
        raw       = self._fetch_scores_odds_api(
            sport_key, days_back=min(days_back, 3)
        ) if sport_key else []

        form: list[dict] = []
        for s in raw:
            if s["home_team"] != canonical and s["away_team"] != canonical:
                continue
            is_home = s["home_team"] == canonical
            gf = s["home_score"] if is_home else s["away_score"]
            ga = s["away_score"] if is_home else s["home_score"]
            result = "W" if gf > ga else ("L" if gf < ga else "D")
            form.append({
                "date":          s["kickoff_date"],
                "result":        result,
                "goals_for":     gf,
                "goals_against": ga,
                "shots_on_goal": round(gf * 3.5, 1),
                "possession":    50.0,
            })

        return sorted(form, key=lambda x: x["date"], reverse=True)

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE — football-data.org
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_fd(
        self, date_from: str, date_to: str,
        comp_codes: list[str] | None = None
    ) -> list[dict]:
        params: dict = {
            "dateFrom": date_from, "dateTo": date_to,
            "status":   "SCHEDULED,TIMED",
        }
        if comp_codes:
            params["competitions"] = ",".join(comp_codes)

        data = self._get(
            f"{FOOTBALL_DATA_URL}/matches",
            headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
            params=params,
        )
        if not data:
            return []

        results: list[dict] = []
        for m in data.get("matches", []):
            try:
                ko   = m.get("utcDate", "")
                home = normalize_team_name(m["homeTeam"]["name"])
                away = normalize_team_name(m["awayTeam"]["name"])
                hid  = str(m["homeTeam"].get("id", ""))
                aid  = str(m["awayTeam"].get("id", ""))
                results.append({
                    "fixture_id":   f"fd_{m['id']}",
                    "home_team":    home,
                    "away_team":    away,
                    "home_team_id": f"fd_{hid}",
                    "away_team_id": f"fd_{aid}",
                    "kickoff_utc":  ko,
                    "kickoff_date": ko[:10] if ko else date_from,
                    "league":       m.get("competition", {}).get("name", "Unknown"),
                    "season":       DEFAULT_SEASON,
                    "venue_city":   m.get("area", {}).get("name", ""),
                    "status":       m.get("status", "SCHEDULED").lower(),
                    "home_odds": None, "draw_odds": None, "away_odds": None,
                    "odds_source": None, "source": "football-data.org",
                })
            except (KeyError, TypeError):
                continue

        logger.info(
            "[FD.org] %d matches (%s→%s).", len(results), date_from, date_to
        )
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE — ESPN
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_espn(
        self, league: str, target_date: str
    ) -> list[dict]:
        slug = ESPN_LEAGUE_SLUGS.get(league)
        if not slug:
            return []

        cache_key = f"espn_{slug}_{target_date}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        data = self._get(
            f"{ESPN_API_URL}/{slug}/scoreboard",
            headers={"User-Agent": _ua()},
            params={"dates": target_date.replace("-", "")},
        )
        if not data:
            self._cset(cache_key, [])
            return []

        results: list[dict] = []
        for ev in data.get("events", []):
            try:
                comps       = ev.get("competitions", [{}])[0]
                competitors = comps.get("competitors", [])
                if len(competitors) < 2:
                    continue
                home = next(
                    (c for c in competitors if c.get("homeAway") == "home"),
                    competitors[0],
                )
                away = next(
                    (c for c in competitors if c.get("homeAway") == "away"),
                    competitors[1],
                )
                hn = normalize_team_name(
                    home.get("team", {}).get("displayName", "")
                )
                an = normalize_team_name(
                    away.get("team", {}).get("displayName", "")
                )
                if not hn or not an:
                    continue
                state = ev.get("status", {}).get("type", {}).get("state", "pre")
                if state not in ("pre", "in"):
                    continue
                date_str = ev.get("date", "")
                results.append({
                    "fixture_id":   f"espn_{ev['id']}",
                    "home_team":    hn,
                    "away_team":    an,
                    "home_team_id": f"espn_{home.get('team',{}).get('id','')}",
                    "away_team_id": f"espn_{away.get('team',{}).get('id','')}",
                    "kickoff_utc":  date_str,
                    "kickoff_date": date_str[:10] if date_str else target_date,
                    "league":       league,
                    "season":       DEFAULT_SEASON,
                    "venue_city":   comps.get("venue", {}).get(
                        "address", {}
                    ).get("city", ""),
                    "status":       "scheduled",
                    "home_odds": None, "draw_odds": None, "away_odds": None,
                    "odds_source": None, "source": "espn",
                })
            except (KeyError, TypeError, IndexError):
                continue

        logger.info(
            "[ESPN] %d events for %s on %s.", len(results), league, target_date
        )
        self._cset(cache_key, results)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE — TheSportsDB
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_tsdb(
        self, league_id: str, league_name: str
    ) -> list[dict]:
        data = self._get(
            f"{THESPORTSDB_URL}/eventsnextleague.php",
            params={"id": league_id},
        )
        if not data:
            return []

        today   = date.today().isoformat()
        results: list[dict] = []

        for ev in data.get("events") or []:
            try:
                ev_date = ev.get("dateEvent", "")
                ev_time = ev.get("strTime", "00:00:00") or "00:00:00"
                ko_utc  = f"{ev_date}T{ev_time[:8]}Z" if ev_date else ""
                if ev_date and ev_date < today:
                    continue
                results.append({
                    "fixture_id":   f"tsdb_{ev['idEvent']}",
                    "home_team":    normalize_team_name(ev.get("strHomeTeam", "")),
                    "away_team":    normalize_team_name(ev.get("strAwayTeam", "")),
                    "home_team_id": f"tsdb_{ev.get('idHomeTeam','')}",
                    "away_team_id": f"tsdb_{ev.get('idAwayTeam','')}",
                    "kickoff_utc":  ko_utc,
                    "kickoff_date": ev_date,
                    "league":       league_name,
                    "season":       DEFAULT_SEASON,
                    "venue_city":   ev.get("strVenue", ""),
                    "status":       "scheduled",
                    "home_odds": None, "draw_odds": None, "away_odds": None,
                    "odds_source": None, "source": "thesportsdb",
                })
            except (KeyError, TypeError):
                continue

        logger.info("[TSDB] %d events for %s.", len(results), league_name)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE — Demo mode
    # ══════════════════════════════════════════════════════════════════════

    def _generate_demo_matches(self, competitions: list[str]) -> list[dict]:
        today  = date.today()
        cutoff = today + timedelta(days=10)
        demo_id = 90000
        results: list[dict] = []

        sets = [
            ("World Cup 2026",    _WC2026_FIXTURES),
            ("MLS",               _MLS_FIXTURES),
            ("Romania SuperLiga", _SUPERLIGA_FIXTURES),
        ]
        for league_name, fixtures in sets:
            if league_name not in competitions and competitions:
                continue
            for home, away, match_date, ko_time, city in fixtures:
                md = date.fromisoformat(match_date)
                if not (today <= md <= cutoff):
                    continue
                demo_id += 1
                results.append({
                    "fixture_id":   f"demo_{demo_id}",
                    "home_team":    normalize_team_name(home),
                    "away_team":    normalize_team_name(away),
                    "home_team_id": f"demo_h_{demo_id}",
                    "away_team_id": f"demo_a_{demo_id}",
                    "kickoff_utc":  f"{match_date}T{ko_time}Z",
                    "kickoff_date": match_date,
                    "league":       league_name,
                    "season":       DEFAULT_SEASON,
                    "venue_city":   city,
                    "status":       "scheduled",
                    "home_odds": None, "draw_odds": None, "away_odds": None,
                    "odds_source": None,
                    "source": f"demo-{league_name.lower().replace(' ','-')}",
                })

        logger.info("[Demo] Generated %d demo matches.", len(results))
        return results

    # ══════════════════════════════════════════════════════════════════════
    # ELO RATINGS
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_elo_ratings(self) -> dict[str, int]:
        mem = self._cget("elo_ratings")
        if mem is not None:
            return mem

        if _disc_fresh(ELO_CACHE_PATH, max_age_hours=24) and self._elo_cache:
            self._cset("elo_ratings", self._elo_cache)
            return self._elo_cache

        if not BS4_AVAILABLE:
            logger.warning("[ELO] BeautifulSoup not installed.")
            return {}

        logger.info("[ELO] Scraping eloratings.net…")
        try:
            r = self._s.get(
                ELO_URL,
                headers={"User-Agent": _ua(), "Accept-Language": "en-US,en;q=0.9"},
                timeout=15,
            )
            if not r.ok:
                return {}

            from bs4 import BeautifulSoup
            soup    = BeautifulSoup(r.text, "html.parser")
            ratings: dict[str, int] = {}
            table   = soup.find("table")

            if table:
                for row in table.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if len(cells) < 3:
                        continue
                    try:
                        raw_name = cells[1].get_text(strip=True)
                        raw_elo  = cells[2].get_text(strip=True).replace(",", "")
                        elo_val  = int(raw_elo)
                        canonical = normalize_team_name(raw_name)
                        if canonical and elo_val > 0:
                            ratings[canonical] = elo_val
                    except (ValueError, IndexError):
                        continue

            if ratings:
                _disc_save(ELO_CACHE_PATH, ratings)
                self._elo_cache = ratings
                self._cset("elo_ratings", ratings)
            else:
                # Scraping a eșuat — folosim fallback hardcodat
                logger.info("[ELO] Scraping returned 0 teams — using hardcoded fallback.")
                ratings = {k: v for k, v in ELO_RATINGS_FALLBACK.items()}
                self._elo_cache = ratings
                self._cset("elo_ratings", ratings)

            logger.info("[ELO] %d team ratings available.", len(ratings))
            return ratings

        except Exception as exc:
            logger.error("[ELO] Scrape failed: %s", exc)
            return {}

    def get_elo_rating(self, team_name: str) -> int | None:
        canonical = normalize_team_name(team_name)
        ratings   = self._fetch_elo_ratings()
        result    = ratings.get(canonical)
        if result is None:
            # Check hardcoded fallback directly
            result = ELO_RATINGS_FALLBACK.get(canonical)
            if result:
                logger.info("[ELO] %s found in hardcoded fallback: %d", canonical, result)
        return result

    # ══════════════════════════════════════════════════════════════════════
    # LEGACY STATS (clubs — fd.org + TSDB)
    # ══════════════════════════════════════════════════════════════════════

    def get_team_form_fd(self, team_id: str, comp_code: str) -> dict | None:
        tid = team_id.replace("fd_", "")
        if not tid.isdigit():
            return None
        cache_key = f"standings_{comp_code}"
        cached = self._cget(cache_key)
        if cached is None:
            cached = self._get(
                f"{FOOTBALL_DATA_URL}/competitions/{comp_code}/standings",
                headers={"X-Auth-Token": FOOTBALL_DATA_KEY},
            )
            if cached:
                self._cset(cache_key, cached)
        if not cached:
            return None
        for grp in cached.get("standings", []):
            for entry in grp.get("table", []):
                if str(entry.get("team", {}).get("id", "")) == tid:
                    played = entry.get("playedGames") or 1
                    return {
                        "played":        played,
                        "goals_for":     entry.get("goalsFor", 0),
                        "goals_against": entry.get("goalsAgainst", 0),
                        "form":          entry.get("form", "") or "",
                        "avg_gf":  round((entry.get("goalsFor",  0) or 0) / played, 3),
                        "avg_ga":  round((entry.get("goalsAgainst",0) or 0)/ played, 3),
                    }
        return None

    def get_team_last_events_tsdb(self, team_id: str) -> list[dict]:
        tid = team_id.replace("tsdb_", "")
        if not tid.isdigit():
            return []
        data = self._get(
            f"{THESPORTSDB_URL}/eventslast.php", params={"id": tid}
        )
        if not data:
            return []
        results: list[dict] = []
        for ev in data.get("results") or []:
            try:
                hs = int(ev.get("intHomeScore") or 0)
                as_ = int(ev.get("intAwayScore") or 0)
                is_home = ev.get("idHomeTeam") == tid
                gf = hs if is_home else as_
                ga = as_ if is_home else hs
                results.append({
                    "date": ev.get("dateEvent", ""),
                    "result": "W" if gf > ga else ("L" if gf < ga else "D"),
                    "goals_for":     gf,
                    "goals_against": ga,
                    "shots_on_goal": round(gf * 3.5, 1),
                    "possession":    50.0,
                })
            except (ValueError, TypeError):
                continue
        return results

    def get_team_stats(self, team_id: str, league: str = "") -> list[dict]:
        if team_id and team_id.startswith("tsdb_"):
            return self.get_team_last_events_tsdb(team_id)
        return []

    def get_standings_form(self, team_id: str, league: str) -> dict | None:
        comp_code = FD_COMPETITIONS.get(league)
        if comp_code and team_id and team_id.startswith("fd_"):
            return self.get_team_form_fd(team_id, comp_code)
        return None

    # ══════════════════════════════════════════════════════════════════════
    # ODDS
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_odds(self, sport_key: str) -> dict[str, dict]:
        if sport_key in self._dead_keys:
            return {}
        cache_key = f"odds_{sport_key}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        data = self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/odds",
            params={
                "apiKey": ODDS_API_KEY, "regions": "eu",
                "markets": "h2h", "oddsFormat": "decimal",
            },
        )
        if not isinstance(data, list):
            if data is None:
                self._dead_keys.add(sport_key)
            self._cset(cache_key, {})
            return {}

        result: dict[str, dict] = {}
        for ev in data:
            home_raw = ev.get("home_team", "")
            away_raw = ev.get("away_team", "")
            home = normalize_team_name(home_raw)
            away = normalize_team_name(away_raw)
            ev_id = ev.get("id", "")
            bh = bd = ba = 0.0
            bk_name = ""
            for bk in ev.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt.get("key") != "h2h":
                        continue
                    om: dict[str, float] = {}
                    for o in mkt.get("outcomes", []):
                        om[normalize_team_name(o["name"])] = float(
                            o.get("price", 0)
                        )
                    h = om.get(home, 0.0)
                    d = om.get("Draw", 0.0)
                    a = om.get(away, 0.0)
                    if h > bh:
                        bh = h; bk_name = bk.get("title", "")
                    if d > bd:
                        bd = d
                    if a > ba:
                        ba = a
            if bh > 1.0:
                entry = {
                    "home": bh, "draw": bd, "away": ba,
                    "bookmaker": bk_name, "ev_id": ev_id,
                }
                result[f"{home}||{away}"] = entry
                result[ev_id]             = entry

        self._cset(cache_key, result)
        return result

    def _attach_odds(self, matches: list[dict]) -> list[dict]:
        league_odds: dict[str, dict] = {}
        for m in matches:
            if m.get("home_odds"):
                continue
            league    = m.get("league", "")
            sport_key = ODDS_SPORT_KEYS.get(league)
            ev_id     = m.get("_odds_api_id", "")
            if not sport_key or sport_key in self._dead_keys:
                continue
            if sport_key not in league_odds:
                league_odds[sport_key] = self._fetch_odds(sport_key)
            od = league_odds[sport_key]
            if not od:
                continue
            odds = od.get(ev_id)
            if not odds:
                h = normalize_team_name(m["home_team"])
                a = normalize_team_name(m["away_team"])
                odds = od.get(f"{h}||{a}")
            if odds:
                m["home_odds"]   = odds["home"]
                m["draw_odds"]   = odds["draw"]
                m["away_odds"]   = odds["away"]
                m["odds_source"] = f"The Odds API ({odds.get('bookmaker','')})"
        return matches

    # ══════════════════════════════════════════════════════════════════════
    # WEATHER
    # ══════════════════════════════════════════════════════════════════════

    def get_weather(self, city: str, match_date: str | None = None) -> dict:
        base = {
            "temp_c": 15.0, "condition": "Clear", "wind_kph": 10.0,
            "precip_mm": 0.0, "humidity": 50,
            "xg_penalty": 0.0,
            "description": "☀️  Clear conditions — no xG penalty.",
        }
        if not city or city in ("Unknown", ""):
            return base

        target = match_date or date.today().isoformat()
        today  = date.today().isoformat()

        try:
            if target <= today:
                url    = f"{WEATHER_URL}/current.json"
                params = {"key": WEATHER_API_KEY, "q": city, "aqi": "no"}
            else:
                url    = f"{WEATHER_URL}/forecast.json"
                params = {"key": WEATHER_API_KEY, "q": city, "dt": target, "aqi": "no"}

            r = self._s.get(url, params=params, timeout=10)
            if not r.ok:
                return base
            data = r.json()

            if target <= today:
                cur       = data["current"]
                temp_c    = cur["temp_c"]
                condition = cur["condition"]["text"]
                wind_kph  = cur["wind_kph"]
                precip_mm = cur["precip_mm"]
                humidity  = cur["humidity"]
            else:
                day       = data["forecast"]["forecastday"][0]["day"]
                temp_c    = day["avgtemp_c"]
                condition = day["condition"]["text"]
                wind_kph  = day["maxwind_kph"]
                precip_mm = day["totalprecip_mm"]
                humidity  = day["avghumidity"]

            penalty = 0.0
            notes   = []
            cl      = condition.lower()

            for bc in ["heavy rain","torrential","blizzard","heavy snow",
                       "thunderstorm","sleet","freezing"]:
                if bc in cl:
                    penalty += 0.08; notes.append("severe weather"); break
            else:
                if "rain" in cl or "drizzle" in cl:
                    penalty += 0.04; notes.append("light rain")
                elif "snow" in cl:
                    penalty += 0.06; notes.append("snow")

            if precip_mm > 15:
                penalty += 0.04; notes.append("heavy precip")
            elif precip_mm > 5:
                penalty += 0.02; notes.append("light precip")
            if wind_kph > 70:
                penalty += 0.04; notes.append("strong wind")
            elif wind_kph > 50:
                penalty += 0.02; notes.append("moderate wind")
            if temp_c < 0:
                penalty += 0.03; notes.append("freezing")
            elif temp_c > 38:
                penalty += 0.02; notes.append("extreme heat")

            penalty = min(penalty, 0.15)
            desc = (
                f"{'⚠️' if penalty > 0.06 else '🌧️'}  {condition} | "
                f"{', '.join(notes)} → xG -{penalty*100:.0f}%"
                if notes else
                f"☀️  {condition} | {temp_c}°C | No xG penalty."
            )
            return {
                "temp_c": temp_c, "condition": condition,
                "wind_kph": wind_kph, "precip_mm": precip_mm,
                "humidity": humidity, "xg_penalty": round(penalty, 3),
                "description": desc,
            }
        except Exception as exc:
            logger.warning("[Weather] %s: %s", city, exc)
            return base

    # ══════════════════════════════════════════════════════════════════════
    # PUBLIC — MAIN FETCH
    # ══════════════════════════════════════════════════════════════════════

    def get_matches_for_week(
        self,
        days_ahead:   int = 7,
        competitions: list[str] | None = None,
    ) -> list[dict]:
        today    = date.today()
        end_date = today + timedelta(days=days_ahead)
        d_from   = today.isoformat()
        d_to     = end_date.isoformat()

        cache_key = (
            f"week_{d_from}_{days_ahead}_"
            f"{','.join(sorted(competitions or []))}"
        )
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        matches:   list[dict] = []
        seen_keys: set[str]   = set()

        def _add(new_matches: list[dict]) -> None:
            for m in new_matches:
                mk = match_key(
                    m.get("home_team", ""),
                    m.get("away_team", ""),
                    m.get("kickoff_date", ""),
                )
                if mk not in seen_keys:
                    seen_keys.add(mk)
                    matches.append(m)

        comps = competitions or list(ODDS_SPORT_KEYS.keys())

        # ── Source 1: The Odds API events ─────────────────────────────────
        logger.info("[Week] Fetching from The Odds API…")
        priority = ["World Cup 2026"] + [c for c in comps if c != "World Cup 2026"]
        for league in priority:
            sk = ODDS_SPORT_KEYS.get(league)
            if sk:
                _add(self._fetch_events_odds_api(sk, days_ahead))
        logger.info("[Week] After OddsAPI: %d unique", len(matches))

        # ── Source 2: SportAPI scheduled events ───────────────────────────
        logger.info("[Week] Fetching from SportAPI…")
        for i in range(min(days_ahead, 7)):
            target = (today + timedelta(days=i)).isoformat()
            for league in comps:
                if league in SPORTAPI_TOURNAMENTS:
                    _add(self._fetch_sportapi_matches(target, league))
        logger.info("[Week] After SportAPI: %d unique", len(matches))

        # ── Source 3: football-data.org ───────────────────────────────────
        logger.info("[Week] Fetching from FD.org…")
        fd_codes = [
            FD_COMPETITIONS[c] for c in comps if c in FD_COMPETITIONS
        ] or None
        _add(self._fetch_matches_fd(d_from, d_to, fd_codes))
        logger.info("[Week] After FD.org: %d unique", len(matches))

        # ── Source 4: ESPN ────────────────────────────────────────────────
        logger.info("[Week] Fetching from ESPN…")
        for i in range(min(days_ahead, 7)):
            target = (today + timedelta(days=i)).isoformat()
            for league in comps:
                if ESPN_LEAGUE_SLUGS.get(league):
                    _add(self._fetch_matches_espn(league, target))
        logger.info("[Week] After ESPN: %d unique", len(matches))

        # ── Source 5: TheSportsDB ─────────────────────────────────────────
        if len(matches) < 5:
            for league in comps:
                lid = TSDB_LEAGUE_IDS.get(league)
                if lid:
                    _add(self._fetch_matches_tsdb(lid, league))
            logger.info("[Week] After TSDB: %d unique", len(matches))

        # ── Source 6: Demo mode ───────────────────────────────────────────
        if len(matches) < 3:
            _add(self._generate_demo_matches(comps))
            logger.info("[Week] After Demo: %d unique", len(matches))

        # ── Filter + attach odds + sort ───────────────────────────────────
        matches = [
            m for m in matches
            if d_from <= m.get("kickoff_date", "9999") <= d_to
        ]
        matches = self._attach_odds(matches)
        matches.sort(key=lambda m: m.get("kickoff_utc", ""))

        logger.info("[Week] Final: %d matches.", len(matches))
        self._cset(cache_key, matches)
        return matches

    def get_matches_for_date(self, target_date: str) -> list[dict]:
        return [
            m for m in self.get_matches_for_week(days_ahead=7)
            if m.get("kickoff_date") == target_date
        ]

    def clear_cache(self) -> None:
        self._mem.clear()
        self._dead_keys.clear()
        logger.info("Memory cache and dead-keys cleared.")
