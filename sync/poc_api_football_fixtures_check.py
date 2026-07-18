"""
================================================================================
FOOTBALL ORACLE — CLI: verificare functionala a fallback-ului API-Football
================================================================================
Module: sync/poc_api_football_fixtures_check.py

Verificare END-TO-END, cu date reale: apeleaza oracle_api.get_matches_for_week()
exact cum ar face-o app.py, pentru o singura liga data, si arata cate meciuri
au venit si din ce sursa (Odds/FreeLF/football-data/ESPN/TSDB/apifootball/demo).
Discovery, NU o schimbare de productie — nu scrie nicaieri, doar citeste.

Rulare:
  python sync/poc_api_football_fixtures_check.py --league "Romania SuperLiga"
================================================================================
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from oracle_api import FootballOracleAPI


def main() -> None:
    parser = argparse.ArgumentParser(description="Verificare functionala fallback API-Football")
    parser.add_argument("--league", required=True)
    args = parser.parse_args()

    api = FootballOracleAPI()
    matches = api.get_matches_for_week(days_ahead=7, competitions=[args.league])

    print(f"{len(matches)} meciuri gasite pentru {args.league!r}:\n")
    for m in matches:
        print(f"  {m.get('home_team')} vs {m.get('away_team')}  "
              f"({m.get('kickoff_date')})  source={m.get('source')}")

    sources = {m.get("source") for m in matches}
    print(f"\nSurse folosite: {sorted(s for s in sources if s)}")


if __name__ == "__main__":
    main()
