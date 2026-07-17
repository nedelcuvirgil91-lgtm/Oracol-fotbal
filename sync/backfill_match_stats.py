"""
================================================================================
FOOTBALL ORACLE — Backfill Match Stats CLI
================================================================================
Module: sync/backfill_match_stats.py

Punct de intrare pentru MatchStatsBackfillService
(services/match_stats_backfill_service.py). Aceleași două locuri variabile ca
la Odds: liga (LEAGUE_DIVISION_CODES) și grupul de coloane (STAT_GROUPS) — o
statistică nouă înseamnă o intrare nouă în STAT_GROUPS, zero cod nou.

Romania SuperLiga exclusă din LEAGUE_DIVISION_CODES — sursa are 0%
completitudine pentru orice statistică de meci acolo (demonstrat,
docs/05_DATA_AUDIT/DATASET_CAPABILITY_AUDIT_2026-07-13.md §3). Championship
exclus — match_history nu are azi rânduri cu league="Championship" (doar
codul brut "E1"), deci nu există țintă vie de backfill.

Rulare:
  python sync/backfill_match_stats.py --league "Premier League" --stats shots --dry-run
  python sync/backfill_match_stats.py --league "Premier League" --stats shots
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
logger = logging.getLogger("FootballOracle.BackfillMatchStatsCLI")

LEAGUE_DIVISION_CODES: dict[str, str] = {
    "Premier League": "E0",
    "La Liga": "SP1",
    "Serie A": "I1",
    "Bundesliga": "D1",
    "Ligue 1": "F1",
}

# Task 1: shots. Task 2 (automat, aceeași infrastructură): corners/fouls/
# cartonașe/HT — adăugate ca grup nou, nu ca schimbare de cod.
STAT_GROUPS: dict[str, list[str]] = {
    "shots": ["home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target"],
    "match_events": [
        "home_fouls", "away_fouls", "home_corners", "away_corners",
        "home_yellow_cards", "away_yellow_cards", "home_red_cards", "away_red_cards",
        "home_ht_goals", "away_ht_goals",
    ],
}


def run_backfill_for_league(league: str, stats: str, dry_run: bool = False):
    from services.match_stats_backfill_service import MatchStatsBackfillService
    from sync.sources.football_data_co_uk import fetch_football_data_co_uk_match_stats

    division = LEAGUE_DIVISION_CODES.get(league)
    if division is None:
        raise ValueError(
            f"Liga '{league}' nu are un cod de division configurat în "
            f"LEAGUE_DIVISION_CODES — adaugă o intrare, nu cod nou."
        )
    columns = STAT_GROUPS.get(stats)
    if columns is None:
        raise ValueError(f"Grup de statistici necunoscut: '{stats}' — vezi STAT_GROUPS.")

    service = MatchStatsBackfillService(
        provider="football-data.co.uk",
        division=division,
        season=None,
        importer=fetch_football_data_co_uk_match_stats,
        league=league,
        columns=columns,
    )
    return service.run(dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(description="Football Oracle — Backfill Match Stats")
    parser.add_argument("--league", type=str, required=True,
                         choices=list(LEAGUE_DIVISION_CODES.keys()),
                         help="Liga de procesat (din LEAGUE_DIVISION_CODES)")
    parser.add_argument("--stats", type=str, required=True,
                         choices=list(STAT_GROUPS.keys()),
                         help="Grupul de coloane de completat (din STAT_GROUPS)")
    parser.add_argument("--dry-run", action="store_true",
                         help="Simulare — fără scriere în Supabase")
    args = parser.parse_args()

    metrics = run_backfill_for_league(args.league, args.stats, dry_run=args.dry_run)

    print("═" * 60)
    print(f"  BACKFILL MATCH STATS — {args.league} / {args.stats} (dry_run={args.dry_run})")
    print("═" * 60)
    print(f"  Meciuri unice în sursă  : {metrics.source_matches_found}")
    print(f"  Potrivite               : {metrics.matched}")
    print(f"  Rata de matching        : {metrics.match_rate_pct}%")
    print(f"  Deja complete           : {metrics.already_complete}")
    print(f"  Fără potrivire          : {metrics.rejected_no_match}")
    print(f"  Ambigue                 : {metrics.rejected_ambiguous_match}")
    print(f"  Scor neconcordant       : {metrics.rejected_score_mismatch}")
    print(f"  Scrise cu succes        : {metrics.written_ok}")
    print(f"  Erori de scriere        : {metrics.write_errors}")
    print(f"  Populare per coloană    : {metrics.columns_populated}")
    print("═" * 60)
    if metrics.rejection_details:
        sample = metrics.rejection_details[:20]
        print(f"  Exemple motive respingere (max 20 din {len(metrics.rejection_details)}):")
        for line in sample:
            print(f"    - {line}")

    if metrics.write_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
