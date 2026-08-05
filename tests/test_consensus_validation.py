"""
Teste pentru learning_core.consensus_validation (ADR-033, Faza 2 — T1,
periodic). Fără rețea — automation_runs și supabase_client monkeypatch-uite.
"""
from __future__ import annotations

import pytest

import learning_core.consensus_validation as cv


# ── compute_metrics() — funcție pură ────────────────────────────────────────

def test_compute_metrics_none_with_single_engine():
    """ml_active=False -> un singur motor -> nimic de comparat, stare
    legitima, nu eroare."""
    result = cv.compute_metrics([
        {"family": "rule_based", "engine": "oracle_protocol", "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2},
    ])
    assert result is None


def test_compute_metrics_perfect_agreement():
    identical = {"prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}
    result = cv.compute_metrics([
        {"family": "ml", "engine": "xgboost_v1", **identical},
        {"family": "rule_based", "engine": "oracle_protocol", **identical},
    ])
    assert result["agreement_score"] == pytest.approx(1.0)
    assert result["divergence_score"] == pytest.approx(0.0)
    assert result["prediction_distance"] == 0.0


def test_compute_metrics_maximum_disagreement():
    """Distanta L1 maxima intre doi vectori de probabilitate e 2 (ex. un
    motor 100% acasa, celalalt 100% deplasare) -> agreement_score = 0."""
    result = cv.compute_metrics([
        {"family": "ml", "engine": "xgboost_v1", "prob_home": 1.0, "prob_draw": 0.0, "prob_away": 0.0},
        {"family": "rule_based", "engine": "oracle_protocol", "prob_home": 0.0, "prob_draw": 0.0, "prob_away": 1.0},
    ])
    assert result["agreement_score"] == pytest.approx(0.0)
    assert result["divergence_score"] == pytest.approx(2.0)
    assert result["prediction_distance"] == 1.0


def test_compute_metrics_same_argmax_different_probabilities():
    """Ambele motoare aleg 'acasa' ca rezultat cel mai probabil, dar cu
    probabilitati diferite -> prediction_distance=0, dar agreement < 1."""
    result = cv.compute_metrics([
        {"family": "ml", "engine": "xgboost_v1", "prob_home": 0.9, "prob_draw": 0.05, "prob_away": 0.05},
        {"family": "rule_based", "engine": "oracle_protocol", "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2},
    ])
    assert result["prediction_distance"] == 0.0
    assert 0.0 < result["agreement_score"] < 1.0


def test_compute_metrics_none_with_three_engines():
    """[CORECTAT — audit final ADR-051/052] Metrica e definită doar pentru o
    PERECHE (distanță L1 între doi vectori) — cu 3+ motoare disponibile,
    trebuie să întoarcă explicit None (Regula #8), nu să aleagă tacit
    primele două și să ignore restul. Nu se întâmplă azi în producție
    (build_raw_predictions() nu adaugă niciodată mai mult de Oracle+ML),
    dar codul trebuie să rămână corect indiferent de asta — gardă
    structurală, nu doar comportamentală."""
    three = [
        {"family": "rule_based", "engine": "oracle_protocol", "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2},
        {"family": "ml", "engine": "xgboost_v1", "prob_home": 0.4, "prob_draw": 0.35, "prob_away": 0.25},
        {"family": "blend", "engine": "blend_v1", "prob_home": 0.45, "prob_draw": 0.32, "prob_away": 0.23},
    ]
    assert cv.compute_metrics(three) is None


# ── _bootstrap_independent_groups() — funcție pură ──────────────────────────

def test_bootstrap_independent_groups_detects_clear_difference():
    low_error_group = [0.1] * 50
    high_error_group = [0.9] * 50
    result = cv._bootstrap_independent_groups(low_error_group, high_error_group, n_iterations=200)
    assert result["significant"] is True
    assert result["delta"] < 0


def test_bootstrap_independent_groups_identical_groups_not_significant():
    same = [0.5] * 50
    result = cv._bootstrap_independent_groups(same, same, n_iterations=200)
    assert result["significant"] is False
    assert result["delta"] == pytest.approx(0.0)


# ── Constante fixate la Freeze (ADR-033) ────────────────────────────────────

def test_threshold_matches_adr033_freeze():
    assert cv.MIN_SAMPLES_FOR_CONSENSUS_VALIDATION == 200


def test_primary_metric_is_agreement_score():
    assert cv.PRIMARY_METRIC == "agreement_score"
    assert cv.PRIMARY_METRIC in cv.CANDIDATE_METRICS


# ── run_validation_cycle() — orchestrare ────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_ar(monkeypatch):
    """automation_runs fabricat - captureaza apelurile fara scriere reala."""
    calls = []

    class _Recorder:
        def write_run(self, producer, process_type, tier, target_key=None):
            calls.append(("write_run", producer, process_type, tier, target_key))
            return len(calls)

        def start_run(self, run_id):
            calls.append(("start_run", run_id))
            return True

        def complete_run(self, run_id, summary=None):
            calls.append(("complete_run", run_id, summary))
            return True

        def skip_run(self, run_id, skip_reason):
            calls.append(("skip_run", run_id, skip_reason))
            return True

        def propose_decision(self, run_id, tier, rollback_plan=None, evidence=None,
                              correction_method=None, ttl_hours=None):
            calls.append(("propose_decision", run_id, tier, evidence))
            return 999

        def surface_decision(self, decision_id):
            calls.append(("surface_decision", decision_id))
            return True

    rec = _Recorder()
    monkeypatch.setattr(cv, "ar", rec)
    yield calls


def test_disabled_by_default_skips_entire_cycle(monkeypatch, clean_ar):
    monkeypatch.setattr(cv.sb, "load_config", lambda default: dict(default))
    result = cv.run_validation_cycle()
    assert result == {"enabled": False}
    assert clean_ar == [], "niciun automation_run nu trebuie creat cand flag-ul e oprit"


def _enable(monkeypatch):
    monkeypatch.setattr(cv.sb, "load_config", lambda default: {"consensus_validation_enabled": True})


def _sample(fixture_id: str, agreement_pair, outcome: str, kickoff="2026-01-01"):
    return {
        "fixture_id": fixture_id,
        "raw_predictions": [
            {"family": "ml", "engine": "xgboost_v1", **agreement_pair[0]},
            {"family": "rule_based", "engine": "oracle_protocol", **agreement_pair[1]},
        ],
        "kickoff_date": kickoff,
        "actual_result": outcome,
    }


def test_below_threshold_skips_with_reason(monkeypatch, clean_ar):
    _enable(monkeypatch)
    few_samples = [
        _sample(f"fx-{i}",
                ({"prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2},
                 {"prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}),
                "H")
        for i in range(5)
    ]
    monkeypatch.setattr(cv.sb, "get_unevaluated_consensus_samples", lambda: few_samples)

    result = cv.run_validation_cycle()

    assert result["status"] == "insufficient_data"
    assert result["n_samples"] == 5
    skip_calls = [c for c in clean_ar if c[0] == "skip_run"]
    assert len(skip_calls) == 1
    assert "prag de esantion" in skip_calls[0][2]


def test_above_threshold_evaluates_all_candidate_metrics(monkeypatch, clean_ar):
    _enable(monkeypatch)
    import random
    random.seed(42)
    samples = []
    for i in range(250):
        agree = i % 2 == 0
        outcome = "H" if agree else random.choice(["H", "D", "A"])
        pair = (
            {"prob_home": 0.7, "prob_draw": 0.2, "prob_away": 0.1},
            {"prob_home": 0.7, "prob_draw": 0.2, "prob_away": 0.1} if agree
            else {"prob_home": 0.1, "prob_draw": 0.2, "prob_away": 0.7},
        )
        samples.append(_sample(f"fx-{i}", pair, outcome))
    monkeypatch.setattr(cv.sb, "get_unevaluated_consensus_samples", lambda: samples)

    saved_verdicts = {}
    def _fake_save(**kw):
        saved_verdicts[kw["metric_name"]] = kw
        return True
    monkeypatch.setattr(cv.sb, "save_consensus_validation_verdict", _fake_save)

    result = cv.run_validation_cycle()

    assert result["status"] == "evaluated"
    assert set(saved_verdicts.keys()) == set(cv.CANDIDATE_METRICS)
    assert saved_verdicts["agreement_score"]["is_primary_metric"] is True
    assert saved_verdicts["divergence_score"]["is_primary_metric"] is False
    assert saved_verdicts["prediction_distance"]["is_primary_metric"] is False


def test_exploratory_metric_surface_worthy_never_proposes_t3a(monkeypatch, clean_ar):
    """[ADR-033 §5] Nicio metrica exploratorie nu poate declansa T3a, chiar
    daca iese semnificativa - doar metrica PRIMARA poate."""
    _enable(monkeypatch)
    samples = [_sample(f"fx-{i}",
                        ({"prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2},
                         {"prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}),
                        "H") for i in range(250)]
    monkeypatch.setattr(cv.sb, "get_unevaluated_consensus_samples", lambda: samples)
    monkeypatch.setattr(cv.sb, "save_consensus_validation_verdict", lambda **kw: True)

    def _fake_evaluate(metric_name, usable, is_primary):
        # simuleaza un verdict surface_worthy pentru O METRICA EXPLORATORIE
        verdict = "surface_worthy" if metric_name == "divergence_score" else "rejected"
        return {"verdict": verdict, "n_samples_evaluated": len(usable), "test": None}

    monkeypatch.setattr(cv, "_evaluate_metric", _fake_evaluate)

    cv.run_validation_cycle()

    propose_calls = [c for c in clean_ar if c[0] == "propose_decision"]
    assert propose_calls == [], "un verdict pozitiv pe o metrica exploratorie nu trebuie sa propuna T3a"


def test_primary_metric_surface_worthy_proposes_t3a(monkeypatch, clean_ar):
    _enable(monkeypatch)
    samples = [_sample(f"fx-{i}",
                        ({"prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2},
                         {"prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}),
                        "H") for i in range(250)]
    monkeypatch.setattr(cv.sb, "get_unevaluated_consensus_samples", lambda: samples)
    monkeypatch.setattr(cv.sb, "save_consensus_validation_verdict", lambda **kw: True)

    def _fake_evaluate(metric_name, usable, is_primary):
        verdict = "surface_worthy" if metric_name == cv.PRIMARY_METRIC else "rejected"
        return {"verdict": verdict, "n_samples_evaluated": len(usable), "test": None}

    monkeypatch.setattr(cv, "_evaluate_metric", _fake_evaluate)

    cv.run_validation_cycle()

    propose_calls = [c for c in clean_ar if c[0] == "propose_decision"]
    assert len(propose_calls) == 1
    assert propose_calls[0][2] == "T3a"
    assert propose_calls[0][3]["metric_name"] == cv.PRIMARY_METRIC
