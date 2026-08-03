"""
================================================================================
FOOTBALL ORACLE — Backfill Season (football-data.org) CLI
================================================================================
Module: sync/backfill_season_football_data.py

Backfill dedicat pentru coloana `season` pe rândurile DEJA EXISTENTE în
match_history, provenite din football-data.org (fixture_id LIKE 'fd_%').

De ce e nevoie de un script separat, în loc de fluxul zilnic normal:
`sync.sync_matches.sync_from_football_data()` filtrează explicit, prin
`_deduplicate()`, orice `fixture_id` deja prezent în match_history ÎNAINTE
ca rândul să ajungă la `upsert_matches_bulk()` — util pentru sincronizarea
zilnică (evită re-trimiterea de meciuri deja colectate), dar înseamnă că
fix-ul din `sync/sources/football_data.py` (season inclus acum în payload,
2026-08-03) nu poate atinge randuri deja colectate prin acel flux, oricât
ar rula night_sync.yml — confirmat live: rulare completă night_sync.yml
(run #3, 2026-08-03) -> 0/5756 randuri fd_* au capatat season.

Acest script re-interoghează football-data.org — exact aceleași 6 ligi x 5
sezoane (30 request-uri, `SEASONS`/`COMPETITION_CODES` din
sync/sources/football_data.py, neschimbate aici) — și scrie DIRECT prin
`database.queries.upsert_matches_bulk()`, FĂRĂ pasul de deduplicare
client-side (nu importă `sync.sync_matches`, nu apelă
`get_existing_fixture_ids()`/`_deduplicate()`).

Siguranță: `upsert_matches_bulk()` trece prin RPC-ul canonic
`upsert_matches_canonical` (migrația 038), care caută rândul existent după
CHEIA NATURALĂ (home_team, away_team, kickoff_date) — nu după fixture_id —
și face COALESCE per coloană: orice coloană deja populată (actual_result,
home_elo, etc.) rămâne neschimbată; doar coloanele NULL (aici, `season`)
se completează. Lock advisory per cheie naturală (deja folosit de fluxul
zilnic) elimină orice risc de race condition. Idempotent prin construcție:
rulat de mai multe ori, a doua rulare nu schimbă nimic (COALESCE e no-op
pe coloane deja populate) — nu prin verificare manuală.

Rulare:
  python -m sync.backfill_season_football_data --dry-run
  python -m sync.backfill_season_football_data
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
logger = logging.getLogger("FootballOracle.BackfillSeasonFootballDataCLI")


def run(dry_run: bool = False) -> dict:
    """Re-fetch football-data.org (toate ligile/sezoanele implicite din
    sync.sources.football_data) și scrie direct prin upsert_matches_bulk(),
    fără deduplicare client-side pe fixture_id — vezi docstring-ul
    modulului pentru motiv și garanții de siguranță."""
    from sync.sources.football_data import fetch_all_leagues

    all_matches: list[dict] = []

    for league, season, matches in fetch_all_leagues():
        if matches:
            all_matches.extend(matches)
        logger.info("[BackfillSeason] FD: %s %d -> %d meciuri", league, season, len(matches))

    with_season = sum(1 for m in all_matches if m.get("season"))
    without_season = len(all_matches) - with_season

    logger.info(
        "[BackfillSeason] Total fetch-uit: %d meciuri (%d cu season din provider, %d fără)",
        len(all_matches), with_season, without_season,
    )

    if dry_run:
        logger.info("[BackfillSeason] --dry-run: nicio scriere în Supabase.")
        return {
            "fetched": len(all_matches),
            "with_season": with_season,
            "without_season": without_season,
            "written_ok": 0,
            "errors": 0,
            "dry_run": True,
        }

    if not all_matches:
        logger.warning("[BackfillSeason] Niciun meci fetch-uit — nimic de scris.")
        return {
            "fetched": 0, "with_season": 0, "without_season": 0,
            "written_ok": 0, "errors": 0, "dry_run": False,
        }

    from database.queries import upsert_matches_bulk
    ok, errors = upsert_matches_bulk(all_matches)
    logger.info("[BackfillSeason] Scriere: %d ok, %d erori", ok, errors)

    return {
        "fetched": len(all_matches),
        "with_season": with_season,
        "without_season": without_season,
        "written_ok": ok,
        "errors": errors,
        "dry_run": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Football Oracle — Backfill season pentru rânduri existente football-data.org"
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch + raport, fără scriere în Supabase")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run)

    print("=" * 60)
    print(f"  BACKFILL SEASON — football-data.org (dry_run={args.dry_run})")
    print("=" * 60)
    print(f"  Meciuri fetch-uite          : {result['fetched']}")
    print(f"  Cu season din provider      : {result['with_season']}")
    print(f"  Fără season (provider omis) : {result['without_season']}")
    print(f"  Scrise cu succes            : {result['written_ok']}")
    print(f"  Erori de scriere            : {result['errors']}")
    print("=" * 60)

    if result["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
