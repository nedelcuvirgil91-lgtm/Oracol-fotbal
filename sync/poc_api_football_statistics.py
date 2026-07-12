"""
================================================================================
FOOTBALL ORACLE — CLI: sondaj API-Football /fixtures/statistics
================================================================================
Module: sync/poc_api_football_statistics.py

Wrapper subțire peste diagnostics_api_football.py — Discovery & Instrumentation,
NU integrare. Nu scrie în match_history, nu atinge Prediction Engine.

Rulare:
  python sync/poc_api_football_statistics.py
  python sync/poc_api_football_statistics.py --leagues "Premier League,La Liga"

Rulat de obicei prin GitHub Actions (workflow_dispatch — vezi
.github/workflows/poc_api_football_statistics.yml), unde există acces real la
Internet, spre deosebire de mediul de dezvoltare curent.
================================================================================
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from diagnostics_api_football import PROBE_TEAMS, format_report_text, run_probe


def main() -> None:
    parser = argparse.ArgumentParser(description="Sondaj API-Football /fixtures/statistics (discovery, nu integrare)")
    parser.add_argument(
        "--leagues", default="",
        help=f"Listă de ligi separate prin virgulă (implicit toate: {', '.join(PROBE_TEAMS.keys())})",
    )
    args = parser.parse_args()

    leagues = [l.strip() for l in args.leagues.split(",") if l.strip()] or None
    unknown = [l for l in (leagues or []) if l not in PROBE_TEAMS]
    if unknown:
        print(f"⚠️  Ligi necunoscute (ignorate, nu sunt în PROBE_TEAMS): {unknown}")
        leagues = [l for l in leagues if l in PROBE_TEAMS] or None

    report = run_probe(leagues=leagues)
    print(format_report_text(report))


if __name__ == "__main__":
    main()
