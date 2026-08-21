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
  PPL = Primeira Liga (Portugalia)
  DED = Eredivisie (Olanda)
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
    # [ADAUGAT 2026-08-04] Coduri VERIFICATE LIVE (workflow_dispatch
    # poc_new_leagues_verification.yml, run 30958350888) — aceleași coduri
    # deja folosite în mappings.FD_COMPETITIONS. Turcia/Croația rămân
    # excluse deliberat — confirmat live, absente din planul gratuit
    # football-data.org (/v4/competitions, lista completă).
    "Primeira Liga":    "PPL",
    "Eredivisie":       "DED",
}

# Sezoane disponibile (format football-data.org: YYYY)
# [REPARAT] Lipsea 2025 (sezonul 2025-26) - de aceea toate ligile europene se
# opreau la mai 2025 in match_history, gasit prin audit direct in Supabase.
# 2026 (sezonul 2026-27) nu are inca date - incepe in august.
SEASONS = [2021, 2022, 2023, 2024, 2025]

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

        # [FIX F4.5, 2026-08-21] Departajarea de la 11 metri era numarata ca
        # goluri. Pentru o tusa decisa la penalty-uri, football-data.org
        # raporteaza in `score.fullTime` suma (scor dupa prelungiri + suturile
        # de departajare), semnalata de `score.duration == "PENALTY_SHOOTOUT"`.
        # Codul citea `fullTime` neconditionat si nu se uita niciodata la
        # `duration`, deci scria acea suma ca scor al meciului.
        #
        # Caz real, descoperit in auditul F4 pe date live: Liverpool - Paris
        # Saint-Germain, 2025-03-11, Champions League, `fd_524100` ->
        # `actual_home_goals=1, actual_away_goals=5`. Meciul s-a terminat 0-1,
        # PSG a castigat 4-1 la penalty-uri: 0+1=1, 1+4=5. Aritmetica se
        # potriveste exact.
        #
        # Impact dincolo de scorul afisat: `actual_result` ramane corect
        # (castigatorul e acelasi), dar diferenta de goluri intra distorsionat
        # in multiplicatorul MOV al ELO (`sync/backfill_features._mov_multiplier`)
        # — goal_diff 4 in loc de 1 — deci coruperea se propaga in starea
        # derivata, nu ramane cosmetica.
        #
        # Ordinea de preferinta e cea a specificatiei providerului: `regularTime`
        # (90'), apoi `fullTime` cand nu exista departajare. NU se scade
        # `score.penalties` din `fullTime` — scaderea ar presupune ca `fullTime`
        # e mereu suma, ipoteza neverificata pe payload-uri reale; cand nu avem
        # o valoare de 90' explicita si stim ca a existat departajare, meciul e
        # sarit, iar starea ramane "necunoscut" in loc de aproximata (North Star
        # #8). Un meci sarit e recuperabil dintr-o alta sursa; unul scris gresit
        # contamineaza tacit ELO.
        score      = match.get("score", {})
        duration   = (score.get("duration") or "").upper()
        ft         = score.get("fullTime") or {}
        regular    = score.get("regularTime") or {}

        if duration == "PENALTY_SHOOTOUT":
            home_goals = regular.get("home")
            away_goals = regular.get("away")
            if home_goals is None or away_goals is None:
                logger.warning(
                    "[FD] Meci decis la penalty-uri fara `regularTime` explicit "
                    "(id=%s, %s - %s) — sarit, ca sa nu scriem departajarea ca "
                    "goluri (F4.5).",
                    match.get("id", "?"), home_team, away_team,
                )
                return None
        else:
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

        # [FIX Pasul 3, Master Repair Plan] season era parsat din payload-ul
        # real al providerului dar nu ajungea niciodata in dict-ul scris in
        # match_history (variabila locala neutilizata) - de aceea season
        # ramanea NULL pentru toate randurile football-data.org, desi
        # providerul il oferea. Format "YYYY-YYYY", direct din startDate/
        # endDate ale providerului (migratia 038) - nicio aproximare
        # calendaristica proprie (interzis explicit, season_cleanup.py).
        season_obj   = match.get("season") or {}
        start_year   = (season_obj.get("startDate") or "")[:4]
        end_year     = (season_obj.get("endDate") or "")[:4]
        if start_year and end_year and start_year != end_year:
            season = f"{start_year}-{end_year}"
        elif start_year:
            season = start_year
        else:
            season = None

        fixture_id = f"fd_{match_id}"

        # Statistici suplimentare dacă sunt disponibile
        home_xg = None
        away_xg = None

        # [ELIMINAT Pasul 3, Master Repair Plan] football-data.org include
        # uneori match.get("odds") (homeWin/draw/awayWin), dar acest modul nu
        # are voie sa le scrie nicaieri: singura tabela reala de cote e
        # odds_history, alimentata EXCLUSIV din The Odds API prin
        # oracle_api._attach_odds() -> OddsPersistenceService (contract
        # Frozen, ADR-005/006 sectiunea 5 - "evita dubla sursa de adevar").
        # match_history nu are nicio coloana odds_*. Codul vechi parsa
        # match["odds"] in 3 variabile locale niciodata incluse in dict-ul
        # returnat - exact clasa de bug gasita la season (fix anterior in
        # acest fisier) - eliminat complet, nu doar lasat neutilizat.

        # [FIX 2026-07-13 — writer destructiv] NU mai trimitem home_elo/away_elo
        # explicit None: la upsert pe fixture_id existent, None RESCRIA cu NULL
        # un ELO deja calculat de backfill (demonstrat: 1.059 rânduri re-anulate
        # la sync-ul din 06:28, în timpul rulării de backfill). O cheie absentă
        # lasă coloana neatinsă la update și NULL implicit la insert — identic
        # pentru rânduri noi, non-destructiv pentru cele existente.
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
            "used_for_training": True,
            "season":            season,
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
