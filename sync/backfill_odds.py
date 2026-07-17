"""
================================================================================
FOOTBALL ORACLE — Backfill Odds CLI
================================================================================
Module: sync/backfill_odds.py

Punct de intrare pentru BackfillOddsService (services/odds_backfill_service.py).
Singurul loc din tot lanțul unde apare o valoare specifică unei ligi este
dicționarul de configurație de mai jos — o ligă nouă înseamnă o linie nouă
aici, zero cod nou.

Rulare:
  python sync/backfill_odds.py --league "Premier League" --dry-run
  python sync/backfill_odds.py --league "Premier League"
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.BackfillOddsCLI")

# Configurație — league canonic Football Oracle -> cod division football-data.co.uk.
# Etapa 1 (PoC): doar Premier League. Etapele următoare adaugă rânduri aici,
# nu cod nou (Sprint: Odds Infrastructure, task #22).
LEAGUE_DIVISION_CODES: dict[str, str] = {
    "Premier League": "E0",
}


def run_backfill_for_league(league: str, dry_run: bool = False):
    from services.odds_backfill_service import BackfillOddsService
    from sync.sources.football_data_co_uk import fetch_football_data_co_uk_rows

    division = LEAGUE_DIVISION_CODES.get(league)
    if division is None:
        raise ValueError(
            f"Liga '{league}' nu are un cod de division configurat în "
            f"LEAGUE_DIVISION_CODES — adaugă o intrare, nu cod nou."
        )

    service = BackfillOddsService(
        provider="football-data.co.uk",
        division=division,
        season=None,
        importer=fetch_football_data_co_uk_rows,
        league=league,
    )
    return service.run(dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(description="Football Oracle — Backfill Odds")
    parser.add_argument("--league", type=str, required=True,
                         choices=list(LEAGUE_DIVISION_CODES.keys()),
                         help="Liga de procesat (din LEAGUE_DIVISION_CODES)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Simulare — fără scriere în Supabase")
    args = parser.parse_args()

    metrics = run_backfill_for_league(args.league, dry_run=args.dry_run)

    print("═" * 60)
    print(f"  BACKFILL ODDS — {args.league} (dry_run={args.dry_run})")
    print("═" * 60)
    print(f"  Meciuri unice în sursă : {metrics.source_matches_found}")
    print(f"  Rânduri (meci,bookmaker): {metrics.source_rows_found}")
    print(f"  Potrivite               : {metrics.matched}")
    print(f"  Rata de matching        : {metrics.match_rate_pct}%")
    print(f"  Fără potrivire          : {metrics.rejected_no_match}")
    print(f"  Ambigue                 : {metrics.rejected_ambiguous_match}")
    print(f"  Scor neconcordant       : {metrics.rejected_score_mismatch}")
    print(f"  Scrise cu succes        : {metrics.written_ok}")
    print(f"  Erori de scriere        : {metrics.write_errors}")
    print("═" * 60)

    if metrics.write_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
