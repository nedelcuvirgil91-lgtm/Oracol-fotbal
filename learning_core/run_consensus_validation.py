"""
================================================================================
FOOTBALL ORACLE — Learning Core: Consensus Validation CLI (ADR-033)
================================================================================
Punct de intrare pentru declanșatorul extern (GitHub Actions, decuplat atât
de sync/run_daily.py, cât și de continuous_learning.yml — ADR-030) — vezi
.github/workflows/consensus_validation.yml.

Nu populează Model Registry — ADR-033 nu are nicio interacțiune cu el
(nu se înregistrează, nu e antrenat, nu e un LearningAlgorithm).

Rulare:
    python learning_core/run_consensus_validation.py
================================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from learning_core.consensus_validation import run_validation_cycle


def main() -> None:
    print("═" * 60)
    print("  Football Oracle — Consensus Validation (ADR-033)")
    print("  Decuplat de run_daily.py și de continuous_learning.yml")
    print("═" * 60)

    summary = run_validation_cycle()

    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))

    if not summary.get("enabled", False):
        print("\n  consensus_validation_enabled=False — niciun ciclu executat.")
        return

    if summary.get("status") == "insufficient_data":
        print(f"\n  {summary['n_samples']} eșantioane — sub prag "
              f"({summary['n_samples']} < 200), niciun verdict produs.")
        return

    verdicts = summary.get("results", {})
    print(f"\n  {summary['n_samples']} eșantioane evaluate:")
    for metric_name, result in verdicts.items():
        print(f"    {metric_name}: {result['verdict']}")


if __name__ == "__main__":
    main()
