"""Regenerează tests/predictor_regression_golden.json — Predictor Regression
Suite (EPIC "Functional Completion", Punctul 2, 2026-08-03).

NU se rulează automat, niciodată în CI. Rulare manuală, DOAR când o
schimbare deliberată și aprobată a Predictorului trebuie să devină noua
bază "golden" — orice altă rulare a testului
(tests/test_predictor_regression_suite.py) trebuie să EȘUEZE dacă
valorile diferă, nu să fie "reparată" prin regenerare necontrolată.

Rulare:
  python scripts/generate_predictor_regression_golden.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from predictor_regression_scenarios import SCENARIOS, run_scenario, snapshot_fields

GOLDEN_PATH = ROOT / "tests" / "predictor_regression_golden.json"


def main() -> None:
    golden: dict[str, dict] = {}
    for scenario in SCENARIOS:
        pred = run_scenario(scenario)
        golden[scenario.key] = snapshot_fields(pred)
        print(f"{scenario.key:35s} home_xg={pred.home_xg:.4f} away_xg={pred.away_xg:.4f} "
              f"ph={pred.prob_home_win:.4f} pd={pred.prob_draw:.4f} pa={pred.prob_away_win:.4f}")

    GOLDEN_PATH.write_text(json.dumps(golden, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\nScris {len(golden)} scenarii in {GOLDEN_PATH}")


if __name__ == "__main__":
    main()
