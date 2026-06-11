"""
================================================================================
FOOTBALL ORACLE — Hybrid API Layer (No API-Football)
================================================================================
Module  : oracle_api.py
Strategy: Robust cascade WITHOUT API-Football (suspended/unreliable)

  MATCHES (cascade):
    1. The Odds API  → /sports/{key}/events  (meciuri + date, 0 credit cost)
    2. football-data.org → /matches          (meciuri ligi majore)
    3. TheSportsDB   → free, no key needed   (fallback general)
    4. SofaScore scraping                    (fallback final)

  ODDS (cascade):
    1. The Odds API  → /sports/{key}/odds    (cote reale, cache 4h)
    2. SofaScore / Betexplorer scraping      (fallback)

  STATS pentru xG (cascade):
    1. football-data.org → standings + form  (gratuit)
    2. TheSportsDB       → last events       (gratuit)
    3. Neutral league defaults               (last resort)

  WEATHER:
    WeatherAPI → penalizare xG reală

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
# CREDENTIALS  (API-Football REMOVED)
# ─────────────────────────────────────────────────────────────────────────────
ODDS_API_KEY      = "b0e2ab9bcda1d9f4c5ddfe1063c81cd7"
FOOTBALL_DATA_KEY = "3934542be32c47f88a194f9eec0f44a1"
WEATHER_API_KEY   = "48a5b54b8ced45cc924153231263005"

# ─────────────────────────────────────────────────────────────────────────────
# BASE URLs
# ─────────────────────────────────────────────────────────────────────────────
FOOTBALL_DATA_URL = "https://api.football-data.org/v4"
ODDS_API_URL      = "https://api.the-odds-api.com/v4"
THESPORTSDB_URL   = "https://www.thesportsdb.com/api/v1/json/3"  # free tier
WEATHER_URL       = "http://api.weatherapi.com/v1"

# ─────────────────────────────────────────────────────────────────────────────
# LEAGUE MAPPINGS
# ─────────────────────────────────────────────────────────────────────────────

# football-data.org competition codes (free plan supports these)
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

# The Odds API sport keys
ODDS_SPORT_KEYS: dict[str, str] = {
    "Premier League":    "soccer_epl",
    "La Liga":           "soccer_spain_la_liga",
    "Serie A":           "soccer_italy_serie_a",
    "Bundesliga":        "soccer_germany_bundesliga",
    "Ligue 1":           "soccer_france_ligue_one",
    "Champions League":  "soccer_uefa_champs_league",
    "Europa League":     "soccer_uefa_europa_league",
    "Romania SuperLiga": "soccer_romania_1_liga",
    "World Cup 2026":    "soccer_fifa_world_cup",
    "MLS":               "soccer_usa_mls",
    "Eredivisie":        "soccer_netherlands_eredivisie",
    "Primeira Liga":     "soccer_portugal_primeira_liga",
}

# TheSportsDB league IDs (free)
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

# League baseline xG (avg goals/team/game) — used when no stats available
LEAGUE_BASELINES: dict[str, float] = {
    "Premier League":    1.35,
    "La Liga":           1.20,
    "Serie A":           1.25,
    "Bundesliga":        1.40,
    "Ligue 1":           1.30,
    "Champions League":  1.20,
    "Europa League":     1.15,
    "Romania SuperLiga": 1.15,
    "World Cup 2026":    1.30,
    "default":           1.25,
}

DEFAULT_SEASON = 2026

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
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
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
# NORMALISED MATCH SCHEMA
# ─────────────────────────────────────────────────────────────────────────────
# {
#   fixture_id, home_team, away_team, home_team_id, away_team_id,
#   kickoff_utc, kickoff_date, league, season, venue_city, status,
#   home_odds, draw_odds, away_odds, odds_source, source
# }


class FootballOracleAPI:
    """
    Hybrid data layer — NO API-Football.
    Cascade: The Odds API → football-data.org → TheSportsDB → scraping.
    """

    def __init__(self) -> None:
        self._s   = _build_session()
        self._mem: dict[str, tuple[Any, datetime]] = {}
        self._ttl = 30   # cache TTL minutes
        logger.info("FootballOracleAPI (No-AF Hybrid) initialised.")

    # ══════════════════════════════════════════════════════════════════════
    # CACHE
    # ══════════════════════════════════════════════════════════════════════

    def _cget(self, key: str) -> Any | None:
        if key in self._mem:
            v, ts = self._mem[key]
            if (datetime.now(timezone.utc) - ts).total_seconds() < self._ttl * 60:
                logger.info("CACHE HIT: %s", key)
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
            if not r.ok:
                logger.warning("[HTTP] %s → %s", url[:60], r.status_code)
                return None
            return r.json()
        except Exception as exc:
            logger.error("[HTTP] %s → %s", url[:60], exc)
            return None

    def _scrape(self, url: str, delay: float = 1.5) -> str | None:
        if not BS4_AVAILABLE:
            return None
        time.sleep(delay + random.uniform(0, 0.6))
        try:
            r = self._s.get(url, headers={
                "User-Agent": _ua(),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Referer": "https://www.google.com/",
            }, timeout=15)
            return r.text if r.ok else None
        except Exception as exc:
            logger.error("[Scrape] %s → %s", url[:60], exc)
            return None

    # ══════════════════════════════════════════════════════════════════════
    # SOURCE 1 — The Odds API: events (meciuri, 0 credit cost)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_events_odds_api(
        self, sport_key: str, days_ahead: int = 7
    ) -> list[dict]:
        """
        Fetch upcoming events from The Odds API /events endpoint.
        This uses ZERO credits — credits only consumed when fetching odds.
        Returns normalised match dicts WITHOUT odds.
        """
        cache_key = f"events_{sport_key}_{days_ahead}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached

        now        = datetime.now(timezone.utc)
        commence_to = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")

        data = self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/events",
            params={
                "apiKey":        ODDS_API_KEY,
                "commenceTimeFrom": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "commenceTo":    commence_to,
            },
        )
        if not data or not isinstance(data, list):
            return []

        # Reverse-lookup league name from sport_key
        league_name = next(
            (lg for lg, sk in ODDS_SPORT_KEYS.items() if sk == sport_key),
            sport_key,
        )

        results: list[dict] = []
        for ev in data:
            try:
                ko     = ev.get("commence_time", "")
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
                    "source":       "the-odds-api-events",
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
    # SOURCE 2 — football-data.org: matches
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_fd(
        self, date_from: str, date_to: str,
        comp_codes: list[str] | None = None,
    ) -> list[dict]:
        """Fetch matches from football-data.org for a date range."""
        params: dict = {
            "dateFrom": date_from,
            "dateTo":   date_to,
            "status":   "SCHEDULED,TIMED,LIVE,IN_PLAY",
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
                ko          = m.get("utcDate", "")
                league_name = m.get("competition", {}).get("name", "Unknown")
                home_id     = str(m["homeTeam"].get("id", ""))
                away_id     = str(m["awayTeam"].get("id", ""))
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
    # SOURCE 3 — TheSportsDB: upcoming events (free, no key)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_tsdb(self, league_id: str, league_name: str) -> list[dict]:
        """
        Fetch next 15 events from TheSportsDB for a league.
        Free endpoint, no API key needed.
        """
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
                ko_utc  = f"{ev_date}T{ev_time[:8]}Z" if ev_date else ""

                # Only include future/today matches
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
    # SOURCE 4 — SofaScore scraping fallback
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_sofascore(self, target_date: str) -> list[dict]:
        """
        Scrape SofaScore scheduled matches for a given date.
        Uses their public API endpoint (JSON, no auth needed).
        """
        url  = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{target_date}"
        data = self._get(url, headers={
            "User-Agent":  _ua(),
            "Referer":     "https://www.sofascore.com/",
            "Accept":      "application/json",
            "Cache-Control": "no-cache",
        })
        if not data:
            return []

        events  = data.get("events", [])
        results: list[dict] = []

        for ev in events:
            try:
                home = ev["homeTeam"]["name"]
                away = ev["awayTeam"]["name"]
                ts   = ev.get("startTimestamp", 0)
                if ts:
                    ko_dt   = datetime.fromtimestamp(ts, tz=timezone.utc)
                    ko_utc  = ko_dt.isoformat()
                    ko_date = ko_dt.date().isoformat()
                else:
                    ko_utc  = target_date + "T00:00:00Z"
                    ko_date = target_date

                league_name = ev.get("tournament", {}).get("name", "Unknown")
                category    = ev.get("tournament", {}).get("category", {}).get("name", "")

                results.append({
                    "fixture_id":   f"sofa_{ev['id']}",
                    "home_team":    home,
                    "away_team":    away,
                    "home_team_id": f"sofa_{ev['homeTeam']['id']}",
                    "away_team_id": f"sofa_{ev['awayTeam']['id']}",
                    "kickoff_utc":  ko_utc,
                    "kickoff_date": ko_date,
                    "league":       league_name,
                    "season":       DEFAULT_SEASON,
                    "venue_city":   category,
                    "status":       "scheduled",
                    "home_odds":    None,
                    "draw_odds":    None,
                    "away_odds":    None,
                    "odds_source":  None,
                    "source":       "sofascore",
                })
            except (KeyError, TypeError):
                continue

        logger.info("[SofaScore] %d events for %s.", len(results), target_date)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # ODDS — The Odds API (conserving credits with cache)
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_odds(self, sport_key: str) -> dict[str, dict]:
        """
        Fetch 1X2 odds for a league. Cache 4 hours to conserve 500 credits/month.
        Returns dict: "Home vs Away" → {home, draw, away, bookmaker}
        """
        cache_key = f"odds_{sport_key}"
        cached    = self._cget(cache_key)
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
        if not data or not isinstance(data, list):
            return {}

        result: dict[str, dict] = {}
        for ev in data:
            home     = ev.get("home_team", "")
            away     = ev.get("away_team", "")
            ev_id    = ev.get("id", "")
            best_h = best_d = best_a = 0.0
            bk_name  = ""

            for bk in ev.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt.get("key") != "h2h":
                        continue
                    om: dict[str, float] = {}
                    for o in mkt.get("outcomes", []):
                        om[o["name"]] = float(o.get("price", 0))
                    h = om.get(home, 0.0)
                    d = om.get("Draw", 0.0)
                    a = om.get(away,  0.0)
                    if h > best_h:
                        best_h  = h
                        bk_name = bk.get("title", "")
                    if d > best_d: best_d = d
                    if a > best_a: best_a = a

            if best_h > 1.0:
                # Index by multiple keys for fuzzy matching
                result[f"{home} vs {away}"]  = {"home":best_h,"draw":best_d,"away":best_a,"bookmaker":bk_name,"ev_id":ev_id}
                result[ev_id]                = result[f"{home} vs {away}"]

        # Cache with 4h TTL override
        self._mem[cache_key] = (result, datetime.now(timezone.utc))
        self._ttl = 240   # 4h for odds
        logger.info("[OddsAPI-Odds] %d events with odds for %s.", len(result)//2, sport_key)
        self._ttl = 30    # reset TTL for other calls
        return result

    def _attach_odds(self, matches: list[dict]) -> list[dict]:
        """
        Attach odds to each match from The Odds API.
        Groups by league to minimise API calls (1 call per league).
        """
        league_odds: dict[str, dict] = {}

        for m in matches:
            if m.get("home_odds"):
                continue

            league    = m.get("league", "")
            sport_key = ODDS_SPORT_KEYS.get(league)

            # Try to match via stored odds_api event ID first
            ev_id = m.get("_odds_api_id", "")

            if sport_key:
                if sport_key not in league_odds:
                    league_odds[sport_key] = self._fetch_odds(sport_key)
                od = league_odds[sport_key]

                # Lookup by event ID
                odds = od.get(ev_id)

                # Lookup by exact name
                if not odds:
                    odds = od.get(f"{m['home_team']} vs {m['away_team']}")

                # Fuzzy lookup
                if not odds:
                    hn = m["home_team"].lower()
                    an = m["away_team"].lower()
                    for k, v in od.items():
                        kl = k.lower()
                        if hn[:7] in kl and an[:7] in kl:
                            odds = v
                            break

                if odds:
                    m["home_odds"]   = odds["home"]
                    m["draw_odds"]   = odds["draw"]
                    m["away_odds"]   = odds["away"]
                    m["odds_source"] = f"The Odds API ({odds['bookmaker']})"

        return matches

    # ══════════════════════════════════════════════════════════════════════
    # STATS — football-data.org standings (for xG calculation)
    # ══════════════════════════════════════════════════════════════════════

    def get_team_form_fd(self, team_id: str, comp_code: str) -> dict | None:
        """Team form/stats from fd.org standings. team_id = "fd_123"."""
        tid = team_id.replace("fd_", "").replace("tsdb_", "").replace("sofa_", "")
        if not tid.isdigit():
            return None

        cache_key = f"standings_{comp_code}"
        cached    = self._cget(cache_key)
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
        """
        Fetch last 5 events for a team from TheSportsDB.
        Returns simplified stat dicts for xG calculation.
        """
        tid = team_id.replace("tsdb_", "")
        if not tid.isdigit():
            return []

        data = self._get(
            f"{THESPORTSDB_URL}/eventslast.php",
            params={"id": tid},
        )
        if not data:
            return []

        events  = data.get("results") or []
        results: list[dict] = []

        for ev in events:
            try:
                home_score = int(ev.get("intHomeScore") or 0)
                away_score = int(ev.get("intAwayScore") or 0)
                is_home    = ev.get("idHomeTeam") == tid
                gf = home_score if is_home else away_score
                ga = away_score if is_home else home_score
                results.append({
                    "date":          ev.get("dateEvent", ""),
                    "result":        "W" if gf > ga else ("L" if gf < ga else "D"),
                    "goals_for":     gf,
                    "goals_against": ga,
                    "shots_on_goal": gf * 3.5,   # estimate: 3.5 shots per goal
                    "possession":    50.0,         # not available via TSDB free
                })
            except (ValueError, TypeError):
                continue

        return results

    def get_team_stats(self, team_id: str, league: str = "") -> list[dict]:
        """
        Public method — cascade stats fetch.
        1. TheSportsDB last events (if tsdb_ ID)
        2. Empty list → engine uses standings form
        """
        if team_id.startswith("tsdb_"):
            return self.get_team_last_events_tsdb(team_id)
        # sofascore / odds IDs — no stats endpoint available without auth
        return []

    def get_standings_form(self, team_id: str, league: str) -> dict | None:
        """Get team standings form from football-data.org."""
        comp_code = FD_COMPETITIONS.get(league)
        if comp_code and team_id.startswith("fd_"):
            return self.get_team_form_fd(team_id, comp_code)
        return None

    # ══════════════════════════════════════════════════════════════════════
    # WEATHER (real xG penalty)
    # ══════════════════════════════════════════════════════════════════════

    def get_weather(self, city: str, match_date: str | None = None) -> dict:
        base = {
            "temp_c": 15.0, "condition": "Clear", "wind_kph": 10.0,
            "precip_mm": 0.0, "humidity": 50,
            "xg_penalty": 0.0,
            "description": "☀️  Clear conditions — no xG penalty.",
        }
        if not city or city == "Unknown":
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

            for bc in ["heavy rain","torrential","blizzard","heavy snow","thunderstorm","sleet","freezing"]:
                if bc in cl:
                    penalty += 0.08; notes.append("severe weather"); break
            else:
                if "rain" in cl or "drizzle" in cl:
                    penalty += 0.04; notes.append("light rain")
                elif "snow" in cl:
                    penalty += 0.06; notes.append("snow")

            if precip_mm > 15:  penalty += 0.04; notes.append(f"heavy precip")
            elif precip_mm > 5: penalty += 0.02; notes.append(f"light precip")

            if wind_kph > 70:   penalty += 0.04; notes.append(f"strong wind")
            elif wind_kph > 50: penalty += 0.02; notes.append(f"moderate wind")

            if temp_c < 0:      penalty += 0.03; notes.append(f"freezing")
            elif temp_c > 38:   penalty += 0.02; notes.append(f"extreme heat")

            penalty = min(penalty, 0.15)
            desc    = (
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
    # PUBLIC — MAIN FETCH METHOD
    # ══════════════════════════════════════════════════════════════════════

    def get_matches_for_week(
        self,
        days_ahead:   int = 7,
        competitions: list[str] | None = None,
    ) -> list[dict]:
        """
        Fetch all upcoming matches for the next `days_ahead` days.

        Cascade:
        1. The Odds API /events (0 credits, best coverage)
        2. football-data.org  (ligi majore)
        3. TheSportsDB        (ligi cu TSDB ID)
        4. SofaScore scraping (fallback global)

        Then enriches all matches with odds from The Odds API.
        """
        today    = date.today()
        end_date = today + timedelta(days=days_ahead)
        d_from   = today.isoformat()
        d_to     = end_date.isoformat()

        cache_key = f"week_{d_from}_{days_ahead}_{','.join(sorted(competitions or []))}"
        cached    = self._cget(cache_key)
        if cached is not None:
            return cached

        matches:    list[dict] = []
        seen_ids:   set[str]  = set()

        def _add(new_matches: list[dict]) -> None:
            for m in new_matches:
                fid = m.get("fixture_id", "")
                if fid and fid not in seen_ids:
                    seen_ids.add(fid)
                    matches.append(m)

        comps = competitions or list(ODDS_SPORT_KEYS.keys())

        # ── Source 1: The Odds API events (free, no credits) ─────────────
        logger.info("Fetching from The Odds API events…")
        for league in comps:
            sk = ODDS_SPORT_KEYS.get(league)
            if sk:
                _add(self._fetch_events_odds_api(sk, days_ahead))

        logger.info("After Odds API events: %d matches", len(matches))

        # ── Source 2: football-data.org ───────────────────────────────────
        logger.info("Fetching from football-data.org…")
        fd_codes = [
            FD_COMPETITIONS[c] for c in comps if c in FD_COMPETITIONS
        ] or None
        _add(self._fetch_matches_fd(d_from, d_to, fd_codes))
        logger.info("After FD.org: %d matches", len(matches))

        # ── Source 3: TheSportsDB ─────────────────────────────────────────
        if len(matches) < 10:
            logger.info("Fetching from TheSportsDB…")
            for league in comps:
                lid = TSDB_LEAGUE_IDS.get(league)
                if lid:
                    _add(self._fetch_matches_tsdb(lid, league))
            logger.info("After TSDB: %d matches", len(matches))

        # ── Source 4: SofaScore scraping ──────────────────────────────────
        if len(matches) < 5:
            logger.info("Falling back to SofaScore scraping…")
            for i in range(min(days_ahead, 4)):
                d = (today + timedelta(days=i)).isoformat()
                _add(self._fetch_matches_sofascore(d))
            logger.info("After SofaScore: %d matches", len(matches))

        # ── Filter to date range ──────────────────────────────────────────
        matches = [
            m for m in matches
            if d_from <= m.get("kickoff_date", "9999") <= d_to
        ]

        # ── Attach odds ───────────────────────────────────────────────────
        matches = self._attach_odds(matches)

        # ── Sort by kickoff ───────────────────────────────────────────────
        matches.sort(key=lambda m: m.get("kickoff_utc", ""))

        logger.info("[Hybrid] Final match count: %d", len(matches))
        self._cset(cache_key, matches)
        return matches

    def get_matches_for_date(self, target_date: str) -> list[dict]:
        all_m = self.get_matches_for_week(days_ahead=7)
        return [m for m in all_m if m.get("kickoff_date") == target_date]

    def clear_cache(self) -> None:
        self._mem.clear()
        logger.info("Cache cleared.")


# ─────────────────────────────────────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  FOOTBALL ORACLE — No-AF Hybrid API Smoke Test")
    print("=" * 65)

    api = FootballOracleAPI()

    print("\n[1] Matches next 7 days (Premier League + Serie A)…")
    matches = api.get_matches_for_week(
        days_ahead=7,
        competitions=["Premier League", "Serie A", "Champions League"],
    )
    print(f"    → {len(matches)} matches found")
    for m in matches[:8]:
        odds_str = (
            f"H={m['home_odds']:.2f} D={m['draw_odds']:.2f} A={m['away_odds']:.2f}"
            if m.get("home_odds") else "No odds yet"
        )
        print(f"    {m['kickoff_date']}  {m['home_team']:25} vs {m['away_team']:25}"
              f"  [{m['league']}]  {odds_str}  [{m['source']}]")

    print("\n[2] Weather — Bucharest…")
    w = api.get_weather("Bucharest")
    print(f"    → {w['description']}")

    print("\n" + "=" * 65 + "\n")
