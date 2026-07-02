"""
================================================================================
FOOTBALL ORACLE v4.0 — ELO Calculator
================================================================================
Module: sync/calculate_elo.py

Calculează ratinguri ELO pentru toate echipele din match_history,
bazat pe rezultatele reale stocate în Supabase.

Formula ELO standard cu ajustări pentru fotbal:
  - K-factor variabil (mai mare pentru echipe cu puține meciuri)
  - Home advantage factor (+50 ELO temporar pentru echipa gazdă)
  - Rating inițial: 1500 pentru toate echipele noi

Rezultatele se salvează în tabela elo_ratings din Supabase.
================================================================================
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from database.queries import (
    get_matches_by_league,
    upsert_elo_ratings,
)

logger = logging.getLogger("FootballOracle.Sync.ELO")

# Parametri ELO
INITIAL_ELO    = 1500
HOME_ADVANTAGE = 50     # ELO temporar adăugat echipei gazdă
K_FACTOR_BASE  = 32     # K-factor standard
K_FACTOR_NEW   = 40     # K mai mare pentru echipe cu < 10 meciuri

LEAGUES = [
    "Premier League",
    "La Liga",
    "Serie A",
    "Bundesliga",
    "Ligue 1",
    "Champions League",
    "Romania SuperLiga",
]


def _expected_score(rating_a: float, rating_b: float) -> float:
    """Probabilitatea așteptată de câștig pentru echipa A."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _k_factor(matches_played: int) -> float:
    """K-factor variabil — mai mare pentru echipe cu experiență redusă."""
    if matches_played < 10:
        return K_FACTOR_NEW
    return K_FACTOR_BASE


def calculate_elo_for_league(
    league: str, matches: list[dict]
) -> dict[str, int]:
    """
    Calculează ratinguri ELO pentru toate echipele dintr-o ligă,
    procesând meciurile în ordine cronologică.

    Returnează dict {team_name: elo_rating}.
    """
    if not matches:
        return {}

    # Sortăm meciurile cronologic
    sorted_matches = sorted(
        matches,
        key=lambda m: m.get("kickoff_date", "") or ""
    )

    ratings:       dict[str, float] = {}
    match_counts:  dict[str, int]   = {}

    def _get_rating(team: str) -> float:
        return ratings.get(team, float(INITIAL_ELO))

    def _get_count(team: str) -> int:
        return match_counts.get(team, 0)

    for match in sorted_matches:
        home = match.get("home_team", "")
        away = match.get("away_team", "")
        result = match.get("actual_result", "")

        if not home or not away or not result:
            continue

        r_home = _get_rating(home) + HOME_ADVANTAGE
        r_away = _get_rating(away)

        exp_home = _expected_score(r_home, r_away)
        exp_away = 1.0 - exp_home

        # Scor real (1 = victorie, 0.5 = egal, 0 = înfrângere)
        if result == "H":
            score_home, score_away = 1.0, 0.0
        elif result == "A":
            score_home, score_away = 0.0, 1.0
        else:  # D
            score_home, score_away = 0.5, 0.5

        k_home = _k_factor(_get_count(home))
        k_away = _k_factor(_get_count(away))

        new_home = _get_rating(home) + k_home * (score_home - exp_home)
        new_away = _get_rating(away) + k_away * (score_away - exp_away)

        ratings[home] = new_home
        ratings[away] = new_away
        match_counts[home] = _get_count(home) + 1
        match_counts[away] = _get_count(away) + 1

    # Rotunjim la int
    return {team: round(elo) for team, elo in ratings.items()}


def recalculate_all_elo(leagues: list[str] | None = None) -> int:
    """
    Recalculează ELO pentru toate ligile și salvează în Supabase.
    Returnează numărul de echipe actualizate.
    """
    target_leagues = leagues or LEAGUES
    total_updated  = 0
    now            = datetime.now(timezone.utc).isoformat()

    for league in target_leagues:
        try:
            # Luăm toate meciurile cu rezultat din ligă
            matches = get_matches_by_league(league, limit=2000)

            if not matches:
                logger.info("[ELO] %s: nicio dată disponibilă", league)
                continue

            elo_ratings = calculate_elo_for_league(league, matches)

            if not elo_ratings:
                continue

            # Pregătim rândurile pentru Supabase
            rows = [
                {
                    "team":       team,
                    "league":     league,
                    "elo":        elo,
                    "updated_at": now,
                }
                for team, elo in elo_ratings.items()
            ]

            ok, errors = upsert_elo_ratings(rows)
            total_updated += ok

            logger.info(
                "[ELO] %s: %d echipe actualizate (top: %s)",
                league,
                ok,
                sorted(elo_ratings.items(), key=lambda x: x[1], reverse=True)[:3],
            )

        except Exception as exc:
            logger.error("[ELO] Eroare pentru %s: %s", league, exc)

    logger.info("[ELO] Total echipe actualizate: %d", total_updated)
    return total_updated
