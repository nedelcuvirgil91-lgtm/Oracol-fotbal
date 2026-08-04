"""
================================================================================
FOOTBALL ORACLE — CLI: backfill istoric meciuri pentru ligi specifice
================================================================================
Module: sync/backfill_league_matches.py

Punct de intrare manual pentru `sync.sync_matches.sync_all()` — logica de
sincronizare istorică (football-data.org + openfootball, deduplicare pe
fixture_id, scriere prin `upsert_matches_canonical`) e deja completă și
deja rulează zilnic, pentru toate ligile, ca „Pasul 2/6" din
`sync/run_daily.py`. Nu exista insa un punct de intrare care sa permita
rularea EI SINGURE, restransa la o lista explicita de ligi — util pentru
backfill controlat (ex. o ligă nou-înregistrată, fără istoric încă), fără
să declanșeze restul pipeline-ului zilnic (rezultate/statistici/feature-uri/
shadow/cote — toate neatinse).

Rulare:
  python sync/backfill_league_matches.py --leagues "Primeira Liga,Eredivisie,Super Lig"
  (sau .github/workflows/backfill_league_matches.yml, workflow_dispatch manual)
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

logger = logging.getLogger("FootballOracle.Sync.BackfillLeagueMatches")


def run(leagues: list[str]) -> None:
    from sync.sync_matches import sync_all

    reports = sync_all(use_football_data=True, use_openfootball=True, leagues=leagues)
    for r in reports:
        print(f"\n{r.source}: {r.matches_fetched} găsite, {r.matches_new} noi, "
              f"{r.matches_skipped} deja existente, {r.errors} erori")
        print(f"  ligi: {', '.join(r.leagues_synced) or '(niciuna)'}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Backfill istoric meciuri pentru ligi explicite (football-data.org + openfootball)")
    parser.add_argument("--leagues", required=True, help='Ligi separate prin virgulă, ex: "Primeira Liga,Eredivisie"')
    args = parser.parse_args()

    leagues_arg = [lg.strip() for lg in args.leagues.split(",") if lg.strip()]
    run(leagues_arg)
