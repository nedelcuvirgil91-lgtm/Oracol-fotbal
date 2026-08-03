"""
================================================================================
FOOTBALL ORACLE v4.0 — OpenFootball Data Source
================================================================================
Module: sync/sources/openfootball.py

Descarcă rezultate istorice din repo-ul public openfootball/football pe GitHub.
Fișierele sunt în format text simplu (.txt), parsate și transformate în
dicționare compatibile cu schema match_history din Supabase.

Surse disponibile:
  - Premier League (eng.1)
  - La Liga (es.1)
  - Bundesliga (de.1)
  - Serie A (it.1)
  - Ligue 1 (fr.1)
  - Champions League (uefa.cl)

Rate limit: GitHub raw content nu are rate limit semnificativ pentru
fișiere publice — putem descărca toate sezoanele fără restricții.
================================================================================
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Iterator

import requests

logger = logging.getLogger("FootballOracle.Sync.OpenFootball")

# URL-uri raw GitHub pentru openfootball/football
GITHUB_RAW = "https://raw.githubusercontent.com/openfootball/football.json/master"

# Mapare ligă Football Oracle → path openfootball
LEAGUE_PATHS: dict[str, dict] = {
    "Premier League": {
        "path": "en",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        "file": "1-premierleague.json",
    },
    "La Liga": {
        "path": "es",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        "file": "1-liga.json",
    },
    "Bundesliga": {
        "path": "de",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        "file": "1-bundesliga.json",
    },
    "Serie A": {
        "path": "it",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        "file": "1-calcio.json",
    },
    "Ligue 1": {
        "path": "fr",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        "file": "1-ligue1.json",
    },
    "Champions League": {
        "path": "uefa.cl",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        "file": "cl.json",
    },
    "Romania SuperLiga": {
        "path": "ro",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
        "file": "1-liga.json",
    },
}

# Fallback: URL alternativ folosind openfootball/football (format diferit)
GITHUB_RAW_ALT = "https://raw.githubusercontent.com/openfootball/football.json"


def _fetch_url(url: str, retries: int = 3) -> dict | list | None:
    """Descarcă un URL JSON cu retry automat."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=15)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 404:
                logger.debug("[OpenFootball] 404: %s", url)
                return None
            logger.warning(
                "[OpenFootball] HTTP %d pentru %s (attempt %d)",
                resp.status_code, url, attempt + 1
            )
        except Exception as exc:
            logger.warning("[OpenFootball] Eroare fetch %s: %s", url, exc)
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    return None


def _parse_match_json(
    match: dict, league: str, season: str
) -> dict | None:
    """
    Transformă un meci din formatul JSON openfootball în
    formatul match_history pentru Supabase.
    """
    try:
        home = match.get("team1", {})
        away = match.get("team2", {})
        score = match.get("score", {})

        home_name = home.get("name", "") if isinstance(home, dict) else str(home)
        away_name = away.get("name", "") if isinstance(away, dict) else str(away)

        if not home_name or not away_name:
            return None

        # Scor — poate fi None dacă meciul nu s-a jucat încă
        ft = score.get("ft") if isinstance(score, dict) else None
        if not ft or len(ft) < 2:
            return None  # meci fără rezultat final — sărim

        home_goals = int(ft[0])
        away_goals = int(ft[1])

        actual_result = (
            "H" if home_goals > away_goals
            else "A" if home_goals < away_goals
            else "D"
        )

        # Data meciului
        date_str = match.get("date", "")
        kickoff_date = date_str[:10] if date_str else ""

        # fixture_id unic — combinație sursă + ligă + sezon + echipe + dată
        fixture_id = (
            f"openfootball_{league.lower().replace(' ', '_')}"
            f"_{season}_{home_name.lower().replace(' ', '_')}"
            f"_vs_{away_name.lower().replace(' ', '_')}"
            f"_{kickoff_date}"
        )
        # Normalizăm fixture_id — eliminăm caractere speciale
        fixture_id = re.sub(r"[^a-z0-9_]", "", fixture_id)[:120]

        # [FIX 2026-07-13 — writer destructiv] home_elo/away_elo explicit None
        # eliminate din payload — aceeași clasă de defect ca în football_data.py:
        # la upsert pe fixture_id existent, None rescria cu NULL un ELO deja
        # calculat. Cheile absente lasă coloanele neatinse (update) / NULL
        # implicit (insert) — feature-urile rămân de completat incremental.
        #
        # [FIX Pasul 3, Master Repair Plan] `season` era deja cunoscut aici
        # (parametru din LEAGUE_PATHS[...]["seasons"], folosit la construirea
        # fixture_id-ului, linia ~141) dar nu ajungea niciodată în dict-ul
        # scris în match_history — aceeași clasă de bug găsită și reparată
        # în football_data.py (season parsat/cunoscut, dar aruncat înainte de
        # persistare). Text liber, exact cum e primit (ex. "2021-22") —
        # migrația 038 nu cere un format anume, doar "cum îl oferă sursa".
        # Fără backfill pentru rândurile existente: 0 rânduri openfootball_*
        # în producție azi (verificat live, 2026-08-03) — nimic de reparat
        # retroactiv, doar scrierile viitoare beneficiază de fix.
        return {
            "fixture_id":        fixture_id,
            "home_team":         home_name,
            "away_team":         away_name,
            "league":            league,
            "kickoff_date":      kickoff_date,
            "actual_home_goals": home_goals,
            "actual_away_goals": away_goals,
            "actual_result":     actual_result,
            "home_xg_pred":      None,
            "away_xg_pred":      None,
            "used_for_training": True,
            "season":            season,
        }
    except Exception as exc:
        logger.debug("[OpenFootball] Parse error: %s — %s", match, exc)
        return None


def fetch_league_season(
    league: str, season: str
) -> list[dict]:
    """
    Descarcă toate meciurile dintr-o ligă și un sezon specific.
    Returnează lista de dicționare compatibile cu match_history.
    """
    config = LEAGUE_PATHS.get(league)
    if not config:
        logger.warning("[OpenFootball] Ligă necunoscută: %s", league)
        return []

    # Construim URL-ul pentru sezonul respectiv
    path = config["path"]
    file = config["file"]

    # Încearcă formatul principal
    url = f"{GITHUB_RAW_ALT}/{season}/{path}/{file}"
    data = _fetch_url(url)

    # Fallback — format alternativ de URL
    if data is None:
        url_alt = f"{GITHUB_RAW_ALT}/master/{season}/{path}/{file}"
        data = _fetch_url(url_alt)

    if data is None:
        logger.warning(
            "[OpenFootball] Nu am găsit date pentru %s %s", league, season
        )
        return []

    # Parseăm meciurile
    matches_raw: list[dict] = []

    # Formatul JSON openfootball: {"name": "...", "rounds": [{"matches": [...]}]}
    if isinstance(data, dict):
        rounds = data.get("rounds", [])
        for round_data in rounds:
            matches_raw.extend(round_data.get("matches", []))
    elif isinstance(data, list):
        matches_raw = data

    results: list[dict] = []
    for match in matches_raw:
        parsed = _parse_match_json(match, league, season)
        if parsed:
            results.append(parsed)

    logger.info(
        "[OpenFootball] %s %s: %d meciuri găsite, %d cu rezultat",
        league, season, len(matches_raw), len(results)
    )
    return results


def fetch_all_leagues(
    leagues: list[str] | None = None,
    seasons: list[str] | None = None,
) -> Iterator[tuple[str, str, list[dict]]]:
    """
    Generator care descarcă date pentru toate ligile și sezoanele specificate.
    Yield: (league_name, season, matches_list)

    Folosit de sync_matches.py ca:
        for league, season, matches in fetch_all_leagues():
            ...
    """
    target_leagues = leagues or list(LEAGUE_PATHS.keys())

    for league in target_leagues:
        config = LEAGUE_PATHS.get(league, {})
        target_seasons = seasons or config.get("seasons", [])

        for season in target_seasons:
            matches = fetch_league_season(league, season)
            yield league, season, matches
            # Pauză mică între cereri ca să nu suprasolicităm GitHub
            time.sleep(0.5)


def get_available_seasons(league: str) -> list[str]:
    """Returnează lista de sezoane disponibile pentru o ligă."""
    config = LEAGUE_PATHS.get(league, {})
    return config.get("seasons", [])
