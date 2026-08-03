"""Predictor Regression Suite (EPIC "Functional Completion", Punctul 2,
aprobat explicit de proprietarul produsului, 2026-08-03).

Rulează `FootballOracleEngine.evaluate_match()` REAL (punctul de intrare de
producție, nu un helper intern) pentru 20 de meciuri golden
(`tests/predictor_regression_scenarios.py`), complet mock-uit — zero
rețea/Supabase reală — și compară `home_xg`/`away_xg`/`ph`/`pd`/`pa` cu
snapshot-ul înghețat `tests/predictor_regression_golden.json`.

Dacă acest test EȘUEAZĂ după o schimbare intenționată la Oracle Engine/
feature_engine.py, NU se "repară" prin rulare oarbă a
`scripts/generate_predictor_regression_golden.py` — diferența trebuie
înțeleasă și aprobată explicit înainte de regenerarea bazei golden (altfel
suita nu mai protejează nimic)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from predictor_regression_scenarios import SCENARIOS, run_scenario, snapshot_fields

GOLDEN_PATH = Path(__file__).parent / "predictor_regression_golden.json"

with open(GOLDEN_PATH, encoding="utf-8") as f:
    GOLDEN = json.load(f)

# Toleranta stricta - Monte Carlo foloseste un seed fix
# (np.random.default_rng(seed=42), oracle_engine.py) - iesirea e
# deterministic-identica intre rulari pentru input identic, nu doar
# statistic apropiata. O toleranta minima absoarbe doar variatii reale
# de rotunjire in lant (round() aplicat de mai multe ori pe parcurs).
TOLERANCE = 1e-6


def test_golden_dataset_has_exactly_20_scenarios():
    assert len(SCENARIOS) == 20
    assert set(GOLDEN.keys()) == {s.key for s in SCENARIOS}


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.key)
def test_prediction_matches_golden_snapshot(scenario):
    pred = run_scenario(scenario)
    actual = snapshot_fields(pred)
    expected = GOLDEN[scenario.key]

    for field in ("home_xg", "away_xg", "ph", "pd", "pa"):
        assert actual[field] == pytest.approx(expected[field], abs=TOLERANCE), (
            f"[{scenario.key}] {field}: asteptat {expected[field]}, obtinut {actual[field]} "
            f"(drift fata de golden snapshot — verifica daca schimbarea la Oracle Engine e "
            f"intentionata; daca da, regenereaza cu scripts/generate_predictor_regression_golden.py "
            f"DUPA aprobare explicita)"
        )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.key)
def test_probabilities_sum_to_one(scenario):
    """Garda de sanitate — indiferent de drift, ph+pd+pa trebuie sa ramana
    o distributie de probabilitate aproape valida. Toleranta 1% (nu 0.1%):
    matricea Poisson e trunchiata la max_goals_poisson (implicit 8) -
    meciurile cu xG mare pentru favorit (ex. ucl_giant_vs_underdog) pierd
    legitim o fractiune mica de masa de probabilitate dincolo de prag -
    comportament cunoscut, nu bug."""
    pred = run_scenario(scenario)
    total = pred.prob_home_win + pred.prob_draw + pred.prob_away_win
    assert total == pytest.approx(1.0, abs=1e-2)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.key)
def test_xg_values_are_positive(scenario):
    pred = run_scenario(scenario)
    assert pred.home_xg > 0
    assert pred.away_xg > 0
