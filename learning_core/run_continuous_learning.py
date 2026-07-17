"""
================================================================================
FOOTBALL ORACLE — Learning Core: Continuous Learning CLI (ADR-030)
================================================================================
Punct de intrare pentru declanșatorul extern (GitHub Actions, decuplat de
sync/run_daily.py) — vezi .github/workflows/continuous_learning.yml.

Populează Model Registry (register_default_algorithms(), exact tiparul deja
folosit de learning_core/train.py — nu e responsabilitatea funcției de
orchestrare din continuous_learning.py), apoi rulează un ciclu complet.

Rulare:
    python learning_core/run_continuous_learning.py
================================================================================
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from learning_core.bootstrap import register_default_algorithms
from learning_core.continuous_learning import run_cycle


def main() -> None:
    print("═" * 60)
    print("  Football Oracle — Continuous Learning (ADR-030)")
    print("  Decuplat de sync/run_daily.py — rulare programată independentă")
    print("═" * 60)

    register_default_algorithms()
    summary = run_cycle()

    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if not summary.get("enabled", False):
        print("\n  learning_core_enabled=False — niciun ciclu executat.")
        return

    print(
        f"\n  {summary['checked']} verificate · {summary['trained']} antrenări noi · "
        f"{summary['evaluated']} evaluări · {summary['proposed']} propuneri T3a · "
        f"{summary['committed']} promovări executate · {summary['guard_failures']} gărzi eșuate"
    )
    if summary["guard_failures"] > 0:
        print("\n  ⚠️  ATENȚIE: gărzi de consistență eșuate — vezi Decision Feed / Activity Log.")


if __name__ == "__main__":
    main()
