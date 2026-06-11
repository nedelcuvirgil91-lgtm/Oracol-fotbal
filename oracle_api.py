"""
================================================================================
FOOTBALL ORACLE — Hybrid API Layer v2.0 (Fixed + World Cup 2026)
================================================================================
Module  : oracle_api.py

CHANGES v2.0 (2026-06-11):
  - Added World Cup 2026 (started today!) as primary data source
  - Fixed The Odds API sport keys (between-season handling)
  - Replaced SofaScore (403) with ESPN public API
  - Added OpenLigaDB for Bundesliga
  - Added demo/simulation mode when all sources offline
  - Smarter between-season detection

  MATCHES (cascade):
    1. The Odds API /events  (World Cup + active leagues, 0 credits)
    2. football-data.org /matches (major leagues)
    3. ESPN public API      (free, no key, good coverage)
    4. TheSportsDB          (fallback general)
    5. Demo mode            (simulated data when between seasons)

  ODDS (cascade):
    1. The Odds API /odds   (real odds, cache 4h)
    2. Estimated from model (fallback)

  STATS (cascade):
    1. football-data.org standings + form
    2. TheSportsDB last events
    3. Neutral league defaults

  WEATHER:
    WeatherAPI → xG penalty

================================================================================
"""

from __future__ import annotations

import logging
import random
import sys
import time
from datetime import date, datetime, timedelta, timezone
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

# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────
ODDS_API_KEY      = "b0e2ab9bcda1d9f4c5ddfe1063c81cd7"
FOOTBALL_DATA_KEY = "3934542be32c47f88a194f9eec0f44a1"
WEATHER_API_KEY   = "48a5b54b8ced45cc924153231263005"

# ─────────────────────────────────────────────────────────────────────────────
# BASE URLs
# ─────────────────────────────────────────────────────────────────────────────
FOOTBALL_DATA_URL = "https://api.football-data.org/v4"
ODDS_API_URL      = "https://api.the-odds-api.com/v4"
THESPORTSDB_URL   = "https://www.thesportsdb.com/api/v1/json/3"
ESPN_API_URL      = "https://site.api.espn.com/apis/site/v2/sports/soccer"
WEATHER_URL       = "http://api.weatherapi.com/v1"

# ─────────────────────────────────────────────────────────────────────────────
# LEAGUE MAPPINGS — Updated for 2026 season state
# ─────────────────────────────────────────────────────────────────────────────

# The Odds API sport keys — verified active keys
# NOTE: Between-season leagues return 404, handled gracefully
ODDS_SPORT_KEYS: dict[str, str] = {
    "World Cup 2026":    "soccer_fifa_world_cup",          # ACTIVE NOW
    "Premier League":    "soccer_epl",
    "La Liga":           "soccer_spain_la_liga",
    "Serie A":           "soccer_italy_serie_a",
    "Bundesliga":        "soccer_germany_bundesliga",
    "Ligue 1":           "soccer_france_ligue_one",
    "Champions League":  "soccer_uefa_champs_league",
    "Europa League":     "soccer_uefa_europa_league",
    "Romania SuperLiga": "soccer_romania_1_liga",
    "MLS":               "soccer_usa_mls",                 # Active in summer
    "Eredivisie":        "soccer_netherlands_eredivisie",
    "Primeira Liga":     "soccer_portugal_primeira_liga",
}

# football-data.org competition codes
FD_COMPETITIONS: dict[str, str] = {
    "Premier League":    "PL",
    "La Liga":           "PD",
    "Serie A":           "SA",
    "Bundesliga":        "BL1",
    "Ligue 1":           "FL1",
    "Champions League":  "CL",
    "Europa League":     "EL",
    "World Cup 2026":    "WC",
}

# ESPN league slugs (public API, no auth)
ESPN_LEAGUE_SLUGS: dict[str, str] = {
    "World Cup 2026":    "fifa.world",
    "Premier League":    "eng.1",
    "La Liga":           "esp.1",
    "Serie A":           "ita.1",
    "Bundesliga":        "ger.1",
    "Ligue 1":           "fra.1",
    "Champions League":  "uefa.champions",
    "MLS":               "usa.1",
    "Romania SuperLiga": "rou.1",
}

# TheSportsDB league IDs
TSDB_LEAGUE_IDS: dict[str, str] = {
    "Premier League":    "4328",
    "La Liga":           "4335",
    "Serie A":           "4332",
    "Bundesliga":        "4331",
    "Ligue 1":           "4334",
    "Champions League":  "4480",
    "Romania SuperLiga": "4652",
    "World Cup 2026":    "4429",
}

# League baseline xG (avg goals/team/game)
LEAGUE_BASELINES: dict[str, float] = {
    "Premier League":    1.35,
    "La Liga":           1.20,
    "Serie A":           1.25,
    "Bundesliga":        1.40,
    "Ligue 1":           1.30,
    "Champions League":  1.20,
    "Europa League":     1.15,
    "Romania SuperLiga": 1.15,
    "World Cup 2026":    1.25,
    "MLS":               1.40,
    "default":           1.25,
}

DEFAULT_SEASON = 2026

# World Cup 2026 group stage teams (for demo mode)
WC2026_GROUPS = {
    "A": [("USA", "Serbia"), ("Panama", "Morocco")],
    "B": [("Mexico", "Poland"), ("Saudi Arabia", "Belgium")],
    "C": [("Brazil", "Croatia"), ("Japan", "Colombia")],
    "D": [("England", "Netherlands"), ("Senegal", "Iran")],
    "E": [("France", "Australia"), ("Denmark", "Tunisia")],
    "F": [("Germany", "Japan"), ("Spain", "Costa Rica")],
    "G": [("Argentina", "Saudi Arabia"), ("Poland", "Mexico")],
    "H": [("Portugal", "Ghana"), ("Uruguay", "South Korea")],
}

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
# ROTATING USER-AGENTS
# ─────────────────────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
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


class FootballOracleAPI:
    """
    Hybrid data layer v2.0.
    Cascade: The Odds API → FD.org → ESPN → TheSportsDB → Demo.
    """

    def __init__(self) -> None:
        self._s   = _build_session()
        self._mem: dict[str, tuple[Any, datetime]] = {}
        self._ttl = 30   # default cache TTL in minutes
        # Track which sport keys are known-dead this session (404/between-season)
        self._dead_keys: set[str] = set()
        logger.info("FootballOracleAPI v2.0 (World Cup Edition) initialised.")

    # ══════════════════════════════════════════════════════════════════════
    # CACHE
    # ══════════════════════════════════════════════════════════════════════

    def _cget(self, key: str) -> Any | None:
        if key in self._mem:
            v, ts = self._mem[key]
            ttl = self._ttl
            # Odds get 4h TTL
            if key.startswith("odds_"):
                ttl = 240
            if (datetime.now(timezone.utc) - ts).total_seconds() < ttl * 60:
                logger.debug("CACHE HIT: %s", key)
                return v
        return None

    def _cset(self, key: str, val: Any) -> None:
        self._mem[key] = (val, datetime.now(timezone.utc))

    # ══════════════════════════════════════════════════════════════════════
    # LOW-LEVEL REQUESTS
    # ══════════════════════════════════════════════════════════════════════

    def _get(self, url: str, headers: dict | None = None,
             params: dict | None = None, timeout: int = 12) -> dict | list | None:
        try:
            r = self._s.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
            if r.status_code == 404:
                logger.warning("[HTTP 404] %s", url[:80])
                return None
            if r.status_code == 403:
                logger.warning("[HTTP 403] Blocked: %s", url[:80])
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

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE 1 — The Odds API: events (0 credits)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_events_odds_api(self, sport_key: str, days_ahead: int = 7) -> list[dict]:
        """Fetch upcoming events from The Odds API /events endpoint (0 credits)."""
        if sport_key in self._dead_keys:
            return []

        cache_key = f"events_{sport_key}_{days_ahead}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        now = datetime.now(timezone.utc)
        commence_to = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

        data = self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/events",
            params={
                "apiKey": ODDS_API_KEY,
                "commenceTimeFrom": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "commenceTo": commence_to,
            },
        )

        if data is None:
            self._dead_keys.add(sport_key)
            logger.info("[OddsAPI-Events] %s marked as dead (404/error).", sport_key)
            self._cset(cache_key, [])
            return []

        if not isinstance(data, list):
            self._cset(cache_key, [])
            return []

        league_name = next(
            (lg for lg, sk in ODDS_SPORT_KEYS.items() if sk == sport_key),
            sport_key,
        )

        results: list[dict] = []
        for ev in data:
            try:
                ko = ev.get("commence_time", "")
                ko_date = ko[:10] if ko else ""
                results.append({
                    "fixture_id":   f"odds_{ev['id']}",
                    "home_team":    ev["home_team"],
                    "away_team":    ev["away_team"],
                    "home_team_id": None,
                    "away_team_id": None,
                    "kickoff_utc":  ko,
                    "kickoff_date": ko_date,
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

        logger.info("[OddsAPI-Events] %d events for %s.", len(results), sport_key)
        self._cset(cache_key, results)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE 2 — football-data.org
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_fd(self, date_from: str, date_to: str,
                          comp_codes: list[str] | None = None) -> list[dict]:
        """Fetch matches from football-data.org."""
        params: dict = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "status": "SCHEDULED,TIMED",
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
                ko = m.get("utcDate", "")
                league_name = m.get("competition", {}).get("name", "Unknown")
                home_id = str(m["homeTeam"].get("id", ""))
                away_id = str(m["awayTeam"].get("id", ""))
                results.append({
                    "fixture_id":   f"fd_{m['id']}",
                    "home_team":    m["homeTeam"]["name"],
                    "away_team":    m["awayTeam"]["name"],
                    "home_team_id": f"fd_{home_id}",
                    "away_team_id": f"fd_{away_id}",
                    "kickoff_utc":  ko,
                    "kickoff_date": ko[:10] if ko else date_from,
                    "league":       league_name,
                    "season":       DEFAULT_SEASON,
                    "venue_city":   m.get("area", {}).get("name", ""),
                    "status":       m.get("status", "SCHEDULED").lower(),
                    "home_odds":    None,
                    "draw_odds":    None,
                    "away_odds":    None,
                    "odds_source":  None,
                    "source":       "football-data.org",
                })
            except (KeyError, TypeError):
                continue

        logger.info("[FD.org] %d matches (%s → %s).", len(results), date_from, date_to)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE 3 — ESPN Public API (free, no key, good coverage)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_espn(self, league: str, target_date: str) -> list[dict]:
        """
        Fetch scoreboard from ESPN's public API.
        No API key required. Works for most major leagues + World Cup.
        """
        slug = ESPN_LEAGUE_SLUGS.get(league)
        if not slug:
            return []

        cache_key = f"espn_{slug}_{target_date}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        url = f"{ESPN_API_URL}/{slug}/scoreboard"
        data = self._get(
            url,
            headers={"User-Agent": _ua()},
            params={"dates": target_date.replace("-", "")},
        )

        if not data:
            self._cset(cache_key, [])
            return []

        events = data.get("events", [])
        results: list[dict] = []

        for ev in events:
            try:
                comps = ev.get("competitions", [{}])[0]
                competitors = comps.get("competitors", [])
                if len(competitors) < 2:
                    continue

                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

                home_name = home.get("team", {}).get("displayName", "")
                away_name = away.get("team", {}).get("displayName", "")

                if not home_name or not away_name:
                    continue

                date_str = ev.get("date", "")  # ISO format
                ko_date  = date_str[:10] if date_str else target_date

                status = ev.get("status", {}).get("type", {}).get("state", "pre")
                if status not in ("pre", "in"):
                    continue  # Skip completed matches

                results.append({
                    "fixture_id":   f"espn_{ev['id']}",
                    "home_team":    home_name,
                    "away_team":    away_name,
                    "home_team_id": f"espn_{home.get('team',{}).get('id','')}",
                    "away_team_id": f"espn_{away.get('team',{}).get('id','')}",
                    "kickoff_utc":  date_str,
                    "kickoff_date": ko_date,
                    "league":       league,
                    "season":       DEFAULT_SEASON,
                    "venue_city":   ev.get("competitions", [{}])[0].get("venue", {}).get("address", {}).get("city", ""),
                    "status":       "scheduled",
                    "home_odds":    None,
                    "draw_odds":    None,
                    "away_odds":    None,
                    "odds_source":  None,
                    "source":       "espn",
                })
            except (KeyError, TypeError, IndexError):
                continue

        logger.info("[ESPN] %d events for %s on %s.", len(results), league, target_date)
        self._cset(cache_key, results)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE 4 — TheSportsDB fallback
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_tsdb(self, league_id: str, league_name: str) -> list[dict]:
        """Fetch next 15 events from TheSportsDB (free)."""
        data = self._get(
            f"{THESPORTSDB_URL}/eventsnextleague.php",
            params={"id": league_id},
        )
        if not data:
            return []

        events = data.get("events") or []
        results: list[dict] = []
        today = date.today().isoformat()

        for ev in events:
            try:
                ev_date = ev.get("dateEvent", "")
                ev_time = ev.get("strTime", "00:00:00") or "00:00:00"
                ko_utc = f"{ev_date}T{ev_time[:8]}Z" if ev_date else ""

                if ev_date and ev_date < today:
                    continue

                results.append({
                    "fixture_id":   f"tsdb_{ev['idEvent']}",
                    "home_team":    ev.get("strHomeTeam", ""),
                    "away_team":    ev.get("strAwayTeam", ""),
                    "home_team_id": f"tsdb_{ev.get('idHomeTeam','')}",
                    "away_team_id": f"tsdb_{ev.get('idAwayTeam','')}",
                    "kickoff_utc":  ko_utc,
                    "kickoff_date": ev_date,
                    "league":       league_name,
                    "season":       DEFAULT_SEASON,
                    "venue_city":   ev.get("strVenue", ""),
                    "status":       "scheduled",
                    "home_odds":    None,
                    "draw_odds":    None,
                    "away_odds":    None,
                    "odds_source":  None,
                    "source":       "thesportsdb",
                })
            except (KeyError, TypeError):
                continue

        logger.info("[TSDB] %d events for %s.", len(results), league_name)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE 5 — Demo/simulation mode (between seasons fallback)
    # ══════════════════════════════════════════════════════════════════════

    def _generate_demo_matches(self, competitions: list[str]) -> list[dict]:
        """
        Generate realistic demo matches when all APIs are offline or between seasons.
        Uses World Cup 2026 group stage fixtures (real tournament, started June 11 2026).
        """
        logger.info("[Demo] Generating simulated matches for display purposes.")
        today = date.today()
        results: list[dict] = []
        demo_id = 90000

        # World Cup 2026 group stage matches (June 11 - July 3, 2026)
        wc_matches = [
            # Group A — Opening day
            ("USA", "Serbia", "2026-06-11", "21:00:00", "New York"),
            ("Panama", "Morocco", "2026-06-12", "18:00:00", "Los Angeles"),
            # Group B
            ("Mexico", "Poland", "2026-06-12", "21:00:00", "Dallas"),
            ("Saudi Arabia", "Belgium", "2026-06-13", "00:00:00", "Miami"),
            # Group C
            ("Brazil", "Croatia", "2026-06-13", "18:00:00", "San Francisco"),
            ("Japan", "Colombia", "2026-06-13", "21:00:00", "Seattle"),
            # Group D
            ("England", "Netherlands", "2026-06-14", "21:00:00", "Chicago"),
            ("Senegal", "Iran", "2026-06-14", "18:00:00", "Toronto"),
            # Group E
            ("France", "Australia", "2026-06-15", "21:00:00", "Montreal"),
            ("Denmark", "Tunisia", "2026-06-15", "18:00:00", "Kansas City"),
            # Group F
            ("Germany", "Japan", "2026-06-16", "21:00:00", "Boston"),
            ("Spain", "Costa Rica", "2026-06-16", "18:00:00", "Philadelphia"),
            # Group G
            ("Argentina", "Peru", "2026-06-17", "21:00:00", "Atlanta"),
            ("Canada", "Ecuador", "2026-06-17", "18:00:00", "Vancouver"),
            # Group H
            ("Portugal", "Ghana", "2026-06-18", "21:00:00", "Guadalajara"),
            ("Uruguay", "South Korea", "2026-06-18", "18:00:00", "Monterrey"),
        ]

        # Non-WC summer leagues still active
        summer_matches = [
            ("MLS", [
                ("Inter Miami", "LA Galaxy", "2026-06-11", "23:30:00", "Miami"),
                ("NYCFC", "Seattle Sounders", "2026-06-13", "23:30:00", "New York"),
                ("Portland Timbers", "San Jose Earthquakes", "2026-06-14", "02:30:00", "Portland"),
                ("Atlanta United", "Orlando City", "2026-06-15", "23:00:00", "Atlanta"),
                ("Club de Foot Montréal", "Toronto FC", "2026-06-17", "23:30:00", "Montreal"),
            ]),
            ("Romania SuperLiga", [
                ("FCSB", "CFR Cluj", "2026-06-14", "19:00:00", "Bucharest"),
                ("Rapid București", "Universitatea Craiova", "2026-06-15", "16:30:00", "Bucharest"),
                ("Farul Constanța", "Petrolul Ploiești", "2026-06-16", "20:00:00", "Constanta"),
            ]),
        ]

        # Add World Cup matches if requested
        if "World Cup 2026" in competitions or not competitions:
            for home, away, match_date, ko_time, city in wc_matches:
                match_dt = date.fromisoformat(match_date)
                if match_dt >= today and match_dt <= today + timedelta(days=10):
                    demo_id += 1
                    results.append({
                        "fixture_id":   f"demo_{demo_id}",
                        "home_team":    home,
                        "away_team":    away,
                        "home_team_id": f"demo_h_{demo_id}",
                        "away_team_id": f"demo_a_{demo_id}",
                        "kickoff_utc":  f"{match_date}T{ko_time}Z",
                        "kickoff_date": match_date,
                        "league":       "World Cup 2026",
                        "season":       2026,
                        "venue_city":   city,
                        "status":       "scheduled",
                        "home_odds":    None,
                        "draw_odds":    None,
                        "away_odds":    None,
                        "odds_source":  None,
                        "source":       "demo-wc2026",
                    })

        # Add other summer leagues
        for league_name, fixtures in summer_matches:
            if league_name in competitions or not competitions:
                for home, away, match_date, ko_time, city in fixtures:
                    match_dt = date.fromisoformat(match_date)
                    if match_dt >= today and match_dt <= today + timedelta(days=10):
                        demo_id += 1
                        results.append({
                            "fixture_id":   f"demo_{demo_id}",
                            "home_team":    home,
                            "away_team":    away,
                            "home_team_id": f"demo_h_{demo_id}",
                            "away_team_id": f"demo_a_{demo_id}",
                            "kickoff_utc":  f"{match_date}T{ko_time}Z",
                            "kickoff_date": match_date,
                            "league":       league_name,
                            "season":       2026,
                            "venue_city":   city,
                            "status":       "scheduled",
                            "home_odds":    None,
                            "draw_odds":    None,
                            "away_odds":    None,
                            "odds_source":  None,
                            "source":       "demo",
                        })

        logger.info("[Demo] Generated %d demo matches.", len(results))
        return results

    # ══════════════════════════════════════════════════════════════════════
    # ODDS — The Odds API
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_odds(self, sport_key: str) -> dict[str, dict]:
        """Fetch 1X2 odds. Cached 4h to conserve 500 credits/month."""
        if sport_key in self._dead_keys:
            return {}

        cache_key = f"odds_{sport_key}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        data = self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/odds",
            params={
                "apiKey":     ODDS_API_KEY,
                "regions":    "eu",
                "markets":    "h2h",
                "oddsFormat": "decimal",
            },
        )

        if data is None:
            self._dead_keys.add(sport_key)
            self._cset(cache_key, {})
            return {}

        if not isinstance(data, list):
            self._cset(cache_key, {})
            return {}

        result: dict[str, dict] = {}
        for ev in data:
            home = ev.get("home_team", "")
            away = ev.get("away_team", "")
            ev_id = ev.get("id", "")
            best_h = best_d = best_a = 0.0
            bk_name = ""

            for bk in ev.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt.get("key") != "h2h":
                        continue
                    om: dict[str, float] = {}
                    for o in mkt.get("outcomes", []):
                        om[o["name"]] = float(o.get("price", 0))
                    h = om.get(home, 0.0)
                    d = om.get("Draw", 0.0)
                    a = om.get(away, 0.0)
                    if h > best_h:
                        best_h = h
                        bk_name = bk.get("title", "")
                    if d > best_d:
                        best_d = d
                    if a > best_a:
                        best_a = a

            if best_h > 1.0:
                entry = {"home": best_h, "draw": best_d, "away": best_a,
                         "bookmaker": bk_name, "ev_id": ev_id}
                result[f"{home} vs {away}"] = entry
                result[ev_id] = entry

        self._cset(cache_key, result)
        logger.info("[OddsAPI-Odds] %d events with odds for %s.", len(result) // 2, sport_key)
        return result

    def _attach_odds(self, matches: list[dict]) -> list[dict]:
        """Attach odds to matches, grouped by league to minimise API calls."""
        league_odds: dict[str, dict] = {}

        for m in matches:
            if m.get("home_odds"):
                continue

            league = m.get("league", "")
            sport_key = ODDS_SPORT_KEYS.get(league)
            ev_id = m.get("_odds_api_id", "")

            if not sport_key or sport_key in self._dead_keys:
                continue

            if sport_key not in league_odds:
                league_odds[sport_key] = self._fetch_odds(sport_key)
            od = league_odds[sport_key]
            if not od:
                continue

            # Lookup by event ID first, then exact name, then fuzzy
            odds = od.get(ev_id)
            if not odds:
                odds = od.get(f"{m['home_team']} vs {m['away_team']}")
            if not odds:
                hn = m["home_team"].lower()
                an = m["away_team"].lower()
                for k, v in od.items():
                    kl = k.lower()
                    if len(hn) >= 5 and len(an) >= 5:
                        if hn[:5] in kl and an[:5] in kl:
                            odds = v
                            break

            if odds:
                m["home_odds"]   = odds["home"]
                m["draw_odds"]   = odds["draw"]
                m["away_odds"]   = odds["away"]
                m["odds_source"] = f"The Odds API ({odds.get('bookmaker','')})"

        return matches

    # ══════════════════════════════════════════════════════════════════════
    # STATS — for xG calculation
    # ══════════════════════════════════════════════════════════════════════

    def get_team_form_fd(self, team_id: str, comp_code: str) -> dict | None:
        """Team form/stats from fd.org standings."""
        tid = team_id.replace("fd_", "").replace("tsdb_", "").replace("sofa_", "")
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
                        "position":      entry.get("position"),
                        "played":        played,
                        "won":           entry.get("won", 0),
                        "draw":          entry.get("draw", 0),
                        "lost":          entry.get("lost", 0),
                        "goals_for":     entry.get("goalsFor", 0),
                        "goals_against": entry.get("goalsAgainst", 0),
                        "goal_diff":     entry.get("goalDifference", 0),
                        "points":        entry.get("points", 0),
                        "form":          entry.get("form", "") or "",
                        "avg_gf":        round((entry.get("goalsFor", 0) or 0) / played, 3),
                        "avg_ga":        round((entry.get("goalsAgainst", 0) or 0) / played, 3),
                    }
        return None

    def get_team_last_events_tsdb(self, team_id: str) -> list[dict]:
        """Fetch last 5 events for a team from TheSportsDB."""
        tid = team_id.replace("tsdb_", "")
        if not tid.isdigit():
            return []

        data = self._get(
            f"{THESPORTSDB_URL}/eventslast.php",
            params={"id": tid},
        )
        if not data:
            return []

        events = data.get("results") or []
        results: list[dict] = []

        for ev in events:
            try:
                home_score = int(ev.get("intHomeScore") or 0)
                away_score = int(ev.get("intAwayScore") or 0)
                is_home = ev.get("idHomeTeam") == tid
                gf = home_score if is_home else away_score
                ga = away_score if is_home else home_score
                results.append({
                    "date":          ev.get("dateEvent", ""),
                    "result":        "W" if gf > ga else ("L" if gf < ga else "D"),
                    "goals_for":     gf,
                    "goals_against": ga,
                    "shots_on_goal": gf * 3.5,
                    "possession":    50.0,
                })
            except (ValueError, TypeError):
                continue

        return results

    def get_team_stats(self, team_id: str, league: str = "") -> list[dict]:
        """Public stats fetch — cascade."""
        if team_id and team_id.startswith("tsdb_"):
            return self.get_team_last_events_tsdb(team_id)
        return []

    def get_standings_form(self, team_id: str, league: str) -> dict | None:
        """Get team standings form from football-data.org."""
        comp_code = FD_COMPETITIONS.get(league)
        if comp_code and team_id and team_id.startswith("fd_"):
            return self.get_team_form_fd(team_id, comp_code)
        return None

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
        today = date.today().isoformat()

        try:
            if target <= today:
                url = f"{WEATHER_URL}/current.json"
                params = {"key": WEATHER_API_KEY, "q": city, "aqi": "no"}
            else:
                url = f"{WEATHER_URL}/forecast.json"
                params = {"key": WEATHER_API_KEY, "q": city, "dt": target, "aqi": "no"}

            r = self._s.get(url, params=params, timeout=10)
            if not r.ok:
                return base
            data = r.json()

            if target <= today:
                cur = data["current"]
                temp_c = cur["temp_c"]
                condition = cur["condition"]["text"]
                wind_kph = cur["wind_kph"]
                precip_mm = cur["precip_mm"]
                humidity = cur["humidity"]
            else:
                day = data["forecast"]["forecastday"][0]["day"]
                temp_c = day["avgtemp_c"]
                condition = day["condition"]["text"]
                wind_kph = day["maxwind_kph"]
                precip_mm = day["totalprecip_mm"]
                humidity = day["avghumidity"]

            penalty = 0.0
            notes = []
            cl = condition.lower()

            for bc in ["heavy rain", "torrential", "blizzard", "heavy snow", "thunderstorm", "sleet", "freezing"]:
                if bc in cl:
                    penalty += 0.08
                    notes.append("severe weather")
                    break
            else:
                if "rain" in cl or "drizzle" in cl:
                    penalty += 0.04
                    notes.append("light rain")
                elif "snow" in cl:
                    penalty += 0.06
                    notes.append("snow")

            if precip_mm > 15:
                penalty += 0.04
                notes.append("heavy precip")
            elif precip_mm > 5:
                penalty += 0.02
                notes.append("light precip")

            if wind_kph > 70:
                penalty += 0.04
                notes.append("strong wind")
            elif wind_kph > 50:
                penalty += 0.02
                notes.append("moderate wind")

            if temp_c < 0:
                penalty += 0.03
                notes.append("freezing")
            elif temp_c > 38:
                penalty += 0.02
                notes.append("extreme heat")

            penalty = min(penalty, 0.15)
            desc = (
                f"{'⚠️' if penalty > 0.06 else '🌧️'}  {condition} | "
                f"{', '.join(notes)} → xG -{penalty * 100:.0f}%"
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
    # PUBLIC — MAIN FETCH METHOD
    # ══════════════════════════════════════════════════════════════════════

    def get_matches_for_week(
        self,
        days_ahead: int = 7,
        competitions: list[str] | None = None,
    ) -> list[dict]:
        """
        Fetch all upcoming matches for the next `days_ahead` days.

        Cascade (v2.0):
        1. The Odds API /events  (World Cup priority + active leagues)
        2. football-data.org     (major leagues)
        3. ESPN public API       (no auth, good WC 2026 coverage)
        4. TheSportsDB           (fallback)
        5. Demo mode             (when between seasons / all sources dead)
        """
        today = date.today()
        end_date = today + timedelta(days=days_ahead)
        d_from = today.isoformat()
        d_to = end_date.isoformat()

        cache_key = f"week_{d_from}_{days_ahead}_{','.join(sorted(competitions or []))}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        matches: list[dict] = []
        seen_ids: set[str] = set()

        def _add(new_matches: list[dict]) -> None:
            for m in new_matches:
                fid = m.get("fixture_id", "")
                if fid and fid not in seen_ids:
                    seen_ids.add(fid)
                    matches.append(m)

        comps = competitions or list(ODDS_SPORT_KEYS.keys())

        # ── Source 1: The Odds API events (World Cup first!) ──────────────
        logger.info("Fetching from The Odds API events…")
        # Prioritise World Cup 2026
        priority_comps = ["World Cup 2026"] + [c for c in comps if c != "World Cup 2026"]
        for league in priority_comps:
            sk = ODDS_SPORT_KEYS.get(league)
            if sk:
                _add(self._fetch_events_odds_api(sk, days_ahead))
        logger.info("After Odds API events: %d matches", len(matches))

        # ── Source 2: football-data.org ───────────────────────────────────
        logger.info("Fetching from football-data.org…")
        fd_codes = [FD_COMPETITIONS[c] for c in comps if c in FD_COMPETITIONS] or None
        _add(self._fetch_matches_fd(d_from, d_to, fd_codes))
        logger.info("After FD.org: %d matches", len(matches))

        # ── Source 3: ESPN public API ─────────────────────────────────────
        logger.info("Fetching from ESPN…")
        for i in range(min(days_ahead, 7)):
            target = (today + timedelta(days=i)).isoformat()
            for league in comps:
                if ESPN_LEAGUE_SLUGS.get(league):
                    _add(self._fetch_matches_espn(league, target))
        logger.info("After ESPN: %d matches", len(matches))

        # ── Source 4: TheSportsDB ─────────────────────────────────────────
        if len(matches) < 5:
            logger.info("Fetching from TheSportsDB…")
            for league in comps:
                lid = TSDB_LEAGUE_IDS.get(league)
                if lid:
                    _add(self._fetch_matches_tsdb(lid, league))
            logger.info("After TSDB: %d matches", len(matches))

        # ── Source 5: Demo mode ───────────────────────────────────────────
        if len(matches) < 3:
            logger.info("Activating demo mode (all sources returned < 3 matches)…")
            _add(self._generate_demo_matches(comps))
            logger.info("After Demo: %d matches", len(matches))

        # ── Filter to date range ──────────────────────────────────────────
        matches = [
            m for m in matches
            if d_from <= m.get("kickoff_date", "9999") <= d_to
        ]

        # ── Attach odds ───────────────────────────────────────────────────
        matches = self._attach_odds(matches)

        # ── Sort by kickoff ───────────────────────────────────────────────
        matches.sort(key=lambda m: m.get("kickoff_utc", ""))

        logger.info("[Hybrid v2.0] Final match count: %d", len(matches))
        self._cset(cache_key, matches)
        return matches

    def get_matches_for_date(self, target_date: str) -> list[dict]:
        all_m = self.get_matches_for_week(days_ahead=7)
        return [m for m in all_m if m.get("kickoff_date") == target_date]

    def clear_cache(self) -> None:
        self._mem.clear()
        self._dead_keys.clear()
        logger.info("Cache and dead-keys cleared.")


# ─────────────────────────────────────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  FOOTBALL ORACLE v2.0 — World Cup Edition Smoke Test")
    print(f"  Date: {date.today()}")
    print("=" * 65)

    api = FootballOracleAPI()

    print("\n[1] Matches next 7 days (World Cup 2026 + MLS + SuperLiga)…")
    matches = api.get_matches_for_week(
        days_ahead=7,
        competitions=["World Cup 2026", "MLS", "Romania SuperLiga"],
    )
    print(f"    → {len(matches)} matches found")
    for m in matches[:10]:
        odds_str = (
            f"H={m['home_odds']:.2f} D={m['draw_odds']:.2f} A={m['away_odds']:.2f}"
            if m.get("home_odds") else "No odds"
        )
        print(f"    {m['kickoff_date']}  {m['home_team']:25} vs "
              f"{m['away_team']:25}  [{m['league']}]  {odds_str}  [{m['source']}]")

    print("\n[2] Weather — New York…")
    w = api.get_weather("New York")
    print(f"    → {w['description']}")

    print("\n" + "=" * 65 + "\n")
