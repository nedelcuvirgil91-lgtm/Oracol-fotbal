"""
================================================================================
FOOTBALL ORACLE — CLI: sondaj API-Football /fixtures/statistics
================================================================================
Module: sync/poc_api_football_statistics.py

Wrapper subțire peste diagnostics_api_football.py — Discovery & Instrumentation,
NU integrare. Nu scrie în match_history, nu atinge Prediction Engine.

Selecție manuală, o singură ligă per rulare (optimizare de quota — vezi
diagnostics_api_football.py). Nu mai există "implicit toate ligile".

Rulare:
  python sync/poc_api_football_statistics.py --league "Premier League"

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
        "--league", required=True, choices=sorted(PROBE_TEAMS.keys()),
        help="O singură ligă de verificat (selecție manuală, obligatorie).",
    )
    args = parser.parse_args()

    report = run_probe(leagues=[args.league])
    print(format_report_text(report))


if __name__ == "__main__":
    main()
