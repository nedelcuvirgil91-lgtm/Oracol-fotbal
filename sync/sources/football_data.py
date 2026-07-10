"""
================================================================================
FOOTBALL ORACLE v4.0 — Football-Data.org Source
================================================================================
Module: sync/sources/football_data.py

Descarcă rezultate și statistici din football-data.org, folosind cheia
gestionată centralizat în key_manager.py (provider "footballdata").

Rate limit: 10 requests/minut pe planul gratuit.
Scriptul respectă automat acest limit cu pauze între cereri.

Endpoint-uri folosite:
  - /v4/competitions/{code}/matches — toate meciurile unui sezon
  - /v4/competitions/{code}/standings — clasamente

Competiții disponibile pe plan gratuit:
  PL  = Premier League
  PD  = La Liga
  SA  = Serie A
  BL1 = Bundesliga
  FL1 = Ligue 1
  CL  = Champions League
================================================================================
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Iterator

import requests

from key_manager import get_key_manager

logger = logging.getLogger("FootballOracle.Sync.FootballData")

FD_BASE_URL = "https://api.football-data.org/v4"
# [ELIMINAT] FD_API_KEY hardcodat - migrat in key_manager.py (provider "footballdata")

# Mapare ligă Football Oracle → cod competition football-data.org
COMPETITION_CODES: dict[str, str] = {
    "Premier League":   "PL",
    "La Liga":          "PD",
    "Serie A":          "SA",
    "Bundesliga":       "BL1",
    "Ligue 1":          "FL1",
    "Champions League": "CL",
}

# Sezoane disponibile (format football-data.org: YYYY)
SEASONS = [2021, 2022, 2023, 2024]

# Rate limit: 10 requests/minut → 6 secunde între cereri
REQUEST_INTERVAL = 6.1

_last_request_time: float = 0.0


def _rate_limited_get(url: str, params: dict | None = None) -> dict | None:
    """GET cu respectarea rate limit-ului de 10 req/min."""
    global _last_request_time

    # Așteptăm dacă e nevoie
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)

    try:
        resp = requests.get(
            url,
            headers=get_key_manager().get_headers("footballdata") or {},
            params=params or {},
            timeout=15,
        )
        _last_request_time = time.time()

        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            logger.warning("[FD] Rate limit atins — aștept 60s")
            time.sleep(60)
            return None
        if resp.status_code == 403:
            logger.warning("[FD] Acces interzis (plan gratuit?) pentru %s", url)
            return None
        if resp.status_code == 404:
            logger.debug("[FD] 404: %s", url)
            return None

        logger.warning("[FD] HTTP %d pentru %s", resp.status_code, url)
        return None

    except Exception as exc:
        logger.error("[FD] Eroare fetch %s: %s", url, exc)
        _last_request_time = time.time()
        return None


def _parse_match(match: dict, league: str) -> dict | None:
    """
    Transformă un meci din formatul football-data.org în
    formatul match_history pentru Supabase.
    """
    try:
        status = match.get("status", "")
        if status not in ("FINISHED",):
            return None  # Doar meciuri terminate

        home_team = (match.get("homeTeam") or {}).get("name", "")
        away_team = (match.get("awayTeam") or {}).get("name", "")
        if not home_team or not away_team:
            return None

        score = match.get("score", {})
        ft    = score.get("fullTime", {})
        home_goals = ft.get("home")
        away_goals = ft.get("away")

        if home_goals is None or away_goals is None:
            return None

        home_goals = int(home_goals)
        away_goals = int(away_goals)

        actual_result = (
            "H" if home_goals > away_goals
            else "A" if home_goals < away_goals
            else "D"
        )

        utc_date  = match.get("utcDate", "")
        kick_date = utc_date[:10] if utc_date else ""
        match_id  = match.get("id", "")
        season    = (match.get("season") or {}).get("startDate", "")[:4]

        fixture_id = f"fd_{match_id}"

        # Statistici suplimentare dacă sunt disponibile
        home_xg = None
        away_xg = None
        odds_home = odds_draw = odds_away = None

        # football-data.org include odds în unele răspunsuri
        odds = match.get("odds", {})
        if odds:
            odds_home = odds.get("homeWin")
            odds_draw = odds.get("draw")
            odds_away = odds.get("awayWin")

        return {
            "fixture_id":        fixture_id,
            "home_team":         home_team,
            "away_team":         away_team,
            "league":            league,
            "kickoff_date":      kick_date,
            "actual_home_goals": home_goals,
            "actual_away_goals": away_goals,
            "actual_result":     actual_result,
            "home_xg_pred":      home_xg,
            "away_xg_pred":      away_xg,
            "home_elo":          None,
            "away_elo":          None,
            "used_for_training": True,
        }
    except Exception as exc:
        logger.debug("[FD] Parse error: %s", exc)
        return None


def fetch_competition_season(
    league: str, season: int
) -> list[dict]:
    """
    Descarcă toate meciurile dintr-o competiție și un sezon.
    season: ex. 2023 (înseamnă sezonul 2023-24)
    """
    code = COMPETITION_CODES.get(league)
    if not code:
        logger.warning("[FD] Ligă necunoscută: %s", league)
        return []

    url  = f"{FD_BASE_URL}/competitions/{code}/matches"
    data = _rate_limited_get(url, params={"season": season, "status": "FINISHED"})

    if not data:
        return []

    matches_raw = data.get("matches", [])
    results: list[dict] = []

    for match in matches_raw:
        parsed = _parse_match(match, league)
        if parsed:
            results.append(parsed)

    logger.info(
        "[FD] %s %d: %d meciuri găsite, %d cu rezultat",
        league, season, len(matches_raw), len(results)
    )
    return results


def fetch_all_leagues(
    leagues: list[str] | None = None,
    seasons: list[int] | None = None,
) -> Iterator[tuple[str, int, list[dict]]]:
    """
    Generator care descarcă date pentru toate ligile și sezoanele.
    Yield: (league_name, season, matches_list)
    """
    target_leagues  = leagues  or list(COMPETITION_CODES.keys())
    target_seasons  = seasons  or SEASONS

    for league in target_leagues:
        for season in target_seasons:
            matches = fetch_competition_season(league, season)
            yield league, season, matches


def fetch_standings(league: str, season: int) -> list[dict] | None:
    """
    Descarcă clasamentul pentru o ligă și sezon.
    Returnează lista de intrări din standings sau None.
    """
    code = COMPETITION_CODES.get(league)
    if not code:
        return None

    url  = f"{FD_BASE_URL}/competitions/{code}/standings"
    data = _rate_limited_get(url, params={"season": season})

    if not data:
        return None

    standings = []
    for grp in data.get("standings", []):
        if grp.get("type") == "TOTAL":
            for entry in grp.get("table", []):
                team = (entry.get("team") or {}).get("name", "")
                if not team:
                    continue
                standings.append({
                    "team":            team,
                    "league":          league,
                    "season":          str(season),
                    "position":        entry.get("position"),
                    "points":          entry.get("points"),
                    "played":          entry.get("playedGames"),
                    "wins":            entry.get("won"),
                    "draws":           entry.get("draw"),
                    "losses":          entry.get("lost"),
                    "goals_for":       entry.get("goalsFor"),
                    "goals_against":   entry.get("goalsAgainst"),
                    "goal_difference": entry.get("goalDifference"),
                    "form":            entry.get("form", ""),
                })
    return standings if standings else None
