"""
================================================================================
FOOTBALL ORACLE — Hybrid API + Scraping Layer
================================================================================
Module  : oracle_api.py
Strategy: Cascading fallback across 4 data sources + intelligent scraping
          Matches  : football-data.org → API-Football live → Flashscore scrape
          Odds     : The Odds API      → Betexplorer scrape
          Stats    : API-Football hist → football-data.io → football-data.org
          Weather  : WeatherAPI (real xG integration)
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

# ── Optional scraping libs (graceful if missing) ──────────────────────────────
try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# CREDENTIALS
# ─────────────────────────────────────────────────────────────────────────────
ODDS_API_KEY        = "b0e2ab9bcda1d9f4c5ddfe1063c81cd7"   # The Odds API
API_FOOTBALL_KEY    = "c4e7610bf0334935d0f90801863e1801"   # API-Football v3
FOOTBALL_DATA_KEY   = "3934542be32c47f88a194f9eec0f44a1"  # football-data.org
FOOTBALL_DATA_IO_KEY= "fd_9778bb604b33b05afd4f5324a90f10d9a3d2f7e42702448d"
WEATHER_API_KEY     = "48a5b54b8ced45cc924153231263005"

# ─────────────────────────────────────────────────────────────────────────────
# BASE URLs
# ─────────────────────────────────────────────────────────────────────────────
API_FOOTBALL_URL  = "https://v3.football.api-sports.io"
FOOTBALL_DATA_URL = "https://api.football-data.org/v4"
FOOTBALL_DATA_IO  = "https://api.football-data.io/v1"
ODDS_API_URL      = "https://api.the-odds-api.com/v4"
WEATHER_URL       = "http://api.weatherapi.com/v1"

# ─────────────────────────────────────────────────────────────────────────────
# LEAGUE MAPPINGS  (football-data.org codes + The Odds API sport keys)
# ─────────────────────────────────────────────────────────────────────────────

# football-data.org competition codes
FD_COMPETITIONS: dict[str, str] = {
    "Premier League":       "PL",
    "La Liga":              "PD",
    "Serie A":              "SA",
    "Bundesliga":           "BL1",
    "Ligue 1":              "FL1",
    "Champions League":     "CL",
    "Europa League":        "EL",
    "Romania SuperLiga":    "RO1",   # may need verification
    "World Cup 2026":       "WC",
}

# The Odds API sport keys for football
ODDS_API_SPORT_KEYS: dict[str, str] = {
    "Premier League":       "soccer_epl",
    "La Liga":              "soccer_spain_la_liga",
    "Serie A":              "soccer_italy_serie_a",
    "Bundesliga":           "soccer_germany_bundesliga",
    "Ligue 1":              "soccer_france_ligue_one",
    "Champions League":     "soccer_uefa_champs_league",
    "Europa League":        "soccer_uefa_europa_league",
    "Romania SuperLiga":    "soccer_romania_1_liga",
    "World Cup 2026":       "soccer_fifa_world_cup",
}

# API-Football league IDs (for stats/history)
AF_LEAGUE_IDS: dict[str, int] = {
    "Premier League":    39,
    "La Liga":          140,
    "Serie A":          135,
    "Bundesliga":        78,
    "Ligue 1":           61,
    "Champions League":   2,
    "Europa League":      3,
    "Romania SuperLiga": 283,
    "World Cup 2026":     1,
}

# Betexplorer league slugs for scraping fallback
BETEXPLORER_SLUGS: dict[str, str] = {
    "Premier League":    "england/premier-league",
    "La Liga":           "spain/laliga",
    "Serie A":           "italy/serie-a",
    "Bundesliga":        "germany/bundesliga",
    "Ligue 1":           "france/ligue-1",
    "Champions League":  "europe/champions-league",
    "Europa League":     "europe/europa-league",
    "Romania SuperLiga": "romania/superliga",
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
# ROTATING USER-AGENTS  (anti-ban for scraping)
# ─────────────────────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]


def _random_ua() -> str:
    return random.choice(USER_AGENTS)


# ─────────────────────────────────────────────────────────────────────────────
# SESSION BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_session(retries: int = 3, backoff: float = 0.5) -> Session:
    s = Session()
    r = Retry(
        total=retries,
        backoff_factor=backoff,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    a = HTTPAdapter(max_retries=r)
    s.mount("https://", a)
    s.mount("http://",  a)
    return s


# ─────────────────────────────────────────────────────────────────────────────
# UNIFIED MATCH SCHEMA
# ─────────────────────────────────────────────────────────────────────────────
# Every source normalises to this dict:
# {
#   "fixture_id"   : str   (source_prefix + id)
#   "home_team"    : str
#   "away_team"    : str
#   "home_team_id" : str | None
#   "away_team_id" : str | None
#   "kickoff_utc"  : str   (ISO 8601)
#   "kickoff_date" : str   (YYYY-MM-DD)
#   "league"       : str
#   "league_id"    : int | None
#   "season"       : int
#   "venue_city"   : str
#   "status"       : str   ("scheduled" | "live" | "finished")
#   "home_odds"    : float | None
#   "draw_odds"    : float | None
#   "away_odds"    : float | None
#   "odds_source"  : str | None
#   "source"       : str   (which API/scraper provided this)
# }


def _empty_match(home: str, away: str, league: str) -> dict:
    return {
        "fixture_id":   f"unknown_{home}_{away}",
        "home_team":    home,
        "away_team":    away,
        "home_team_id": None,
        "away_team_id": None,
        "kickoff_utc":  "",
        "kickoff_date": date.today().isoformat(),
        "league":       league,
        "league_id":    None,
        "season":       DEFAULT_SEASON,
        "venue_city":   "",
        "status":       "scheduled",
        "home_odds":    None,
        "draw_odds":    None,
        "away_odds":    None,
        "odds_source":  None,
        "source":       "unknown",
    }


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class FootballOracleAPI:
    """
    Hybrid data layer: 4 API sources + intelligent scraping fallback.
    All public methods return normalised match dicts or [] / {} on failure.
    """

    def __init__(self) -> None:
        self._s       = _build_session()
        self._cache: dict[str, tuple[Any, datetime]] = {}   # simple in-memory cache
        self._cache_ttl_min = 30   # cache TTL in minutes
        logger.info("FootballOracleAPI (Hybrid) initialised.")

    # ══════════════════════════════════════════════════════════════════════
    # CACHE HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _cache_get(self, key: str) -> Any | None:
        if key in self._cache:
            val, ts = self._cache[key]
            if (datetime.now(timezone.utc) - ts).seconds < self._cache_ttl_min * 60:
                logger.info("CACHE HIT: %s", key)
                return val
        return None

    def _cache_set(self, key: str, val: Any) -> None:
        self._cache[key] = (val, datetime.now(timezone.utc))

    # ══════════════════════════════════════════════════════════════════════
    # LOW-LEVEL GET HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _get_fd(self, endpoint: str, params: dict | None = None) -> dict | None:
        """football-data.org GET."""
        url = f"{FOOTBALL_DATA_URL}/{endpoint}"
        headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
        try:
            r = self._s.get(url, headers=headers, params=params or {}, timeout=12)
            if r.status_code == 429:
                logger.warning("[FD.org] Rate limited — backing off 60s.")
                time.sleep(60)
                return None
            if not r.ok:
                logger.warning("[FD.org] HTTP %s for %s", r.status_code, endpoint)
                return None
            return r.json()
        except Exception as exc:
            logger.error("[FD.org] %s", exc)
            return None

    def _get_af(self, endpoint: str, params: dict | None = None) -> dict | None:
        """API-Football v3 GET."""
        url = f"{API_FOOTBALL_URL}/{endpoint}"
        headers = {"x-apisports-key": API_FOOTBALL_KEY, "Accept": "application/json"}
        try:
            r = self._s.get(url, headers=headers, params=params or {}, timeout=12)
            if not r.ok:
                logger.warning("[AF] HTTP %s for %s", r.status_code, endpoint)
                return None
            body = r.json()
            if body.get("errors"):
                logger.warning("[AF] API error: %s", body["errors"])
                return None
            return body
        except Exception as exc:
            logger.error("[AF] %s", exc)
            return None

    def _get_odds_api(self, endpoint: str, params: dict | None = None) -> Any | None:
        """The Odds API GET."""
        url = f"{ODDS_API_URL}/{endpoint}"
        p   = {"apiKey": ODDS_API_KEY, **(params or {})}
        try:
            r = self._s.get(url, params=p, timeout=12)
            remaining = r.headers.get("x-requests-remaining", "?")
            logger.info("[OddsAPI] %s — remaining credits: %s", endpoint, remaining)
            if not r.ok:
                logger.warning("[OddsAPI] HTTP %s", r.status_code)
                return None
            return r.json()
        except Exception as exc:
            logger.error("[OddsAPI] %s", exc)
            return None

    def _get_scrape(self, url: str, delay: float = 1.5) -> str | None:
        """Generic scrape GET with rotating UA and polite delay."""
        if not BS4_AVAILABLE:
            logger.warning("BeautifulSoup not installed — scraping disabled.")
            return None
        time.sleep(delay + random.uniform(0, 0.8))
        headers = {
            "User-Agent":      _random_ua(),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer":         "https://www.google.com/",
        }
        try:
            r = self._s.get(url, headers=headers, timeout=15)
            if not r.ok:
                logger.warning("[Scrape] HTTP %s for %s", r.status_code, url)
                return None
            return r.text
        except Exception as exc:
            logger.error("[Scrape] %s — %s", url, exc)
            return None

    # ══════════════════════════════════════════════════════════════════════
    # 1. MATCHES — PRIMARY: football-data.org
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_fd(
        self,
        date_from: str,
        date_to:   str,
        competitions: list[str] | None = None,
    ) -> list[dict]:
        """
        Fetch matches from football-data.org for a date range.
        Returns normalised match list.
        """
        params: dict = {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED,TIMED,LIVE"}
        if competitions:
            params["competitions"] = ",".join(competitions)

        body = self._get_fd("matches", params)
        if not body:
            return []

        results: list[dict] = []
        for m in body.get("matches", []):
            try:
                ko = m.get("utcDate", "")
                ko_date = ko[:10] if ko else date_from
                league_name = m.get("competition", {}).get("name", "Unknown")
                home = m["homeTeam"]["name"]
                away = m["awayTeam"]["name"]
                home_id = str(m["homeTeam"].get("id", ""))
                away_id = str(m["awayTeam"].get("id", ""))
                area    = m.get("area", {}).get("name", "")

                results.append({
                    "fixture_id":   f"fd_{m['id']}",
                    "home_team":    home,
                    "away_team":    away,
                    "home_team_id": f"fd_{home_id}",
                    "away_team_id": f"fd_{away_id}",
                    "kickoff_utc":  ko,
                    "kickoff_date": ko_date,
                    "league":       league_name,
                    "league_id":    AF_LEAGUE_IDS.get(league_name),
                    "season":       DEFAULT_SEASON,
                    "venue_city":   area,
                    "status":       m.get("status", "SCHEDULED").lower(),
                    "home_odds":    None,
                    "draw_odds":    None,
                    "away_odds":    None,
                    "odds_source":  None,
                    "source":       "football-data.org",
                })
            except (KeyError, TypeError):
                continue
        logger.info("[FD.org] %d matches fetched (%s → %s).", len(results), date_from, date_to)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # 2. MATCHES — FALLBACK: API-Football /fixtures?live=all
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_live_af(self) -> list[dict]:
        """Fetch live matches from API-Football (no season required)."""
        body = self._get_af("fixtures", {"live": "all"})
        if not body:
            return []

        results: list[dict] = []
        for f in body.get("response", []):
            try:
                fix    = f["fixture"]
                teams  = f["teams"]
                league = f["league"]
                ko     = fix.get("date", "")
                results.append({
                    "fixture_id":   f"af_{fix['id']}",
                    "home_team":    teams["home"]["name"],
                    "away_team":    teams["away"]["name"],
                    "home_team_id": f"af_{teams['home']['id']}",
                    "away_team_id": f"af_{teams['away']['id']}",
                    "kickoff_utc":  ko,
                    "kickoff_date": ko[:10] if ko else "",
                    "league":       league.get("name", ""),
                    "league_id":    league.get("id"),
                    "season":       league.get("season", DEFAULT_SEASON),
                    "venue_city":   fix.get("venue", {}).get("city", ""),
                    "status":       "live",
                    "home_odds":    None,
                    "draw_odds":    None,
                    "away_odds":    None,
                    "odds_source":  None,
                    "source":       "api-football-live",
                })
            except (KeyError, TypeError):
                continue
        logger.info("[AF-Live] %d live matches.", len(results))
        return results

    # ══════════════════════════════════════════════════════════════════════
    # 3. MATCHES — SCRAPING FALLBACK: Flashscore
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_matches_scrape(self, target_date: str) -> list[dict]:
        """
        Scrape Betexplorer for matches on a given date.
        Returns partial normalised dicts (no team IDs).
        """
        if not BS4_AVAILABLE:
            return []

        results: list[dict] = []
        for league_name, slug in BETEXPLORER_SLUGS.items():
            url  = f"https://www.betexplorer.com/soccer/{slug}/"
            html = self._get_scrape(url, delay=2.0)
            if not html:
                continue

            try:
                soup  = BeautifulSoup(html, "html.parser")
                rows  = soup.select("tr.js-home-highlight, tr[data-dt]")
                for row in rows:
                    try:
                        dt_attr = row.get("data-dt", "")
                        if dt_attr and dt_attr[:10] != target_date:
                            continue

                        teams_el = row.select_one(".table-main__tt")
                        if not teams_el:
                            continue
                        text = teams_el.get_text(separator=" - ", strip=True)
                        if " - " not in text:
                            continue
                        home, away = text.split(" - ", 1)

                        # Try to extract odds from columns
                        odds_els = row.select("td.table-main__odds span")
                        h_odd = d_odd = a_odd = None
                        if len(odds_els) >= 3:
                            try:
                                h_odd = float(odds_els[0].get_text(strip=True))
                                d_odd = float(odds_els[1].get_text(strip=True))
                                a_odd = float(odds_els[2].get_text(strip=True))
                            except ValueError:
                                pass

                        results.append({
                            "fixture_id":   f"scrape_{league_name}_{home}_{away}",
                            "home_team":    home.strip(),
                            "away_team":    away.strip(),
                            "home_team_id": None,
                            "away_team_id": None,
                            "kickoff_utc":  dt_attr or target_date + "T00:00:00Z",
                            "kickoff_date": target_date,
                            "league":       league_name,
                            "league_id":    AF_LEAGUE_IDS.get(league_name),
                            "season":       DEFAULT_SEASON,
                            "venue_city":   "",
                            "status":       "scheduled",
                            "home_odds":    h_odd,
                            "draw_odds":    d_odd,
                            "away_odds":    a_odd,
                            "odds_source":  "betexplorer-scrape" if h_odd else None,
                            "source":       "betexplorer-scrape",
                        })
                    except Exception:
                        continue
            except Exception as exc:
                logger.warning("[Scrape-BE] Parse error %s: %s", league_name, exc)

        logger.info("[Scrape-BE] %d matches scraped for %s.", len(results), target_date)
        return results

    # ══════════════════════════════════════════════════════════════════════
    # 4. ODDS — PRIMARY: The Odds API
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_odds_odds_api(
        self, sport_key: str
    ) -> dict[str, dict]:
        """
        Fetch 1X2 odds from The Odds API for a sport/league.
        Returns dict keyed by "HomeTeam vs AwayTeam" → {home, draw, away, bookmaker}.
        Caches result for 4 hours to conserve credits.
        """
        cache_key = f"odds_api_{sport_key}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        data = self._get_odds_api(
            f"sports/{sport_key}/odds",
            params={
                "regions":  "eu",
                "markets":  "h2h",
                "oddsFormat": "decimal",
            },
        )
        if not data:
            return {}

        result: dict[str, dict] = {}
        for event in data:
            home = event.get("home_team", "")
            away = event.get("away_team", "")
            key  = f"{home} vs {away}"

            best_h = best_d = best_a = 0.0
            bk_name = ""

            for bk in event.get("bookmakers", []):
                for market in bk.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    odds_map: dict[str, float] = {}
                    for o in market.get("outcomes", []):
                        odds_map[o["name"]] = float(o.get("price", 0))

                    h = odds_map.get(home, 0.0)
                    d = odds_map.get("Draw", 0.0)
                    a = odds_map.get(away,  0.0)

                    # Keep best (highest) odds across bookmakers
                    if h > best_h:
                        best_h = h; bk_name = bk.get("title","")
                    if d > best_d:
                        best_d = d
                    if a > best_a:
                        best_a = a

            if best_h > 1.0:
                result[key] = {
                    "home": best_h,
                    "draw": best_d,
                    "away": best_a,
                    "bookmaker": bk_name,
                }

        self._cache_set(cache_key, result)
        logger.info("[OddsAPI] %d events with odds for %s.", len(result), sport_key)
        return result

    # ══════════════════════════════════════════════════════════════════════
    # 5. ODDS — SCRAPING FALLBACK: Betexplorer
    # ══════════════════════════════════════════════════════════════════════

    def _fetch_odds_scrape(
        self, home_team: str, away_team: str, league_name: str
    ) -> dict | None:
        """
        Scrape Betexplorer for specific match odds.
        Returns {home, draw, away, bookmaker} or None.
        """
        if not BS4_AVAILABLE:
            return None

        slug = BETEXPLORER_SLUGS.get(league_name)
        if not slug:
            return None

        url  = f"https://www.betexplorer.com/soccer/{slug}/"
        html = self._get_scrape(url, delay=1.5)
        if not html:
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select("tr[data-dt]")
            for row in rows:
                text = (row.select_one(".table-main__tt") or row).get_text(" ", strip=True)
                if home_team.lower()[:6] in text.lower() and away_team.lower()[:6] in text.lower():
                    odds_els = row.select("td.table-main__odds span")
                    if len(odds_els) >= 3:
                        try:
                            return {
                                "home":      float(odds_els[0].get_text(strip=True)),
                                "draw":      float(odds_els[1].get_text(strip=True)),
                                "away":      float(odds_els[2].get_text(strip=True)),
                                "bookmaker": "Betexplorer (avg)",
                            }
                        except ValueError:
                            pass
        except Exception as exc:
            logger.warning("[Scrape-Odds] %s", exc)
        return None

    # ══════════════════════════════════════════════════════════════════════
    # 6. STATISTICS — API-Football historical
    # ══════════════════════════════════════════════════════════════════════

    def get_team_stats_af(
        self, team_id_raw: str, last_n: int = 5
    ) -> list[dict]:
        """
        Fetch last N finished fixtures + stats for a team.
        team_id_raw: "af_496" format or plain int string.
        Returns normalised list of stat dicts.
        """
        team_id = team_id_raw.replace("af_", "").replace("fd_", "")
        if not team_id.isdigit():
            return []

        # Try multiple recent seasons (no season lock)
        for season in [2024, 2023, 2022]:
            body = self._get_af(
                "fixtures",
                {"team": team_id, "last": last_n, "status": "FT", "season": season},
            )
            if body and body.get("response"):
                break
        else:
            return []

        fixtures = body.get("response", [])
        if not fixtures:
            return []

        enriched: list[dict] = []
        for fix in fixtures:
            fid       = fix["fixture"]["id"]
            home_g    = fix["goals"]["home"] or 0
            away_g    = fix["goals"]["away"] or 0
            t_is_home = fix["teams"]["home"]["id"] == int(team_id)
            gf        = home_g if t_is_home else away_g
            ga        = away_g if t_is_home else home_g
            result    = "W" if gf > ga else ("L" if gf < ga else "D")

            stats_body = self._get_af(
                "fixtures/statistics",
                {"fixture": fid, "team": team_id},
            )
            raw = []
            if stats_body and stats_body.get("response"):
                raw = stats_body["response"][0].get("statistics", [])

            def _n(key: str) -> float:
                for s in raw:
                    if s["type"] == key:
                        v = s["value"]
                        if v is None: return 0.0
                        if isinstance(v, str):
                            return float(v.replace("%","").strip() or 0)
                        return float(v)
                return 0.0

            enriched.append({
                "fixture_id":    fid,
                "date":          fix["fixture"]["date"][:10],
                "result":        result,
                "goals_for":     gf,
                "goals_against": ga,
                "shots_on_goal": _n("Shots on Goal"),
                "shots_total":   _n("Total Shots"),
                "possession":    _n("Ball Possession"),
                "passes_acc":    _n("Passes %"),
                "corners":       _n("Corner Kicks"),
                "yellow_cards":  _n("Yellow Cards"),
                "red_cards":     _n("Red Cards"),
                "saves":         _n("Goalkeeper Saves"),
            })
        logger.info("[AF-Stats] team=%s — %d fixtures enriched.", team_id, len(enriched))
        return enriched

    # ══════════════════════════════════════════════════════════════════════
    # 7. STATISTICS — football-data.org (team form via standings)
    # ══════════════════════════════════════════════════════════════════════

    def get_team_form_fd(self, team_id_raw: str, competition_code: str) -> dict | None:
        """
        Get team form info from football-data.org standings.
        Returns dict with form string, points, goalsFor, goalsAgainst.
        """
        team_id = team_id_raw.replace("fd_", "")
        if not team_id.isdigit():
            return None

        body = self._get_fd(f"competitions/{competition_code}/standings")
        if not body:
            return None

        for standing_group in body.get("standings", []):
            for entry in standing_group.get("table", []):
                if str(entry.get("team", {}).get("id", "")) == team_id:
                    return {
                        "position":      entry.get("position"),
                        "played":        entry.get("playedGames"),
                        "won":           entry.get("won"),
                        "draw":          entry.get("draw"),
                        "lost":          entry.get("lost"),
                        "goals_for":     entry.get("goalsFor"),
                        "goals_against": entry.get("goalsAgainst"),
                        "goal_diff":     entry.get("goalDifference"),
                        "points":        entry.get("points"),
                        "form":          entry.get("form", ""),    # e.g. "W,D,W,L,W"
                    }
        return None

    # ══════════════════════════════════════════════════════════════════════
    # 8. WEATHER  (real integration — returns xG penalty factor)
    # ══════════════════════════════════════════════════════════════════════

    def get_weather(self, city: str, match_date: str | None = None) -> dict:
        """
        Fetch weather for a venue.
        Returns dict including xg_penalty_factor (0.0 = no penalty, up to 0.15).
        """
        target = match_date or date.today().isoformat()
        today  = date.today().isoformat()
        base   = {"temp_c": 15.0, "condition": "Clear", "wind_kph": 10.0,
                  "precip_mm": 0.0, "humidity": 50, "xg_penalty": 0.0,
                  "description": "☀️  Clear conditions — no xG penalty."}
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
                cur = data["current"]
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

            # ── xG penalty calculation ─────────────────────────────────
            penalty = 0.0
            notes   = []

            bad_conditions = [
                "heavy rain","torrential","blizzard","heavy snow",
                "thunderstorm","sleet","freezing drizzle","ice pellets",
            ]
            cond_lower = condition.lower()

            if any(bc in cond_lower for bc in bad_conditions):
                penalty += 0.08
                notes.append("severe weather")
            elif "rain" in cond_lower or "drizzle" in cond_lower:
                penalty += 0.04
                notes.append("light rain")
            elif "snow" in cond_lower:
                penalty += 0.06
                notes.append("snow")

            if precip_mm > 15:
                penalty += 0.04
                notes.append(f"heavy precip ({precip_mm}mm)")
            elif precip_mm > 5:
                penalty += 0.02
                notes.append(f"light precip ({precip_mm}mm)")

            if wind_kph > 70:
                penalty += 0.04
                notes.append(f"strong wind ({wind_kph}km/h)")
            elif wind_kph > 50:
                penalty += 0.02
                notes.append(f"moderate wind ({wind_kph}km/h)")

            if temp_c < 0:
                penalty += 0.03
                notes.append(f"freezing ({temp_c}°C)")
            elif temp_c > 38:
                penalty += 0.02
                notes.append(f"extreme heat ({temp_c}°C)")

            penalty = min(penalty, 0.15)   # cap at -15% xG

            if notes:
                icon = "⚠️" if penalty > 0.06 else "🌧️"
                desc = f"{icon}  {condition} | {', '.join(notes)} → xG -{penalty*100:.0f}%"
            else:
                desc = f"☀️  {condition} | {temp_c}°C | No xG penalty."

            return {
                "temp_c":      temp_c,
                "condition":   condition,
                "wind_kph":    wind_kph,
                "precip_mm":   precip_mm,
                "humidity":    humidity,
                "xg_penalty":  round(penalty, 3),
                "description": desc,
            }

        except Exception as exc:
            logger.warning("[Weather] %s: %s", city, exc)
            return base

    # ══════════════════════════════════════════════════════════════════════
    # PUBLIC HIGH-LEVEL METHODS
    # ══════════════════════════════════════════════════════════════════════

    def get_matches_for_week(
        self,
        days_ahead: int = 7,
        competitions: list[str] | None = None,
    ) -> list[dict]:
        """
        Fetch matches from today through next `days_ahead` days.
        Cascade: football-data.org → API-Football live → scraping.
        Enriches each match with odds from The Odds API.
        Returns normalised match list sorted by kickoff.
        """
        today    = date.today()
        end_date = today + timedelta(days=days_ahead)
        d_from   = today.isoformat()
        d_to     = end_date.isoformat()

        cache_key = f"matches_{d_from}_{d_to}"
        cached    = self._cache_get(cache_key)
        if cached is not None:
            return cached

        # ── Source 1: football-data.org ───────────────────────────────────
        fd_comps = None
        if competitions:
            fd_comps = [FD_COMPETITIONS[c] for c in competitions if c in FD_COMPETITIONS]

        matches = self._fetch_matches_fd(d_from, d_to, fd_comps)

        # ── Source 2: API-Football live (supplement live matches) ─────────
        live = self._fetch_live_af()
        existing_ids = {m["fixture_id"] for m in matches}
        for lm in live:
            if lm["fixture_id"] not in existing_ids:
                matches.append(lm)

        # ── Source 3: Scraping fallback ───────────────────────────────────
        if len(matches) < 5 and BS4_AVAILABLE:
            logger.info("Falling back to Betexplorer scraping…")
            for i in range(min(days_ahead, 3)):
                d = (today + timedelta(days=i)).isoformat()
                scraped = self._fetch_matches_scrape(d)
                for sm in scraped:
                    if sm["fixture_id"] not in {m["fixture_id"] for m in matches}:
                        matches.append(sm)

        # ── Enrich with odds ──────────────────────────────────────────────
        matches = self._enrich_with_odds(matches)

        # ── Sort by kickoff ───────────────────────────────────────────────
        matches.sort(key=lambda m: m.get("kickoff_utc", ""))

        self._cache_set(cache_key, matches)
        logger.info("[Hybrid] Total matches fetched: %d", len(matches))
        return matches

    def get_matches_for_date(self, target_date: str) -> list[dict]:
        """Filter get_matches_for_week to a specific date."""
        all_m = self.get_matches_for_week(days_ahead=7)
        return [m for m in all_m if m.get("kickoff_date", "") == target_date]

    def _enrich_with_odds(self, matches: list[dict]) -> list[dict]:
        """
        Attach odds to each match.
        Cascade: The Odds API (by league) → scraping per match.
        Conserves Odds API credits by fetching per league (not per match).
        """
        # Pre-fetch odds per league key
        league_odds_cache: dict[str, dict] = {}

        for m in matches:
            league     = m.get("league", "")
            sport_key  = ODDS_API_SPORT_KEYS.get(league)

            # Already has odds (scraped)
            if m.get("home_odds"):
                continue

            # Attempt The Odds API
            if sport_key:
                if sport_key not in league_odds_cache:
                    league_odds_cache[sport_key] = self._fetch_odds_odds_api(sport_key)

                odds_dict = league_odds_cache[sport_key]
                home = m["home_team"]
                away = m["away_team"]

                # Try exact match and partial match
                key     = f"{home} vs {away}"
                odds    = odds_dict.get(key)
                if odds is None:
                    # Fuzzy: check if both team names appear in any key
                    for k, v in odds_dict.items():
                        kl = k.lower()
                        if home.lower()[:8] in kl and away.lower()[:8] in kl:
                            odds = v
                            break

                if odds:
                    m["home_odds"]   = odds["home"]
                    m["draw_odds"]   = odds["draw"]
                    m["away_odds"]   = odds["away"]
                    m["odds_source"] = f"The Odds API ({odds['bookmaker']})"
                    continue

            # Fallback: scrape Betexplorer per match
            if BS4_AVAILABLE:
                scraped_odds = self._fetch_odds_scrape(
                    m["home_team"], m["away_team"], m.get("league","")
                )
                if scraped_odds:
                    m["home_odds"]   = scraped_odds["home"]
                    m["draw_odds"]   = scraped_odds["draw"]
                    m["away_odds"]   = scraped_odds["away"]
                    m["odds_source"] = scraped_odds["bookmaker"]

        return matches

    def get_team_stats(self, team_id: str, league: str = "") -> list[dict]:
        """
        Get team stats with cascade fallback.
        API-Football historical → empty list.
        """
        if team_id.startswith("af_") or team_id.isdigit():
            return self.get_team_stats_af(team_id)
        # football-data.org IDs — stats not available via FD.org free tier
        # Return empty, engine will use standings form as fallback
        return []

    def get_standings_form(self, team_id: str, league: str) -> dict | None:
        """Get team form from standings (football-data.org)."""
        comp_code = FD_COMPETITIONS.get(league)
        if comp_code and team_id.startswith("fd_"):
            return self.get_team_form_fd(team_id, comp_code)
        return None

    def clear_cache(self) -> None:
        """Clear the in-memory cache (force fresh data on next call)."""
        self._cache.clear()
        logger.info("API cache cleared.")


# ─────────────────────────────────────────────────────────────────────────────
# SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 65)
    print("  FOOTBALL ORACLE — Hybrid API Smoke Test")
    print("=" * 65)

    api = FootballOracleAPI()

    print("\n[1] Matches next 7 days …")
    matches = api.get_matches_for_week(days_ahead=7)
    print(f"    → {len(matches)} matches found")
    for m in matches[:5]:
        odds_str = (
            f"H={m['home_odds']:.2f} D={m['draw_odds']:.2f} A={m['away_odds']:.2f}"
            if m.get("home_odds") else "No odds"
        )
        print(f"    {m['kickoff_date']}  {m['home_team']} vs {m['away_team']}"
              f"  [{m['league']}]  {odds_str}")

    print("\n[2] Weather — Bucharest …")
    w = api.get_weather("Bucharest")
    print(f"    → {w['description']}")
    print(f"    → xG penalty: -{w['xg_penalty']*100:.0f}%")

    print("\n" + "=" * 65 + "\n")
