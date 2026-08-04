"""
================================================================================
FOOTBALL ORACLE v4.0 — OpenFootball Data Source
================================================================================
Module: sync/sources/openfootball.py

Descarcă rezultate istorice din repo-ul public openfootball/football.json
pe GitHub, format JSON, parsate și transformate în dicționare compatibile
cu schema match_history din Supabase.

Surse disponibile (VERIFICATE LIVE 2026-08-04, după ce URL-urile vechi au
început să dea 404 — vezi nota [FIX 2026-08-04] de mai jos):
  - Premier League (en.1)
  - La Liga (es.1)
  - Bundesliga (de.1)
  - Serie A (it.1)
  - Ligue 1 (fr.1)
  - Champions League (uefa.cl)
  - Primeira Liga (pt.1)
  - Eredivisie (nl.1)
  - Super Lig (tr.1)

NU disponibile în acest dataset (verificat live, HTTP 404 pe fișierul
real, nu presupus) — Romania SuperLiga, HNL (Croația). Pentru HNL,
Flashscore Foundation Data Layer (`FLASHSCORE_TRACKED_COMPETITIONS`)
rămâne sursa reală, deja activă.

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

# URL raw GitHub pentru openfootball/football.json (branch master, obligatoriu
# în path pentru raw.githubusercontent.com).
GITHUB_RAW = "https://raw.githubusercontent.com/openfootball/football.json/master"

# Mapare ligă Football Oracle → cod fișier openfootball. [FIX 2026-08-04]
# Repo-ul sursă și-a schimbat COMPLET layout-ul de fișiere ȘI formatul JSON
# de la implementarea inițială — confirmat live, nu presupus:
#   - vechi: {season}/{path}/{file} (ex. "2024-25/en/1-premierleague.json"),
#     JSON {"name":..., "rounds":[{"matches":[...]}]}  — TOATE dădeau 404.
#   - nou:   {season}/{code}.json (ex. "2024-25/en.1.json"),
#     JSON {"name":..., "matches":[...]} flat, fără "rounds".
# Fiecare "code" de mai jos verificat live (HTTP 200 + "name" plauzibil).
LEAGUE_PATHS: dict[str, dict] = {
    "Premier League": {
        "code": "en.1",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
    "La Liga": {
        "code": "es.1",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
    "Bundesliga": {
        "code": "de.1",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
    "Serie A": {
        "code": "it.1",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
    "Ligue 1": {
        "code": "fr.1",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
    "Champions League": {
        "code": "uefa.cl",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
    # [ADAUGAT 2026-08-04] 3 ligi noi — cod verificat live. Romania SuperLiga
    # (fostă aici, "ro") și HNL NU sunt în acest dataset — confirmat live,
    # HTTP 404 pe fișierul real, niciun cod ghicit alternativ presupus.
    "Primeira Liga": {
        "code": "pt.1",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
    "Eredivisie": {
        "code": "nl.1",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
    "Super Lig": {
        "code": "tr.1",
        "seasons": ["2021-22", "2022-23", "2023-24", "2024-25"],
    },
}


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

    # [FIX 2026-08-04] URL unic, verificat live — {season}/{code}.json direct
    # sub root-ul sezonului, fără subfolder de țară (fostul path/file nested
    # nu mai există în repo, dădea 404 pentru toate cele 6 ligi vechi).
    code = config["code"]
    url = f"{GITHUB_RAW}/{season}/{code}.json"
    data = _fetch_url(url)

    if data is None:
        logger.warning(
            "[OpenFootball] Nu am găsit date pentru %s %s", league, season
        )
        return []

    # [FIX 2026-08-04] Formatul REAL curent (verificat live): {"name":...,
    # "matches":[...]} — flat, fără wrapper "rounds". Fallback pe formatul
    # vechi păstrat defensiv, nu presupus necesar azi.
    matches_raw: list[dict] = []
    if isinstance(data, dict):
        matches_raw = data.get("matches", [])
        if not matches_raw:
            for round_data in data.get("rounds", []):
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
