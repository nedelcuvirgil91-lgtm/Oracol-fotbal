"""Teste pentru prediction_evaluation.py (Sprint 0 — Stabilizare, Etapa 3) —
Accuracy/Log-loss/Brier/Calibrare, funcții pure, fără rețea."""
from __future__ import annotations

import math

import pytest

from prediction_evaluation import (
    CalibrationBin,
    EvaluationMetrics,
    build_evaluation_report,
    compute_calibration,
    compute_metrics,
)


def _row(ph, pd_, pa, actual, league="Premier League"):
    return {"prob_home_pred": ph, "prob_draw_pred": pd_, "prob_away_pred": pa,
            "actual_result": actual, "league": league}


# ── compute_metrics ─────────────────────────────────────────────────────

def test_compute_metrics_empty_rows_returns_none_metrics():
    m = compute_metrics([])
    assert m == EvaluationMetrics(n=0, accuracy=None, log_loss=None, brier_score=None)


def test_compute_metrics_hand_verified_values():
    """Valori calculate manual, verificate independent de implementare —
    3 randuri, formula Brier multi-clasa (identica ml_predictor._multiclass_brier)
    si log-loss standard (cross-entropy pe clasa reala)."""
    rows = [
        _row(0.6, 0.3, 0.1, "H"),   # corect, ll=-ln(0.6), brier=0.26
        _row(0.2, 0.3, 0.5, "A"),   # corect, ll=-ln(0.5), brier=0.38
        _row(0.5, 0.3, 0.2, "D"),   # gresit (predicted=H), ll=-ln(0.3), brier=0.78
    ]
    m = compute_metrics(rows)

    assert m.n == 3
    assert m.accuracy == round(2 / 3, 4)

    expected_ll = (-math.log(0.6) - math.log(0.5) - math.log(0.3)) / 3
    assert m.log_loss == round(expected_ll, 4)

    expected_brier = (0.26 + 0.38 + 0.78) / 3
    assert m.brier_score == round(expected_brier, 4)


def test_compute_metrics_perfect_predictions_have_zero_brier_and_full_accuracy():
    rows = [_row(1.0, 0.0, 0.0, "H"), _row(0.0, 1.0, 0.0, "D"), _row(0.0, 0.0, 1.0, "A")]
    m = compute_metrics(rows)
    assert m.accuracy == 1.0
    assert m.brier_score == 0.0
    assert m.log_loss == 0.0


def test_compute_metrics_excludes_rows_with_missing_probability():
    rows = [
        _row(0.6, 0.3, 0.1, "H"),
        {"prob_home_pred": None, "prob_draw_pred": 0.3, "prob_away_pred": 0.5, "actual_result": "A"},
    ]
    m = compute_metrics(rows)
    assert m.n == 1


def test_compute_metrics_excludes_rows_with_invalid_actual_result():
    rows = [_row(0.6, 0.3, 0.1, None), _row(0.5, 0.3, 0.2, "X")]
    m = compute_metrics(rows)
    assert m.n == 0


def test_compute_metrics_clips_probability_to_avoid_log_zero():
    """Un rand cu probabilitate exact 0 pe clasa reala nu trebuie sa
    arunce math domain error (log(0)) — clipping la eps."""
    rows = [_row(1.0, 0.0, 0.0, "D")]
    m = compute_metrics(rows)
    assert m.log_loss is not None and m.log_loss > 0


# ── compute_calibration ─────────────────────────────────────────────────

def test_compute_calibration_returns_bins_for_all_three_outcomes():
    rows = [_row(0.6, 0.3, 0.1, "H")]
    bins = compute_calibration(rows, n_bins=10)
    outcomes = {b.outcome for b in bins}
    assert outcomes == {"H", "D", "A"}
    assert len(bins) == 30  # 10 bin-uri x 3 clase


def test_compute_calibration_places_prediction_in_correct_bin():
    rows = [_row(0.65, 0.2, 0.15, "H")]
    bins = compute_calibration(rows, n_bins=10)
    h_bin = next(b for b in bins if b.outcome == "H" and b.bin_index == 6)
    assert h_bin.n == 1
    assert h_bin.mean_predicted == 0.65
    assert h_bin.observed_frequency == 1.0


def test_compute_calibration_empty_bin_has_none_stats():
    rows = [_row(0.05, 0.05, 0.9, "A")]
    bins = compute_calibration(rows, n_bins=10)
    h_bin_far = next(b for b in bins if b.outcome == "H" and b.bin_index == 9)
    assert h_bin_far.n == 0
    assert h_bin_far.mean_predicted is None
    assert h_bin_far.observed_frequency is None


def test_compute_calibration_perfect_probability_one_stays_in_last_bin():
    """p=1.0 exact ar cadea in bin_idx=n_bins (10) fara clamp — trebuie
    sa ramana in ultimul bin valid (9)."""
    rows = [_row(1.0, 0.0, 0.0, "H")]
    bins = compute_calibration(rows, n_bins=10)
    last_bin = next(b for b in bins if b.outcome == "H" and b.bin_index == 9)
    assert last_bin.n == 1


# ── build_evaluation_report ─────────────────────────────────────────────

def test_build_evaluation_report_groups_by_league(monkeypatch):
    import prediction_evaluation as pe

    rows = [
        _row(0.6, 0.3, 0.1, "H", league="Premier League"),
        _row(0.5, 0.3, 0.2, "D", league="MLS"),
    ]
    monkeypatch.setattr(pe, "get_predictions_with_results", lambda days_back=None: rows)

    report = pe.build_evaluation_report()

    assert report["n_total_rows"] == 2
    assert report["overall"].n == 2
    assert set(report["per_league"].keys()) == {"Premier League", "MLS"}
    assert report["per_league"]["Premier League"].n == 1
    assert report["per_league"]["MLS"].n == 1
    assert len(report["calibration"]) == 30


def test_build_evaluation_report_empty_data_does_not_crash(monkeypatch):
    import prediction_evaluation as pe

    monkeypatch.setattr(pe, "get_predictions_with_results", lambda days_back=None: [])

    report = pe.build_evaluation_report()

    assert report["n_total_rows"] == 0
    assert report["overall"].n == 0
    assert report["per_league"] == {}


def test_get_predictions_with_results_delegates_to_database_queries(monkeypatch):
    import database.queries as q
    import prediction_evaluation as pe

    captured = {}

    def fake(days_back=None):
        captured["days_back"] = days_back
        return [{"fake": "row"}]

    monkeypatch.setattr(q, "get_predictions_with_results", fake)

    result = pe.get_predictions_with_results(days_back=30)

    assert captured["days_back"] == 30
    assert result == [{"fake": "row"}]
