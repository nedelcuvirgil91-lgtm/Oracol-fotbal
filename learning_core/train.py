"""
================================================================================
FOOTBALL ORACLE — Learning Core: Training Runner (CLI manual)
================================================================================
Rulare exclusiv manuală — NU face parte din sync/run_daily.py, nu se
declanșează automat de nimic. Vezi LEARNING_CORE_ARCHITECTURE.md §9 (v4.1):
"Training Runner — apelabil manual (CLI...), nu încă în bucla zilnică automată."

Folosire:
    python learning_core/train.py                            # antrenează toți algoritmii înregistrați
    python learning_core/train.py --algorithm xgboost_v1      # doar unul
    python learning_core/train.py --list                      # listează algoritmii disponibili, iese
================================================================================
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from learning_core import model_registry
from learning_core.bootstrap import register_default_algorithms
from learning_core.training_runner import run_training


def _print_separator(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _print_report(report) -> None:
    _print_separator()
    print(f"  Algoritm: {report.algorithm_name} v{report.algorithm_version} "
          f"(ligă: {report.league_scope})")
    _print_separator()
    print(f"  Status           : {report.result.status}")
    print(f"  Samples folosite : {report.result.samples_used}")
    if report.result.walk_forward_metrics:
        print("  Metrici walk-forward:")
        for k, v in report.result.walk_forward_metrics.items():
            print(f"    {k}: {v}")
    if report.result.message:
        print(f"  Mesaj            : {report.result.message}")
    print(f"  Salvat local     : {report.saved_to}")
    print(f"  training_run_id  : {report.result.training_run_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Football Oracle — Learning Core Training Runner (rulare manuală)"
    )
    parser.add_argument("--algorithm", help="Nume algoritm (ex. xgboost_v1). Implicit: toți din registry.")
    parser.add_argument("--version", default="1", help="Versiune algoritm (implicit: 1)")
    parser.add_argument("--list", action="store_true", help="Listează algoritmii disponibili și iese")
    args = parser.parse_args()

    register_default_algorithms()

    if args.list:
        print("Algoritmi disponibili în Model Registry:")
        for name, version in model_registry.list_available():
            print(f"  - {name} v{version}")
        return

    print("═" * 60)
    print("  Football Oracle — Learning Core — Training Runner")
    print("  Rulare MANUALĂ — nu face parte din sincronizarea zilnică")
    print("═" * 60)

    targets = (
        [(args.algorithm, args.version)]
        if args.algorithm
        else model_registry.list_available()
    )

    if not targets:
        print("\n  Niciun algoritm înregistrat. Verifică bootstrap.register_default_algorithms().")
        return

    succeeded = 0
    for name, version in targets:
        try:
            report = run_training(name, version)
            succeeded += 1
            print()
            _print_report(report)
        except Exception as exc:
            print(f"\n  ⚠️  {name} v{version}: eșuat — {exc}")

    print()
    print("═" * 60)
    print(f"  {succeeded}/{len(targets)} antrenări finalizate")
    print("═" * 60)


if __name__ == "__main__":
    main()
