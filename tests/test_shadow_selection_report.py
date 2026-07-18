"""Teste pentru shadow_selection_report.py — build_report() e pură (primește
rânduri deja citite, produce text), testabilă direct, fără rețea."""
from __future__ import annotations

from shadow_selection_report import build_readiness_verdict, build_report


def _row(league="Romania SuperLiga", current="espn", recommended="sportapi",
         decision_changed=True, observed_at="2026-07-19T10:00:00+00:00",
         current_score=0.5, recommended_score=0.9, deltas=None):
    return {
        "league": league, "data_type": "fixtures", "observed_at": observed_at,
        "current_provider": current, "recommended_provider": recommended,
        "decision_changed": decision_changed,
        "current_score": current_score, "recommended_score": recommended_score,
        "component_deltas": deltas,
    }


def test_build_report_empty_rows():
    text = build_report([])
    assert "Nicio observație înregistrată încă." in text


def test_build_report_counts_total_identical_different_unavailable():
    rows = [
        _row(current="espn", recommended="espn", decision_changed=False, deltas=None),
        _row(current="espn", recommended="sportapi", decision_changed=True,
             deltas={"coverage": 0.4, "quota": 0.08, "latency": -0.02, "reliability": 0.11}),
        _row(current="espn", recommended=None, decision_changed=False, deltas=None),
    ]
    text = build_report(rows)
    assert "Total recomandări: 3" in text
    assert "Identice cu providerul curent: 1" in text
    assert "Diferite față de providerul curent: 1" in text
    assert "Niciun candidat eligibil (provider_unavailable): 1" in text


def test_build_report_provider_distribution():
    rows = [
        _row(recommended="sportapi", decision_changed=True, deltas={"coverage": 0.1}),
        _row(recommended="sportapi", decision_changed=True, deltas={"coverage": 0.2}),
        _row(recommended="espn", decision_changed=False, deltas=None),
    ]
    text = build_report(rows)
    assert "sportapi" in text
    assert "espn" in text


def test_build_report_component_delta_average():
    rows = [
        _row(decision_changed=True, deltas={"coverage": 0.4}),
        _row(decision_changed=True, deltas={"coverage": 0.2}),
    ]
    text = build_report(rows)
    assert "coverage       +0.300" in text  # media (0.4+0.2)/2


def test_build_report_lists_all_differing_cases():
    rows = [
        _row(league="MLS", current="footballdata", recommended="oddsapi",
             decision_changed=True, deltas={"quota": 0.1}),
    ]
    text = build_report(rows)
    assert "MLS" in text
    assert "footballdata" in text
    assert "oddsapi" in text


def test_build_report_exit_criterion_not_met_with_small_sample():
    rows = [_row(decision_changed=False, recommended="espn", deltas=None)]
    text = build_report(rows)
    assert "Eșantion minim" in text
    assert "NOT READY" in text


def test_build_report_exit_criterion_match_rate_computed_correctly():
    # 19 identice, 1 diferita -> 95.0% -> exact la prag
    rows = [_row(decision_changed=False, recommended="espn", deltas=None) for _ in range(19)]
    rows.append(_row(decision_changed=True, recommended="sportapi", deltas={"coverage": 0.1}))
    text = build_report(rows)
    assert "95.0%" in text


# ── build_readiness_verdict — Shadow Readiness Report ───────────────────────

def test_readiness_verdict_no_data():
    text = build_readiness_verdict([])
    assert "NOT READY (fără date)" in text


def test_readiness_verdict_insufficient_sample():
    rows = [_row(decision_changed=False, recommended="espn", deltas=None)]
    text = build_readiness_verdict(rows)
    assert "❌ NOT READY — eșantion insuficient" in text


def test_readiness_verdict_low_match_rate_with_enough_sample():
    # 50 recomandari, 8 zile, dar doar 80% match rate -> esantion OK, match rate NU
    identical_rows = [_row(observed_at=f"2026-07-{10+i:02d}T10:00:00+00:00",
                            decision_changed=False, recommended="espn", deltas=None)
                       for i in range(8) for _ in range(5)]  # 40 identice, 8 zile
    different_rows = [_row(observed_at="2026-07-10T10:00:00+00:00", decision_changed=True,
                            recommended="sportapi", deltas={"coverage": 0.1}) for _ in range(10)]
    rows = identical_rows + different_rows  # 50 total, 40 identice = 80%
    text = build_readiness_verdict(rows)
    assert "eșantion" not in text.split("PR6 readiness:")[1].lower() or "match rate sub prag" in text
    assert "❌ NOT READY — match rate sub prag" in text


def test_readiness_verdict_partial_when_auto_criteria_met():
    identical_rows = [_row(observed_at=f"2026-07-{10+i:02d}T10:00:00+00:00",
                            decision_changed=False, recommended="espn", deltas=None)
                       for i in range(8) for _ in range(6)]  # 48 identice, 8 zile
    different_rows = [_row(observed_at="2026-07-10T10:00:00+00:00", decision_changed=True,
                            recommended="sportapi", deltas={"coverage": 0.1}) for _ in range(2)]
    rows = identical_rows + different_rows  # 50 total, 48 identice = 96%
    text = build_readiness_verdict(rows)
    assert "⚠️  PARȚIAL" in text
    assert "96.0%" in text


def test_readiness_verdict_never_fabricates_criterion_2_or_4():
    """Regresie centrala: verdictul nu are voie sa afirme 'Regresii
    functionale: 0' sau vreun check-mark pentru criteriile 2/4 - trebuie
    marcate explicit NEVERIFICAT, indiferent cat de bune sunt celelalte
    cifre."""
    identical_rows = [_row(observed_at=f"2026-07-{10+i:02d}T10:00:00+00:00",
                            decision_changed=False, recommended="espn", deltas=None)
                       for i in range(10) for _ in range(6)]
    text = build_readiness_verdict(identical_rows)
    assert "NEVERIFICAT" in text
    assert "Regresii funcționale:  0" not in text
    assert "Erori recorder:        0" not in text
    assert text.count("NEVERIFICAT") == 3  # regresii, erori recorder, consum de cereri


def test_readiness_verdict_is_deterministic():
    rows = [_row(decision_changed=True, deltas={"coverage": 0.1})]
    results = [build_readiness_verdict(rows) for _ in range(50)]
    assert all(r == results[0] for r in results)


def test_build_report_daily_evolution_section_present():
    rows = [
        _row(observed_at="2026-07-19T10:00:00+00:00", decision_changed=False, recommended="espn", deltas=None),
        _row(observed_at="2026-07-20T10:00:00+00:00", decision_changed=True, recommended="sportapi",
             deltas={"coverage": 0.1}),
    ]
    text = build_report(rows)
    assert "2026-07-19" in text
    assert "2026-07-20" in text


def test_build_report_is_pure_and_deterministic():
    rows = [
        _row(decision_changed=True, deltas={"coverage": 0.4, "quota": 0.08}),
        _row(decision_changed=False, recommended="espn", deltas=None),
    ]
    results = [build_report(rows) for _ in range(50)]
    assert all(r == results[0] for r in results)
