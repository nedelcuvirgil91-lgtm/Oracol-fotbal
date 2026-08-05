"""
================================================================================
FOOTBALL ORACLE — Validation Analysis CLI (ADR-052 §2.4)
================================================================================
Punct de intrare pentru declanșatorul extern (GitHub Actions, decuplat de
sync/run_daily.py, continuous_learning.yml și consensus_validation.yml) —
vezi .github/workflows/validation_analysis.yml.

Rulare:
    python run_validation_analysis.py --cadence daily
    python run_validation_analysis.py --cadence weekly
================================================================================
"""
from __future__ import annotations

import argparse
import json

from validation_analysis import run_report_cycle


def main() -> None:
    parser = argparse.ArgumentParser(description="Football Oracle — Validation Analysis (ADR-052)")
    parser.add_argument("--cadence", choices=["daily", "weekly"], required=True)
    args = parser.parse_args()

    print("═" * 60)
    print(f"  Football Oracle — Validation Analysis ({args.cadence}, ADR-052)")
    print("═" * 60)

    summary = run_report_cycle(args.cadence)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))

    if not summary.get("enabled", False):
        print("\n  validation_analysis_enabled=False — niciun ciclu executat.")
        return

    status = summary.get("status")
    if status == "no_data":
        print("\n  0 meciuri cu rezultat cunoscut in fereastra — niciun raport salvat.")
    elif status == "computed":
        report = summary["report"]
        print(f"\n  Fereastra {report['period_start']}..{report['period_end']} "
              f"({report['n_matches_total']} meciuri) — salvat={summary['saved']}")
        for engine in ("oracle", "ml", "blend"):
            m = report[engine]
            if m["n"] == 0:
                print(f"    {engine}: n=0 (indisponibil in fereastra)")
            else:
                print(f"    {engine}: n={m['n']} brier={m['brier']:.4f} "
                      f"logloss={m['logloss']:.4f} accuracy={m['accuracy']:.4f}")


if __name__ == "__main__":
    main()
