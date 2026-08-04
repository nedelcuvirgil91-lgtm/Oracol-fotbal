"""
================================================================================
FOOTBALL ORACLE — Sync Pre-Match Odds (Flashscore, flux nou separat, ADR-043)
================================================================================
Module: sync/sync_pre_match_odds.py

Punctul de intrare Sync Layer pentru `providers/flashscore/pre_match_odds.py`
— fluxul separat, dedicat, care descoperă meciuri VIITOARE (fereastra
`days_ahead`) și le atașează cote Flashscore, ca fallback pentru
`odds_fallback_flashscore` (ADR-043). Complet izolat de `sync/run_night.py`/
`sync/run_live.py` (rularea automată existentă, exclusiv meciuri
finalizate) — NEcablat încă în orchestrarea zilnică, deliberat, cât timp
scrierea rămâne în etapa de verificare live (vezi docstring modul
`pre_match_odds.py`).

Descoperirea meciurilor din sursa primară (`oracle_api.
FootballOracleAPI.get_matches_for_week`) — la fel ca `sync_weather_
forecast.py`/`sync_team_health.py` — folosită DOAR pentru rezolvarea
`fixture_id` cross-provider (`pre_match_odds.resolve_fixture_id()`),
niciodată pentru descoperirea meciurilor Flashscore în sine.

Rulare:
    python -m sync.sync_pre_match_odds --leagues "Europa League" --limit-per-league 3
    (sau .github/workflows/sync_pre_match_odds.yml, workflow_dispatch manual)
================================================================================
"""
from __future__ import annotations

import argparse
import logging

from providers.flashscore.pre_match_odds import sync_week_odds_from_flashscore

logger = logging.getLogger("FootballOracle.Sync.PreMatchOdds")


def _fetch_live_matches(days_ahead: int) -> list[dict]:
    """Best-effort — folosit DOAR pentru rezolvarea fixture_id (vezi
    docstring modul). O eroare aici nu oprește fluxul, doar înseamnă că
    fiecare meci capătă un fixture_id propriu (`resolve_fixture_id()`,
    degradare deja specificată, niciodată o excepție netratată)."""
    try:
        from oracle_api import FootballOracleAPI
        return FootballOracleAPI().get_matches_for_week(days_ahead=days_ahead)
    except Exception as exc:
        logger.warning("[PreMatchOdds] get_matches_for_week() eșuat, fixture_id propriu pt. toate: %s", exc)
        return []


def run(
    leagues: list[str] | None = None, days_ahead: int = 7, limit_per_league: int | None = None,
) -> dict:
    live_matches = _fetch_live_matches(days_ahead)
    logger.info("[PreMatchOdds] %d meciuri din sursa primară (rezolvare fixture_id)", len(live_matches))
    report = sync_week_odds_from_flashscore(
        leagues=leagues, days_ahead=days_ahead,
        limit_per_league=limit_per_league, live_matches=live_matches,
    )
    logger.info("[PreMatchOdds] Raport: %s", report)
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Sincronizare cote Flashscore pentru meciuri viitoare (ADR-043)")
    parser.add_argument("--leagues", type=str, default=None,
                         help="Ligi separate prin virgulă (implicit: toate din FLASHSCORE_TRACKED_COMPETITIONS)")
    parser.add_argument("--days-ahead", type=int, default=7)
    parser.add_argument("--limit-per-league", type=int, default=None)
    args = parser.parse_args()

    leagues_arg = [lg.strip() for lg in args.leagues.split(",")] if args.leagues else None
    run(leagues=leagues_arg, days_ahead=args.days_ahead, limit_per_league=args.limit_per_league)
