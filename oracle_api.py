"""
================================================================================
FOOTBALL ORACLE — Hybrid API Layer v2.3 (Free Live Football edition)
================================================================================
Surse de date:
  - Free Live Football (RapidAPI) — meciuri, standings, stats xG, H2H, lineups
  - The Odds API                  — events + cote H/D/A
  - football-data.org             — meciuri fallback
  - ESPN public API               — meciuri fallback
  - TheSportsDB                   — meciuri fallback
  - eloratings.net                — ELO naționale
  - WeatherAPI                    — penalizare xG meteo
  - Demo mode                     — când toate sursele eșuează
================================================================================
"""
from __future__ import annotations
import json, logging, random, sys, time
from datetime import date, datetime, timedelta, timezone
from typing import Any
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from cache_manager import get_cache
    CACHE_MANAGER_AVAILABLE = True
except ImportError:
    CACHE_MANAGER_AVAILABLE = False

from key_manager import get_key_manager

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False

from mappings import (
    ODDS_SPORT_KEYS, SPORT_KEY_TO_LEAGUE, FD_COMPETITIONS,
    ESPN_LEAGUE_SLUGS, TSDB_LEAGUE_IDS, TSDB_TEAM_IDS, API_FOOTBALL_LEAGUE_IDS,
    ELO_RATINGS_FALLBACK, FREE_LF_LEAGUE_IDS,
    normalize_team_name, match_key,
)

# ── Chei API ──────────────────────────────────────────────────────────────────
# [ELIMINAT] FOOTBALL_DATA_KEY hardcodat - migrat in key_manager.py (provider "footballdata")
# [ELIMINAT R4.1] ODDS_API_KEY / WEATHER_API_KEY / RAPIDAPI_KEY hardcodate direct
# aici, duplicate ale valorilor deja existente in key_manager.py (provideri
# "oddsapi"/"weatherapi"/"freelivefootball") - gasite si documentate in audit
# (docs/03_ENGINE/API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md §13). Migrate acum
# la self._key_manager.get_api_key_param(...)/get_headers(...), acelasi tipar
# deja folosit pentru "footballdata" in acest fisier (linia 666/703) - nicio
# unealta noua, doar extinderea unui tipar deja functional la restul cheilor.

# ── URL-uri ───────────────────────────────────────────────────────────────────
FOOTBALL_DATA_URL  = "https://api.football-data.org/v4"
ODDS_API_URL       = "https://api.the-odds-api.com/v4"
THESPORTSDB_URL    = "https://www.thesportsdb.com/api/v1/json/3"
ESPN_API_URL       = "https://site.api.espn.com/apis/site/v2/sports/soccer"
WEATHER_URL        = "http://api.weatherapi.com/v1"
ELO_URL            = "https://www.eloratings.net"
FREE_LF_URL        = "https://free-api-live-football-data.p.rapidapi.com"
FREE_LF_HOST       = "free-api-live-football-data.p.rapidapi.com"

DEFAULT_SEASON = 2026

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.API")

# ── User-Agents ───────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]
def _ua() -> str: return random.choice(USER_AGENTS)

# ── Session HTTP ──────────────────────────────────────────────────────────────
def _build_session() -> Session:
    s = Session()
    r = Retry(total=3, backoff_factor=0.5,
              status_forcelist=(429, 500, 502, 503, 504),
              allowed_methods=["GET"], raise_on_status=False)
    a = HTTPAdapter(max_retries=r)
    s.mount("https://", a); s.mount("http://", a)
    return s

# ── Helpers cache disc ────────────────────────────────────────────────────────
# [ELIMINAT — mort dupa reparatie] _disc_load/_disc_save/_disc_fresh si
# ELO_CACHE_PATH/SCORES_CACHE_PATH — inlocuite complet de CacheManager
# (_cget/_cset), care acopera identic aceleasi cazuri (elo: TTL 24h,
# odds_scores: TTL prin categoria "odds"), plus persistare Supabase (L2),
# pe care mecanismul vechi nu o avea deloc.

# ── Fixture-uri demo ──────────────────────────────────────────────────────────
_WC2026_FIXTURES = [
    ("United States","Serbia","2026-06-11","21:00:00","New York"),
    ("Panama","Morocco","2026-06-12","18:00:00","Los Angeles"),
    ("Mexico","Poland","2026-06-12","21:00:00","Dallas"),
    ("Saudi Arabia","Belgium","2026-06-13","00:00:00","Miami"),
    ("Brazil","Croatia","2026-06-13","18:00:00","San Francisco"),
    ("Japan","Colombia","2026-06-13","21:00:00","Seattle"),
    ("England","Netherlands","2026-06-14","21:00:00","Chicago"),
    ("Senegal","Iran","2026-06-14","18:00:00","Toronto"),
    ("France","Australia","2026-06-15","21:00:00","Montreal"),
    ("Denmark","Tunisia","2026-06-15","18:00:00","Kansas City"),
    ("Germany","Japan","2026-06-16","21:00:00","Boston"),
    ("Spain","Costa Rica","2026-06-16","18:00:00","Philadelphia"),
    ("Argentina","Peru","2026-06-17","21:00:00","Atlanta"),
    ("Canada","Ecuador","2026-06-17","18:00:00","Vancouver"),
    ("Portugal","Ghana","2026-06-18","21:00:00","Guadalajara"),
    ("Uruguay","South Korea","2026-06-18","18:00:00","Monterrey"),
]
_MLS_FIXTURES = [
    ("Inter Miami","LA Galaxy","2026-06-11","23:30:00","Miami"),
    ("NYCFC","Seattle Sounders","2026-06-13","23:30:00","New York"),
    ("Portland Timbers","San Jose Earthquakes","2026-06-14","02:30:00","Portland"),
    ("Atlanta United","Orlando City","2026-06-15","23:00:00","Atlanta"),
    ("Club de Foot Montréal","Toronto FC","2026-06-17","23:30:00","Montreal"),
]
_SUPERLIGA_FIXTURES = [
    ("FCSB","CFR Cluj","2026-06-14","19:00:00","Bucharest"),
    ("Rapid București","Universitatea Craiova","2026-06-15","16:30:00","Bucharest"),
    ("Farul Constanța","Petrolul Ploiești","2026-06-16","20:00:00","Constanta"),
]


class FootballOracleAPI:
    """Hybrid data layer v2.3 — Free Live Football ca sursă primară."""

    def __init__(self) -> None:
        self._s   = _build_session()
        self._mem: dict[str, tuple[Any, datetime]] = {}
        self._ttl = 30
        self._dead_keys: set[str] = set()
        self._freelf_exhausted: bool = False
        self._api_football = None  # lazy - vezi _fetch_matches_api_football
        self._active_sport_keys: set[str]   = set()
        # [REPARAT] Inainte, _cget/_cset foloseau DOAR self._mem (dict simplu,
        # in memorie, per-instanta) - complet deconectat de CacheManager
        # (L1 disc + L2 Supabase, construit separat). Asta insemna ca "reducerea
        # apelurilor catre API-uri" nu functiona real pt niciuna din sursele
        # gestionate aici (FreeLF, ESPN, football-data.org, Odds API) - fiecare
        # instanta noua (fiecare rerun Streamlit) pornea cu cache gol.
        self._cache_mgr = get_cache() if CACHE_MANAGER_AVAILABLE else None
        self._key_manager = get_key_manager()
        self._validate_api_keys()
        logger.info("FootballOracleAPI v2.3 initialised.")

    # ── Cache — L1 (disc) + L2 (Supabase), prin CacheManager ──────────────
    # Fallback pe self._mem DOAR daca CacheManager nu e disponibil deloc
    # (nu ar trebui sa se intample in productie - e mereu importabil local).
    _CATEGORY_PREFIXES = (
        ("freelf_standings_", "standings"), ("standings_", "standings"),
        ("freelf_form_", "form"),
        ("freelf_stats_", "stats"),
        ("freelf_h2h_", "h2h"),
        ("freelf_lineup_", "lineups"),
        ("odds_", "odds"), ("events_", "odds"),
    )
    _PROVIDER_PREFIXES = (
        ("freelf_", "freelivefootball"), ("espn_", "espn"),
        ("odds_", "oddsapi"), ("events_", "oddsapi"),
        ("standings_", "footballdata"),
    )

    def _category_for_key(self, key: str) -> str:
        if key == "elo_ratings":
            return "elo"
        for prefix, category in self._CATEGORY_PREFIXES:
            if key.startswith(prefix):
                return category
        return "matches"  # freelf_matches_, espn_*, week_* - liste de meciuri

    def _provider_for_key(self, key: str) -> str:
        if key == "elo_ratings":
            return "eloratings"
        for prefix, provider in self._PROVIDER_PREFIXES:
            if key.startswith(prefix):
                return provider
        return "multi"  # ex. week_ combina mai multe surse deodata

    def _cget(self, key: str) -> Any | None:
        if self._cache_mgr is not None:
            return self._cache_mgr.get_raw(self._category_for_key(key), key)
        # fallback — doar daca CacheManager nu exista deloc
        if key in self._mem:
            v, ts = self._mem[key]
            ttl = 240 if key.startswith("odds_") else self._ttl
            if (datetime.now(timezone.utc) - ts).total_seconds() < ttl * 60:
                return v
        return None

    def _cset(self, key: str, val: Any) -> None:
        if self._cache_mgr is not None:
            self._cache_mgr.set(
                self._category_for_key(key), key, val,
                provider=self._provider_for_key(key),
            )
            return
        self._mem[key] = (val, datetime.now(timezone.utc))

    # ── Low-level HTTP ────────────────────────────────────────────────────
    # [ADAUGAT] Mapare host -> nume provider, pt observabilitate (provider_metrics).
    # Reutilizeaza constantele de URL deja existente - nu introduce coduri noi.
    _PROVIDER_HOST_MAP = (
        (FREE_LF_URL, "freelivefootball"),
        (ODDS_API_URL, "oddsapi"),
        (FOOTBALL_DATA_URL, "footballdata"),
        (THESPORTSDB_URL, "thesportsdb"),
        (ESPN_API_URL, "espn"),
        (WEATHER_URL, "weatherapi"),
        (ELO_URL, "eloratings"),
    )

    def _detect_provider_endpoint(self, url: str) -> tuple[str, str]:
        for prefix, name in self._PROVIDER_HOST_MAP:
            if url.startswith(prefix):
                rest = url[len(prefix):].lstrip("/")
                endpoint = rest.split("?")[0].split("/")[0] or "root"
                return name, endpoint
        return "unknown", "unknown"

    def _record_metric(self, url: str, success: bool, latency_ms: float) -> None:
        # Best-effort, nu blocheaza fluxul principal daca esueaza (acelasi
        # principiu de degradare gratioasa folosit peste tot in proiect).
        try:
            provider, endpoint = self._detect_provider_endpoint(url)
            import supabase_client as _sb
            _sb.record_provider_call(provider, endpoint, success, latency_ms)
        except Exception:
            pass

    def _get(self, url: str, headers=None, params=None, timeout: int = 12):
        start = time.monotonic()
        try:
            r = self._s.get(url, headers=headers or {}, params=params or {}, timeout=timeout)
            latency_ms = (time.monotonic() - start) * 1000
            if r.status_code == 404:
                logger.warning("[HTTP 404] %s", url[:80]); self._record_metric(url, False, latency_ms); return None
            if r.status_code == 403:
                logger.warning("[HTTP 403] %s", url[:80]); self._record_metric(url, False, latency_ms); return None
            if r.status_code == 429:
                logger.warning("[HTTP 429] %s", url[:80])
                self._record_metric(url, False, latency_ms)
                if FREE_LF_HOST in url:
                    self._freelf_exhausted = True
                    logger.warning("[FreeLF] Limita 429 — trecem pe fallback ESPN/demo.")
                return None
            if not r.ok:
                logger.warning("[HTTP %s] %s", r.status_code, url[:80]); self._record_metric(url, False, latency_ms); return None
            self._record_metric(url, True, latency_ms)
            return r.json()
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            self._record_metric(url, False, latency_ms)
            logger.error("[HTTP] %s → %s", url[:80], exc); return None

    def _free_lf_get(self, path: str, params=None):
        """Wrapper pentru Free Live Football API (RapidAPI)."""
        return self._get(
            f"{FREE_LF_URL}/{path}",
            headers=self._key_manager.get_headers("freelivefootball") or {},
            params=params or {},
        )

    # ── Startup validation ────────────────────────────────────────────────
    def _validate_api_keys(self) -> None:
        data = self._get(f"{ODDS_API_URL}/sports",
                         params={"apiKey": self._key_manager.get_api_key_param("oddsapi"), "all": "true"})
        if not isinstance(data, list):
            logger.warning("[Validate] Could not fetch sport keys."); return
        active = {s["key"] for s in data if not s.get("has_outrights", False)}
        self._active_sport_keys = active
        for league, sk in ODDS_SPORT_KEYS.items():
            if sk not in active:
                self._dead_keys.add(sk)
                logger.info("[Validate] Dead: %s → %s", league, sk)

    # ── Free Live Football — meciuri pe zi ────────────────────────────────
    def _fetch_freelf_matches(self, target_date: str, league: str) -> list[dict]:
        if self._freelf_exhausted:
            return []
        league_id = FREE_LF_LEAGUE_IDS.get(league)
        if not league_id:
            return []
        cache_key = f"freelf_matches_{target_date}_{league}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached
        date_fmt = target_date.replace("-", "")  # YYYYMMDD
        data = self._free_lf_get(
            "football-get-matches-by-date",
            params={"date": date_fmt},
        )
        if not data:
            self._cset(cache_key, []); return []

        # Detectare automată cheie listă în răspuns
        # Free Live Football returnează {"status":..., "response": {...}} sau {"response": [...]}
        raw_list: list = []
        resp = data.get("response")
        if isinstance(resp, list):
            raw_list = resp
        elif isinstance(resp, dict):
            # response e un dict — caută lista înăuntru
            for inner_key in ("matches", "events", "data", "fixtures", "results"):
                if isinstance(resp.get(inner_key), list):
                    raw_list = resp[inner_key]
                    break
            if not raw_list:
                for v in resp.values():
                    if isinstance(v, list) and v:
                        raw_list = v
                        break
            if not raw_list:
                logger.warning("[FreeLF] response dict keys: %s", list(resp.keys())[:10])
                self._cset(cache_key, []); return []
        elif isinstance(data.get("matches"), list):
            raw_list = data["matches"]
        elif isinstance(data.get("events"), list):
            raw_list = data["events"]
        elif isinstance(data.get("data"), list):
            raw_list = data["data"]
        else:
            logger.warning("[FreeLF] Unknown response structure keys: %s", list(data.keys())[:10])
            self._cset(cache_key, []); return []

        results: list[dict] = []
        for ev in raw_list:
            if not isinstance(ev, dict):
                continue
            try:
                # parentLeagueId e ID-ul canonical, leagueId e runda internă
                parent_lid = ev.get("parentLeagueId") or ev.get("leagueId")
                if parent_lid != league_id:
                    continue
                status = (ev.get("status") or {}).get("type", "")
                if status not in ("notstarted", "inprogress", ""):
                    continue
                home_raw = (ev.get("homeTeam") or {}).get("name", "") or ""
                away_raw = (ev.get("awayTeam") or {}).get("name", "") or ""
                home = normalize_team_name(home_raw)
                away = normalize_team_name(away_raw)
                if not home or not away:
                    continue
                event_id = ev.get("id") or ev.get("eventId")
                ts = ev.get("startTimestamp") or 0
                ko_utc = (datetime.fromtimestamp(ts, tz=timezone.utc)
                          .strftime("%Y-%m-%dT%H:%M:%SZ") if ts
                          else f"{target_date}T00:00:00Z")
                coverage = ev.get("coverageLevel") or ev.get("coverage_level") or ""
                results.append({
                    "fixture_id":       f"freelf_{event_id}",
                    "home_team":        home,
                    "away_team":        away,
                    "home_team_id":     f"freelf_{(ev.get('homeTeam') or {}).get('id','')}",
                    "away_team_id":     f"freelf_{(ev.get('awayTeam') or {}).get('id','')}",
                    "_freelf_event_id": event_id,
                    "_freelf_home_id":  (ev.get("homeTeam") or {}).get("id"),
                    "_freelf_away_id":  (ev.get("awayTeam") or {}).get("id"),
                    "kickoff_utc":      ko_utc,
                    "kickoff_date":     target_date,
                    "league":           league,
                    "season":           DEFAULT_SEASON,
                    "venue_city":       (ev.get("venue") or {}).get("city", "") or "",
                    "status":           "scheduled",
                    "coverage_level":   coverage,
                    "home_odds":        None,
                    "draw_odds":        None,
                    "away_odds":        None,
                    "odds_source":      None,
                    "source":           "freelivefootball",
                })
            except (KeyError, TypeError):
                continue
        self._cset(cache_key, results)
        return results

    # ── Free Live Football — standings ────────────────────────────────────
    def get_freelf_standings(self, league: str) -> list[dict]:
        if self._freelf_exhausted:
            return []
        league_id = FREE_LF_LEAGUE_IDS.get(league)
        if not league_id:
            return []
        cache_key = f"freelf_standings_{league}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached
        data = self._free_lf_get(
            "football-get-standing-all",
            params={"leagueid": league_id},
        )
        if not data:
            self._cset(cache_key, []); return []
        # cheia răspunsului e "standing" (singular)
        raw = data.get("standing") or data.get("response") or []
        results: list[dict] = []
        for entry in raw:
            try:
                team_name = normalize_team_name(
                    (entry.get("team") or {}).get("name", "") or ""
                )
                if not team_name:
                    continue
                played = int(entry.get("played") or entry.get("matches") or 1) or 1
                gf = int(entry.get("goalsFor") or entry.get("goals_for") or 0)
                ga = int(entry.get("goalsAgainst") or entry.get("goals_against") or 0)
                results.append({
                    "team":             team_name,
                    "team_id":          (entry.get("team") or {}).get("id"),
                    "played":           played,
                    "wins":             int(entry.get("wins") or 0),
                    "draws":            int(entry.get("draws") or 0),
                    "losses":           int(entry.get("losses") or 0),
                    "goals_for":        gf,
                    "goals_against":    ga,
                    "avg_gf":           round(gf / played, 3),
                    "avg_ga":           round(ga / played, 3),
                    "points":           int(entry.get("points") or 0),
                    "position":         int(entry.get("position") or entry.get("rank") or 0),
                })
            except (TypeError, ValueError):
                continue
        self._cset(cache_key, results)
        return results

    # ── Free Live Football — forma recentă echipă ─────────────────────────
    def get_team_form_freelf(self, team_id: int, league: str, last_n: int = 5) -> list[dict]:
        if not team_id:
            return []
        cache_key = f"freelf_form_{team_id}_{league}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached
        # folosim standings pentru a extrage forma — Free LF nu are endpoint
        # dedicat de form, dar are "form" string în standings
        standings = self.get_freelf_standings(league)
        for entry in standings:
            if entry.get("team_id") == team_id:
                form_str = entry.get("form", "") or ""
                results: list[dict] = []
                for ch in form_str[-last_n:]:
                    results.append({"result": ch.upper(), "goals_for": 0,
                                    "goals_against": 0, "date": ""})
                self._cset(cache_key, results)
                return results
        self._cset(cache_key, [])
        return []

    # ── Free Live Football — statistics (xG) ─────────────────────────────
    def get_match_statistics(self, event_id: int) -> dict | None:
        if self._freelf_exhausted or not event_id:
            return None
        cache_key = f"freelf_stats_{event_id}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached
        data = self._free_lf_get(f"statistics/{event_id}")
        if not data:
            self._cset(cache_key, None); return None
        stats = data.get("statistics") or data.get("response") or {}
        result = {
            "home_xg":         float((stats.get("home") or {}).get("expected_goals") or 0),
            "away_xg":         float((stats.get("away") or {}).get("expected_goals") or 0),
            "home_possession": float((stats.get("home") or {}).get("BallPossession") or 50),
            "away_possession": float((stats.get("away") or {}).get("BallPossession") or 50),
            "home_shots_ot":   int((stats.get("home") or {}).get("ShotsOnTarget") or 0),
            "away_shots_ot":   int((stats.get("away") or {}).get("ShotsOnTarget") or 0),
            "home_big_chance": int((stats.get("home") or {}).get("big_chance") or 0),
            "away_big_chance": int((stats.get("away") or {}).get("big_chance") or 0),
            "source": "freelivefootball-statistics",
        }
        self._cset(cache_key, result)
        return result

    def has_xg_coverage(self, match: dict) -> bool:
        """Verifică dacă meciul are coverage xG fără să cheltuie credit."""
        return str(match.get("coverage_level", "")).lower() == "xg"

    # ── Free Live Football — H2H ──────────────────────────────────────────
    def get_h2h(self, event_id: int, home_name: str = "", away_name: str = "") -> dict | None:
        if self._freelf_exhausted or not event_id:
            return None
        cache_key = f"freelf_h2h_{event_id}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached
        data = self._free_lf_get(f"h2h/{event_id}")
        if not data:
            self._cset(cache_key, None); return None
        # summary: [home_wins, draws, away_wins]
        summary_raw = data.get("summary") or []
        matches_raw = data.get("matches") or []
        home_wins = int(summary_raw[0]) if len(summary_raw) > 0 else 0
        draws     = int(summary_raw[1]) if len(summary_raw) > 1 else 0
        away_wins = int(summary_raw[2]) if len(summary_raw) > 2 else 0
        n = home_wins + draws + away_wins
        if n == 0:
            self._cset(cache_key, None); return None
        home_g_total = away_g_total = 0
        last_5: list[str] = []
        for m in matches_raw[:10]:
            try:
                hs = int((m.get("homeScore") or {}).get("current") or 0)
                as_ = int((m.get("awayScore") or {}).get("current") or 0)
                home_g_total += hs; away_g_total += as_
                if len(last_5) < 5:
                    if hs > as_: last_5.append("H")
                    elif hs < as_: last_5.append("A")
                    else: last_5.append("D")
            except (TypeError, ValueError):
                continue
        home_g_avg = round(home_g_total / n, 2)
        away_g_avg = round(away_g_total / n, 2)
        dominance  = (home_wins - away_wins) / n
        h2h_modifier = round(dominance * 0.15, 4)
        summary_str = (
            f"H2H ({n} meciuri): {home_wins}W {draws}D {away_wins}L | "
            f"Goluri: {home_g_avg:.1f}–{away_g_avg:.1f} | "
            f"Ultimele: {''.join(last_5)}"
        )
        result = {
            "meetings": n, "home_wins": home_wins, "draws": draws,
            "away_wins": away_wins, "home_goals_avg": home_g_avg,
            "away_goals_avg": away_g_avg, "last_5": last_5,
            "h2h_modifier": h2h_modifier, "summary": summary_str,
        }
        self._cset(cache_key, result)
        return result

    # ── Free Live Football — lineup / absențe ─────────────────────────────
    def get_lineup(self, event_id: int, is_home: bool) -> dict | None:
        if self._freelf_exhausted or not event_id:
            return None
        side = "home" if is_home else "away"
        cache_key = f"freelf_lineup_{event_id}_{side}"
        cached = self._cget(cache_key)
        if cached is not None:
            return cached
        endpoint = (
            "football-get-hometeam-lineup" if is_home
            else "football-get-awayteam-lineup"
        )
        data = self._free_lf_get(endpoint, params={"eventid": event_id})
        if not data:
            self._cset(cache_key, None); return None
        lineup_raw = data.get("lineup") or data.get("response") or {}
        unavailable = lineup_raw.get("unavailable") or []
        result = {
            "confirmed": bool(lineup_raw.get("confirmed")),
            "formation": lineup_raw.get("formation") or "",
            "unavailable": [
                {
                    "id":              p.get("id"),
                    "name":            p.get("name", ""),
                    "market_value":    float(p.get("marketValue") or 0),
                    "unavailability":  p.get("unavailability") or {},
                }
                for p in unavailable
            ],
        }
        self._cset(cache_key, result)
        return result

    # ── Odds API — events ─────────────────────────────────────────────────
    def _fetch_events_odds_api(self, sport_key: str, days_ahead: int = 7) -> list[dict]:
        if sport_key in self._dead_keys: return []
        cache_key = f"events_{sport_key}_{days_ahead}"
        cached = self._cget(cache_key)
        if cached is not None: return cached
        now = datetime.now(timezone.utc)
        data = self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/events",
            params={"apiKey": self._key_manager.get_api_key_param("oddsapi"),
                    "commenceTimeFrom": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "commenceTo": (now + timedelta(days=days_ahead)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        )
        if data is None: self._dead_keys.add(sport_key); self._cset(cache_key, []); return []
        if not isinstance(data, list): self._cset(cache_key, []); return []
        league_name = SPORT_KEY_TO_LEAGUE.get(sport_key, sport_key)
        results: list[dict] = []
        for ev in data:
            try:
                ko   = ev.get("commence_time", "")
                home = normalize_team_name(ev["home_team"])
                away = normalize_team_name(ev["away_team"])
                results.append({
                    "fixture_id":    f"odds_{ev['id']}",
                    "home_team":     home, "away_team": away,
                    "home_team_id":  None, "away_team_id": None,
                    "kickoff_utc":   ko,
                    "kickoff_date":  ko[:10] if ko else "",
                    "league":        league_name, "season": DEFAULT_SEASON,
                    "venue_city":    "", "status": "scheduled",
                    "coverage_level": "",
                    "home_odds":     None, "draw_odds": None, "away_odds": None,
                    "odds_source":   None, "source": "the-odds-api",
                    "_odds_api_id":  ev["id"], "_sport_key": sport_key,
                })
            except (KeyError, TypeError): continue
        self._cset(cache_key, results); return results

    # ── Odds API — scores (formă recentă fallback) ────────────────────────
    def _fetch_scores_odds_api(self, sport_key: str, days_back: int = 3) -> list[dict]:
        if sport_key in self._dead_keys: return []
        # [REPARAT] Ocolea complet CacheManager, folosind doar un fisier disc
        # separat (scores_cache.json) - gasit prin audit final, dupa deploy.
        cache_key = f"odds_scores_{sport_key}_{days_back}"
        cached = self._cget(cache_key)
        if cached is not None: return cached
        data = self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/scores",
            params={"apiKey": self._key_manager.get_api_key_param("oddsapi"), "daysFrom": days_back},
        )
        if not isinstance(data, list): return []
        results: list[dict] = []
        for ev in data:
            try:
                if not ev.get("completed"): continue
                scores   = ev.get("scores") or []
                home_raw = ev.get("home_team", ""); away_raw = ev.get("away_team", "")
                home = normalize_team_name(home_raw); away = normalize_team_name(away_raw)
                sm: dict[str, int] = {}
                for sc in scores:
                    sm[normalize_team_name(sc["name"])] = int(sc.get("score", 0))
                hs  = sm.get(home, sm.get(home_raw, 0))
                as_ = sm.get(away, sm.get(away_raw, 0))
                ko  = ev.get("commence_time", "")
                results.append({
                    "home_team": home, "away_team": away,
                    "home_score": hs, "away_score": as_,
                    "kickoff_utc": ko, "kickoff_date": ko[:10] if ko else "",
                    "league": SPORT_KEY_TO_LEAGUE.get(ev.get("sport_key", ""), ""),
                    "source": "the-odds-api-scores",
                })
            except (KeyError, TypeError, ValueError): continue
        self._cset(cache_key, results)
        return results

    def get_team_recent_form(self, team_name: str, league: str, days_back: int = 14) -> list[dict]:
        canonical = normalize_team_name(team_name)
        sport_key = ODDS_SPORT_KEYS.get(league)
        raw = self._fetch_scores_odds_api(sport_key, days_back=min(days_back, 3)) if sport_key else []
        form: list[dict] = []
        for s in raw:
            if s["home_team"] != canonical and s["away_team"] != canonical: continue
            is_home = s["home_team"] == canonical
            gf = s["home_score"] if is_home else s["away_score"]
            ga = s["away_score"] if is_home else s["home_score"]
            result = "W" if gf > ga else ("L" if gf < ga else "D")
            form.append({"date": s["kickoff_date"], "result": result,
                         "goals_for": gf, "goals_against": ga,
                         "shots_on_goal": round(gf * 3.5, 1), "possession": 50.0})
        return sorted(form, key=lambda x: x["date"], reverse=True)

    # ── football-data.org ─────────────────────────────────────────────────
    def _fetch_matches_fd(self, date_from: str, date_to: str, comp_codes=None) -> list[dict]:
        params: dict = {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED,TIMED"}
        if comp_codes: params["competitions"] = ",".join(comp_codes)
        data = self._get(
            f"{FOOTBALL_DATA_URL}/matches",
            headers=self._key_manager.get_headers("footballdata") or {}, params=params,
        )
        if not data: return []
        results: list[dict] = []
        for m in data.get("matches", []):
            try:
                ko       = m.get("utcDate", "")
                home_raw = (m.get("homeTeam") or {}).get("name") or ""
                away_raw = (m.get("awayTeam") or {}).get("name") or ""
                home = normalize_team_name(home_raw)
                away = normalize_team_name(away_raw)
                if not home or not away: continue
                results.append({
                    "fixture_id":    f"fd_{m['id']}",
                    "home_team":     home, "away_team": away,
                    "home_team_id":  f"fd_{(m.get('homeTeam') or {}).get('id','')}",
                    "away_team_id":  f"fd_{(m.get('awayTeam') or {}).get('id','')}",
                    "kickoff_utc":   ko,
                    "kickoff_date":  ko[:10] if ko else date_from,
                    "league":        (m.get("competition") or {}).get("name", "Unknown"),
                    "season":        DEFAULT_SEASON,
                    "venue_city":    (m.get("area") or {}).get("name", ""),
                    "status":        m.get("status", "SCHEDULED").lower(),
                    "coverage_level": "",
                    "home_odds":     None, "draw_odds": None, "away_odds": None,
                    "odds_source":   None, "source": "football-data.org",
                })
            except (KeyError, TypeError): continue
        return results

    def get_team_form_fd(self, team_id: str, comp_code: str) -> dict | None:
        tid = team_id.replace("fd_", "")
        if not tid.isdigit(): return None
        cache_key = f"standings_{comp_code}"; cached = self._cget(cache_key)
        if cached is None:
            cached = self._get(
                f"{FOOTBALL_DATA_URL}/competitions/{comp_code}/standings",
                headers=self._key_manager.get_headers("footballdata") or {},
            )
            if cached: self._cset(cache_key, cached)
        if not cached: return None
        for grp in cached.get("standings", []):
            for entry in grp.get("table", []):
                if str((entry.get("team") or {}).get("id", "")) == tid:
                    played = entry.get("playedGames") or 1
                    return {
                        "played": played,
                        "goals_for": entry.get("goalsFor", 0),
                        "goals_against": entry.get("goalsAgainst", 0),
                        "form": entry.get("form", "") or "",
                        "avg_gf": round((entry.get("goalsFor", 0) or 0) / played, 3),
                        "avg_ga": round((entry.get("goalsAgainst", 0) or 0) / played, 3),
                    }
        return None

    def get_standings_form(self, team_id: str, league: str) -> dict | None:
        comp_code = FD_COMPETITIONS.get(league)
        if comp_code and team_id and team_id.startswith("fd_"):
            return self.get_team_form_fd(team_id, comp_code)
        return None

    # ── ESPN ──────────────────────────────────────────────────────────────
    def _fetch_matches_espn(self, league: str, target_date: str) -> list[dict]:
        slug = ESPN_LEAGUE_SLUGS.get(league)
        if not slug: return []
        cache_key = f"espn_{slug}_{target_date}"
        cached = self._cget(cache_key)
        if cached is not None: return cached
        data = self._get(
            f"{ESPN_API_URL}/{slug}/scoreboard",
            headers={"User-Agent": _ua()},
            params={"dates": target_date.replace("-", "")},
        )
        if not data: self._cset(cache_key, []); return []
        results: list[dict] = []
        for ev in data.get("events", []):
            try:
                comps       = ev.get("competitions", [{}])[0]
                competitors = comps.get("competitors", [])
                if len(competitors) < 2: continue
                home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                hn = normalize_team_name((home.get("team") or {}).get("displayName", ""))
                an = normalize_team_name((away.get("team") or {}).get("displayName", ""))
                if not hn or not an: continue
                state = (ev.get("status") or {}).get("type", {}).get("state", "pre")
                if state not in ("pre", "in"): continue
                date_str = ev.get("date", "")
                results.append({
                    "fixture_id":    f"espn_{ev['id']}",
                    "home_team":     hn, "away_team": an,
                    "home_team_id":  f"espn_{(home.get('team') or {}).get('id','')}",
                    "away_team_id":  f"espn_{(away.get('team') or {}).get('id','')}",
                    "kickoff_utc":   date_str,
                    "kickoff_date":  date_str[:10] if date_str else target_date,
                    "league":        league, "season": DEFAULT_SEASON,
                    "venue_city":    (comps.get("venue") or {}).get("address", {}).get("city", ""),
                    "status":        "scheduled", "coverage_level": "",
                    "home_odds":     None, "draw_odds": None, "away_odds": None,
                    "odds_source":   None, "source": "espn",
                })
            except (KeyError, TypeError, IndexError): continue
        self._cset(cache_key, results); return results

    # ── TheSportsDB ───────────────────────────────────────────────────────
    def _tsdb_season_string(self, on_date: date | None = None) -> str:
        """Sezon fotbal european ('2026-2027'), calculat DINAMIC din data
        curenta (sezonul incepe in iulie) — niciodata hardcodat."""
        d = on_date or date.today()
        start_year = d.year if d.month >= 7 else d.year - 1
        return f"{start_year}-{start_year + 1}"

    def _parse_tsdb_event(self, ev: dict, league_name: str, today: str) -> dict | None:
        try:
            ev_date = ev.get("dateEvent", "")
            if ev_date and ev_date < today: return None
            home = normalize_team_name(ev.get("strHomeTeam", "") or "")
            away = normalize_team_name(ev.get("strAwayTeam", "") or "")
            if not home or not away: return None
            ev_time = ev.get("strTime", "00:00:00") or "00:00:00"
            ko_utc  = f"{ev_date}T{ev_time[:8]}Z" if ev_date else ""
            return {
                "fixture_id":    f"tsdb_{ev.get('idEvent','')}",
                "home_team":     home, "away_team": away,
                "home_team_id":  f"tsdb_{ev.get('idHomeTeam','')}",
                "away_team_id":  f"tsdb_{ev.get('idAwayTeam','')}",
                "kickoff_utc":   ko_utc, "kickoff_date": ev_date,
                "league":        league_name, "season": DEFAULT_SEASON,
                "venue_city":    ev.get("strVenue", ""), "status": "scheduled",
                "coverage_level": "",
                "home_odds":     None, "draw_odds": None, "away_odds": None,
                "odds_source":   None, "source": "thesportsdb",
            }
        except (KeyError, TypeError):
            return None

    def _fetch_matches_tsdb(self, league_id: str, league_name: str) -> list[dict]:
        today = date.today().isoformat()
        team_ids = TSDB_TEAM_IDS.get(league_name)

        if not team_ids:
            # Cale NESCHIMBATA — eventsnextleague.php, fara reconciliere.
            # Ligile fara TSDB_TEAM_IDS populat raman pe calea veche,
            # verificata ani de zile. Reconcilierea de mai jos e aplicata
            # STRICT ligilor cu dovada live de necesitate (investigatia
            # Etapa 1 SuperLiga) — un endpoint nou, netestat pe cupe
            # europene (Champions/Europa/Conference/World Cup), ar risca
            # o regresie nedemonstrata pe ligi care functioneaza deja corect.
            data = self._get(f"{THESPORTSDB_URL}/eventsnextleague.php", params={"id": league_id})
            results: list[dict] = []
            for ev in (data or {}).get("events") or []:
                parsed = self._parse_tsdb_event(ev, league_name, today)
                if parsed: results.append(parsed)
            return results

        # Reconciliere (dovedita necesara — vezi TSDB_TEAM_IDS, mappings.py):
        # UNIUNEA a trei surse, fiecare cu goluri diferite, confirmate live:
        #   1. eventsnextleague.php — singurul care are, azi, Universitatea
        #      Cluj-Farul Constanța (absent din eventsseason.php).
        #   2. eventsseason.php (sezon calculat dinamic) — 62.5% completitudine
        #      fata de calendarul oficial LPF, vs. 12.5% pentru
        #      eventsnextleague.php singur.
        #   3. supliment per echipa (eventsnext.php, TSDB_TEAM_IDS) — pentru
        #      meciurile absente din AMBELE endpointuri de mai sus, dovedite
        #      prezente STRICT la nivel de echipa.
        # Niciuna dintre cele trei, singura, nu e completa — dovedit live,
        # 2026-07-19: eventsseason.php a intors 0 evenimente viitoare (toate
        # meciurile rundei 1 deja jucate/in curs), iar fara #1 mai sus,
        # Universitatea Cluj-Farul Constanța ar fi disparut complet.
        # Deduplicare prin match_key(), acelasi mecanism deja folosit in
        # get_matches_for_week().
        season = self._tsdb_season_string()
        seen_keys: set[str] = set()
        results: list[dict] = []

        def _add(events: list[dict]) -> None:
            for ev in events:
                parsed = self._parse_tsdb_event(ev, league_name, today)
                if parsed is None: continue
                mk = match_key(parsed["home_team"], parsed["away_team"], parsed["kickoff_date"])
                if mk in seen_keys: continue
                seen_keys.add(mk)
                results.append(parsed)

        nextleague_data = self._get(f"{THESPORTSDB_URL}/eventsnextleague.php", params={"id": league_id})
        _add((nextleague_data or {}).get("events") or [])

        season_data = self._get(f"{THESPORTSDB_URL}/eventsseason.php", params={"id": league_id, "s": season})
        _add((season_data or {}).get("events") or [])

        for team_id in team_ids.values():
            team_data = self._get(f"{THESPORTSDB_URL}/eventsnext.php", params={"id": team_id})
            _add((team_data or {}).get("events") or [])

        return results

    # ── API-Football — fallback ultim, generic prin mappings.py ─────────────
    def _fetch_matches_api_football(self, league: str, date_from: str, date_to: str) -> list[dict]:
        """Nu e sursa primara pentru nicio liga — apelata DOAR din pasul 6 al
        get_matches_for_week(), cand liga respectiva nu are niciun meci de la
        providerii de mai sus. Orice liga noua devine eligibila doar prin
        completarea provider_ids["api_football"] in mappings.py, fara nicio
        schimbare aici."""
        league_id = API_FOOTBALL_LEAGUE_IDS.get(league)
        if not league_id:
            return []
        if self._api_football is None:
            from football_providers import ApiFootballProvider
            self._api_football = ApiFootballProvider(key_manager=self._key_manager, cache=self._cache_mgr)
        return self._api_football.get_fixtures(league, league_id, date_from, date_to, season=DEFAULT_SEASON)

    def get_team_last_events_tsdb(self, team_id: str) -> list[dict]:
        tid = team_id.replace("tsdb_", "")
        if not tid.isdigit(): return []
        data = self._get(f"{THESPORTSDB_URL}/eventslast.php", params={"id": tid})
        if not data: return []
        results: list[dict] = []
        for ev in data.get("results") or []:
            try:
                hs  = int(ev.get("intHomeScore") or 0)
                as_ = int(ev.get("intAwayScore") or 0)
                is_home = ev.get("idHomeTeam") == tid
                gf = hs if is_home else as_; ga = as_ if is_home else hs
                results.append({
                    "date": ev.get("dateEvent", ""),
                    "result": "W" if gf > ga else ("L" if gf < ga else "D"),
                    "goals_for": gf, "goals_against": ga,
                    "shots_on_goal": round(gf * 3.5, 1), "possession": 50.0,
                })
            except (ValueError, TypeError): continue
        return results

    def get_team_stats(self, team_id: str, league: str = "") -> list[dict]:
        if team_id and team_id.startswith("tsdb_"):
            return self.get_team_last_events_tsdb(team_id)
        return []

    # ── Demo mode ─────────────────────────────────────────────────────────
    def _generate_demo_matches(self, competitions: list[str]) -> list[dict]:
        today = date.today(); cutoff = today + timedelta(days=10)
        demo_id = 90000; results: list[dict] = []
        sets = [
            ("World Cup 2026",    _WC2026_FIXTURES),
            ("MLS",               _MLS_FIXTURES),
            ("Romania SuperLiga", _SUPERLIGA_FIXTURES),
        ]
        for league_name, fixtures in sets:
            if league_name not in competitions and competitions: continue
            for home, away, match_date, ko_time, city in fixtures:
                md = date.fromisoformat(match_date)
                if not (today <= md <= cutoff): continue
                demo_id += 1
                results.append({
                    "fixture_id":    f"demo_{demo_id}",
                    "home_team":     normalize_team_name(home),
                    "away_team":     normalize_team_name(away),
                    "home_team_id":  f"demo_h_{demo_id}",
                    "away_team_id":  f"demo_a_{demo_id}",
                    "kickoff_utc":   f"{match_date}T{ko_time}Z",
                    "kickoff_date":  match_date,
                    "league":        league_name, "season": DEFAULT_SEASON,
                    "venue_city":    city, "status": "scheduled",
                    "coverage_level": "",
                    "home_odds":     None, "draw_odds": None, "away_odds": None,
                    "odds_source":   None,
                    "source":        f"demo-{league_name.lower().replace(' ','-')}",
                })
        return results

    # ── ELO ratings ───────────────────────────────────────────────────────
    def _fetch_elo_ratings(self) -> dict[str, int]:
        # [REPARAT] Elimin stratul redundant (_disc_fresh + self._elo_cache) -
        # CacheManager (prin _cget, categoria "elo", TTL 24h) acoperea deja
        # exact acelasi caz, dublat inutil. O singura sursa de adevar acum.
        cached = self._cget("elo_ratings")
        if cached is not None: return cached
        if not BS4_AVAILABLE:
            fallback = dict(ELO_RATINGS_FALLBACK)
            self._cset("elo_ratings", fallback); return fallback
        try:
            r = self._s.get(ELO_URL,
                            headers={"User-Agent": _ua(), "Accept-Language": "en-US,en;q=0.9"},
                            timeout=15)
            if not r.ok: raise Exception(f"HTTP {r.status_code}")
            soup = BeautifulSoup(r.text, "html.parser"); ratings: dict[str, int] = {}
            table = soup.find("table")
            if table:
                for row in table.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if len(cells) < 3: continue
                    try:
                        raw_name = cells[1].get_text(strip=True)
                        raw_elo  = cells[2].get_text(strip=True).replace(",", "")
                        elo_val  = int(raw_elo)
                        canonical = normalize_team_name(raw_name)
                        if canonical and elo_val > 0: ratings[canonical] = elo_val
                    except (ValueError, IndexError): continue
            if not ratings: ratings = dict(ELO_RATINGS_FALLBACK)
            self._cset("elo_ratings", ratings)
            return ratings
        except Exception as exc:
            logger.error("[ELO] Scrape failed: %s", exc)
            fallback = dict(ELO_RATINGS_FALLBACK)
            self._cset("elo_ratings", fallback); return fallback

    def get_elo_rating(self, team_name: str) -> int | None:
        canonical = normalize_team_name(team_name)
        ratings   = self._fetch_elo_ratings()
        result    = ratings.get(canonical)
        if result is None:
            result = ELO_RATINGS_FALLBACK.get(canonical)
            if result: logger.info("[ELO] %s in hardcoded fallback: %d", canonical, result)
        return result

    # ── Odds ──────────────────────────────────────────────────────────────
    def _fetch_market(self, sport_key: str, markets: str) -> list | None:
        """Un singur apel către /odds cu setul de piețe dat — izolat, astfel
        încât un eșec pe piețe suplimentare (ex. btts indisponibil pe planul
        curent) nu poate afecta niciodată h2h, deja funcțional."""
        return self._get(
            f"{ODDS_API_URL}/sports/{sport_key}/odds",
            params={"apiKey": self._key_manager.get_api_key_param("oddsapi"), "regions": "eu",
                    "markets": markets, "oddsFormat": "decimal"},
        )

    def _fetch_odds(self, sport_key: str) -> dict[str, dict]:
        if sport_key in self._dead_keys: return {}
        cache_key = f"odds_{sport_key}"
        cached = self._cget(cache_key)
        if cached is not None: return cached

        # [ADAUGAT] h2h + totals (Over/Under) într-un singur apel — totals e
        # piață standard la fotbal, cost minim suplimentar de quota. Dacă
        # eșuează integral (ex. cont fără acces la "totals"), fallback la h2h
        # singur — exact comportamentul de dinainte, zero regresie pe piața
        # deja folosită (vezi ADR-001 spirit: degradare grațioasă, nimic
        # inventat).
        data = self._fetch_market(sport_key, "h2h,totals")
        if not isinstance(data, list):
            data = self._fetch_market(sport_key, "h2h")
        if not isinstance(data, list):
            if data is None: self._dead_keys.add(sport_key)
            self._cset(cache_key, {}); return {}

        # [ADAUGAT] btts — apel separat, best-effort, complet izolat: dacă
        # piața nu există pe planul curent, eșuează fără să afecteze h2h/
        # totals de mai sus. Potrivire pe ev["id"], stabil între apeluri
        # succesive pentru același sport_key (aceeași convenție ca ev_id la
        # h2h/totals).
        btts_data = self._fetch_market(sport_key, "btts")
        btts_by_id: dict[str, dict] = {}
        if isinstance(btts_data, list):
            for ev in btts_data:
                btts_by_id[ev.get("id", "")] = ev

        result: dict[str, dict] = {}
        for ev in data:
            home   = normalize_team_name(ev.get("home_team", ""))
            away   = normalize_team_name(ev.get("away_team", ""))
            ev_id  = ev.get("id", "")
            bh = bd = ba = 0.0; bk_name = ""
            over25 = under25 = 0.0
            for bk in ev.get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    key = mkt.get("key")
                    if key == "h2h":
                        om: dict[str, float] = {}
                        for o in mkt.get("outcomes", []):
                            om[normalize_team_name(o["name"])] = float(o.get("price", 0))
                        h = om.get(home, 0.0); d = om.get("Draw", 0.0); a = om.get(away, 0.0)
                        if h > bh: bh = h; bk_name = bk.get("title", "")
                        if d > bd: bd = d
                        if a > ba: ba = a
                    elif key == "totals":
                        # doar linia 2.5 — coincide cu markets-urile deja
                        # calculate de Monte Carlo (prob_over25/prob_under25)
                        for o in mkt.get("outcomes", []):
                            if float(o.get("point", -1) or -1) != 2.5:
                                continue
                            price = float(o.get("price", 0))
                            name  = (o.get("name") or "").lower()
                            if name == "over" and price > over25: over25 = price
                            elif name == "under" and price > under25: under25 = price

            btts_yes = btts_no = 0.0
            for bk in (btts_by_id.get(ev_id) or {}).get("bookmakers", []):
                for mkt in bk.get("markets", []):
                    if mkt.get("key") != "btts": continue
                    for o in mkt.get("outcomes", []):
                        price = float(o.get("price", 0))
                        name  = (o.get("name") or "").lower()
                        if name in ("yes", "gg") and price > btts_yes: btts_yes = price
                        elif name in ("no", "ng") and price > btts_no: btts_no = price

            if bh > 1.0:
                entry = {
                    "home": bh, "draw": bd, "away": ba,
                    "bookmaker": bk_name, "ev_id": ev_id,
                    "over25": over25, "under25": under25,
                    "btts_yes": btts_yes, "btts_no": btts_no,
                }
                result[f"{home}||{away}"] = entry
                result[ev_id]             = entry
        self._cset(cache_key, result); return result

    def _attach_odds(self, matches: list[dict]) -> list[dict]:
        league_odds: dict[str, dict] = {}
        for m in matches:
            if m.get("home_odds"): continue
            league    = m.get("league", "")
            sport_key = ODDS_SPORT_KEYS.get(league)
            ev_id     = m.get("_odds_api_id", "")
            if not sport_key or sport_key in self._dead_keys: continue
            if sport_key not in league_odds:
                league_odds[sport_key] = self._fetch_odds(sport_key)
            od = league_odds[sport_key]
            if not od: continue
            odds = od.get(ev_id)
            if not odds:
                h = normalize_team_name(m["home_team"])
                a = normalize_team_name(m["away_team"])
                odds = od.get(f"{h}||{a}")
            if odds:
                m["home_odds"]  = odds["home"]
                m["draw_odds"]  = odds["draw"]
                m["away_odds"]  = odds["away"]
                m["bookmaker"]  = odds.get("bookmaker", "")
                m["odds_source"] = f"The Odds API ({odds.get('bookmaker','')})"
                # [ADAUGAT] Piețe suplimentare — populate DOAR dacă găsite
                # (>1.0), altfel rămân neatinse => _special_value_bets() le
                # sare automat (bk_odds<=1.0), fără nicio valoare inventată.
                if odds.get("over25", 0.0) > 1.0:   m["over25_odds"]   = odds["over25"]
                if odds.get("under25", 0.0) > 1.0:  m["under25_odds"]  = odds["under25"]
                if odds.get("btts_yes", 0.0) > 1.0: m["btts_yes_odds"] = odds["btts_yes"]
                if odds.get("btts_no", 0.0) > 1.0:  m["btts_no_odds"]  = odds["btts_no"]
        return matches

    # ── Weather ───────────────────────────────────────────────────────────
    def get_weather(self, city: str, match_date: str | None = None) -> dict:
        base = {"temp_c": 15.0, "condition": "Clear", "wind_kph": 10.0,
                "precip_mm": 0.0, "humidity": 50, "xg_penalty": 0.0,
                "description": "☀️  Clear conditions — no xG penalty."}
        if not city or city in ("Unknown", ""): return base
        target = match_date or date.today().isoformat()
        today  = date.today().isoformat()
        try:
            if target <= today:
                url    = f"{WEATHER_URL}/current.json"
                params = {"key": self._key_manager.get_api_key_param("weatherapi"), "q": city, "aqi": "no"}
            else:
                url    = f"{WEATHER_URL}/forecast.json"
                params = {"key": self._key_manager.get_api_key_param("weatherapi"), "q": city, "dt": target, "aqi": "no"}
            # [REPARAT] Ruta prin _get() în loc de self._s.get() direct —
            # singurul apel din get_weather() care ocolea instrumentarea
            # provider_metrics (era numărat doar Odds/Injuries, niciodată
            # Weather). Comportament păstrat: orice eșec întoarce `base`.
            data = self._get(url, params=params, timeout=10)
            if data is None: return base
            if target <= today:
                cur       = data["current"]
                temp_c    = cur["temp_c"]; condition = cur["condition"]["text"]
                wind_kph  = cur["wind_kph"]; precip_mm = cur["precip_mm"]
                humidity  = cur["humidity"]
            else:
                day       = data["forecast"]["forecastday"][0]["day"]
                temp_c    = day["avgtemp_c"]; condition = day["condition"]["text"]
                wind_kph  = day["maxwind_kph"]; precip_mm = day["totalprecip_mm"]
                humidity  = day["avghumidity"]
            penalty = 0.0; notes = []; cl = condition.lower()
            for bc in ["heavy rain","torrential","blizzard","heavy snow",
                       "thunderstorm","sleet","freezing"]:
                if bc in cl: penalty += 0.08; notes.append("severe weather"); break
            else:
                if "rain" in cl or "drizzle" in cl: penalty += 0.04; notes.append("light rain")
                elif "snow" in cl: penalty += 0.06; notes.append("snow")
            if precip_mm > 15: penalty += 0.04; notes.append("heavy precip")
            elif precip_mm > 5: penalty += 0.02; notes.append("light precip")
            if wind_kph > 70: penalty += 0.04; notes.append("strong wind")
            elif wind_kph > 50: penalty += 0.02; notes.append("moderate wind")
            if temp_c < 0: penalty += 0.03; notes.append("freezing")
            elif temp_c > 38: penalty += 0.02; notes.append("extreme heat")
            penalty = min(penalty, 0.15)
            desc = (
                f"{'⚠️' if penalty > 0.06 else '🌧️'}  {condition} | "
                f"{', '.join(notes)} → xG -{penalty*100:.0f}%"
                if notes else
                f"☀️  {condition} | {temp_c}°C | No xG penalty."
            )
            return {"temp_c": temp_c, "condition": condition, "wind_kph": wind_kph,
                    "precip_mm": precip_mm, "humidity": humidity,
                    "xg_penalty": round(penalty, 3), "description": desc}
        except Exception as exc:
            logger.warning("[Weather] %s: %s", city, exc); return base

    # ── Orchestrator principal ────────────────────────────────────────────
    def get_matches_for_week(self, days_ahead: int = 7,
                             competitions: list[str] | None = None) -> list[dict]:
        today    = date.today()
        end_date = today + timedelta(days=days_ahead)
        d_from   = today.isoformat(); d_to = end_date.isoformat()
        cache_key = f"week_{d_from}_{days_ahead}_{','.join(sorted(competitions or []))}"
        cached = self._cget(cache_key)
        if cached is not None: return cached

        matches: list[dict] = []; seen_keys: set[str] = set()

        def _add(new_matches: list[dict]) -> None:
            for m in new_matches:
                mk = match_key(
                    m.get("home_team", "") or "",
                    m.get("away_team", "") or "",
                    m.get("kickoff_date", "") or "",
                )
                if mk not in seen_keys:
                    seen_keys.add(mk); matches.append(m)

        comps    = competitions or list(ODDS_SPORT_KEYS.keys())
        priority = ["World Cup 2026"] + [c for c in comps if c != "World Cup 2026"]

        # 1. Odds API events (cote + meciuri)
        for league in priority:
            sk = ODDS_SPORT_KEYS.get(league)
            if sk: _add(self._fetch_events_odds_api(sk, days_ahead))

        # 2. Free Live Football — sursă primară pentru meciuri
        for i in range(min(days_ahead, 7)):
            target = (today + timedelta(days=i)).isoformat()
            for league in comps:
                if league in FREE_LF_LEAGUE_IDS:
                    logger.info("[WeekLoop] FreeLF start: %s / %s", league, target)
                    _add(self._fetch_freelf_matches(target, league))
                    logger.info("[WeekLoop] FreeLF done:  %s / %s", league, target)

        # 3. football-data.org fallback
        fd_codes = [FD_COMPETITIONS[c] for c in comps if c in FD_COMPETITIONS] or None
        logger.info("[WeekLoop] football-data.org start")
        _add(self._fetch_matches_fd(d_from, d_to, fd_codes))
        logger.info("[WeekLoop] football-data.org done")

        # 4. ESPN fallback
        for i in range(min(days_ahead, 7)):
            target = (today + timedelta(days=i)).isoformat()
            for league in comps:
                if ESPN_LEAGUE_SLUGS.get(league):
                    logger.info("[WeekLoop] ESPN start: %s / %s", league, target)
                    _add(self._fetch_matches_espn(league, target))
                    logger.info("[WeekLoop] ESPN done:  %s / %s", league, target)

        # 5. TheSportsDB fallback — condiție PER LIGĂ (HOTFIX interimar,
        #    operațional, separat de ADR-034 — NU evoluție de arhitectură).
        #    ÎNAINTE: gate global `len(matches) < 5`, care bloca structural
        #    orice ligă apărută după ce alte ligi (World Cup + oricare
        #    altele) umpleau pragul global — exact BUG-014B, verificat live
        #    2026-07-18 (Romania SuperLiga nu ajungea niciodată la TSDB,
        #    deși avea 0 meciuri). Aceeași filozofie ca pasul 6
        #    (API-Football) de mai jos — condiție per ligă, nu globală.
        #
        #    TECH-DEBT-ADR034-004 (Issue #27): acest bloc TREBUIE ELIMINAT
        #    la PR7 (ADR-034), când Selection Engine preia complet selecția
        #    providerilor — nu doar lăsat inert. Referință explicită aici ca
        #    să nu devină permanent prin inerție (semnalat la review PR #26).
        for league in comps:
            lid = TSDB_LEAGUE_IDS.get(league)
            if not lid:
                continue
            if any(m.get("league") == league for m in matches):
                continue
            _add(self._fetch_matches_tsdb(lid, league))

        # 6. API-Football — fallback ultim, DOAR pentru ligile cu
        #    provider_ids["api_football"] setat in mappings.py (generic —
        #    orice liga noua completata acolo devine eligibila automat) SI
        #    doar daca liga respectiva inca nu are niciun meci gasit de
        #    providerii de mai sus. Conditie PER LIGA, nu globala (spre
        #    deosebire de gate-ul TSDB, len(matches) < 5, care e global si
        #    de-asta nu a acoperit niciodata Romania — vezi BUG-014B).
        for league in comps:
            if league not in API_FOOTBALL_LEAGUE_IDS:
                continue
            if any(m.get("league") == league for m in matches):
                continue
            logger.info("[WeekLoop] API-Football fallback start: %s", league)
            _add(self._fetch_matches_api_football(league, d_from, d_to))
            logger.info("[WeekLoop] API-Football fallback done: %s", league)

        # 7. Demo mode când nu există date
        if len(matches) < 3:
            _add(self._generate_demo_matches(comps))

        matches = [m for m in matches
                   if d_from <= (m.get("kickoff_date") or "9999") <= d_to]
        matches = self._attach_odds(matches)
        matches.sort(key=lambda m: m.get("kickoff_utc", ""))
        self._shadow_evaluate_selection_engine(comps, matches)
        self._cset(cache_key, matches); return matches

    def _shadow_evaluate_selection_engine(self, comps: list[str], matches: list[dict]) -> None:
        """[ADAUGAT] ADR-034 PR5 — efect secundar, STRICT observațional.
        Nu modifică niciodată `matches` (doar îl citește, deja finalizat) —
        nu poate influența valoarea de retur a get_matches_for_week(). Nu
        face nimic (return imediat) dacă
        selection_engine_shadow_enabled=False (implicit, North Star #3) —
        un singur boolean check, zero cost dincolo de el. Best-effort: orice
        eroare e prinsă aici, niciodată propagată (Regula #8, degradare
        grațioasă, consistent cu learning_core/challenger_shadow.py)."""
        try:
            import shadow_config
            if not shadow_config.is_enabled():
                return

            from provider_capabilities import DataType
            from provider_selector import recommend_provider
            from provider_source_resolver import determine_current_provider
            import shadow_recorder

            shadow_run_id = shadow_recorder.new_shadow_run_id()
            for league in comps:
                current_provider = determine_current_provider(league, matches)
                if current_provider is None:
                    continue  # nicio sursa reala (non-demo) pentru aceasta liga
                recommendation = recommend_provider(league, DataType.FIXTURES, current_provider)
                shadow_recorder.record_shadow_recommendation(recommendation, shadow_run_id)
        except Exception as exc:
            logger.debug("[SelectionEngineShadow] evaluare shadow eșuată: %s", exc)

    def get_matches_for_date(self, target_date: str) -> list[dict]:
        return [m for m in self.get_matches_for_week(days_ahead=7)
                if m.get("kickoff_date") == target_date]

    def clear_cache(self) -> None:
        self._mem.clear(); self._dead_keys.clear()
        self._freelf_exhausted = False
        logger.info("Cache cleared. FreeLF exhausted flag reset.")
