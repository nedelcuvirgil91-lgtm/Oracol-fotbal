"""Teste pentru selection_engine_analytics.py (ADR-041 Faza 2, Sprint 1.1
#6) — fără rețea, funcții pure testate direct, tiparul din
test_shadow_selection_report.py."""
from __future__ import annotations

from provider_health_score import HealthScoreWindow
from selection_engine_analytics import (
    DecisionValidation, ValidationSummary,
    build_validation_report, compute_decision_validations,
    get_decision_validations, summarize_validations,
)


def _shadow_row(league="Romania SuperLiga", current="espn", recommended="sportapi",
                 decision_changed=True, data_type="fixtures"):
    return {
        "league": league, "data_type": data_type,
        "current_provider": current, "recommended_provider": recommended,
        "decision_changed": decision_changed,
    }


def _health(success_rate, provider_id="x"):
    return HealthScoreWindow(
        provider_id=provider_id, window_hours=24, total_calls=10,
        total_errors=0, success_rate=success_rate, avg_latency_ms=100.0,
    )


# ── compute_decision_validations ────────────────────────────────────────

def test_ignores_rows_where_decision_did_not_change():
    rows = [_shadow_row(decision_changed=False)]
    result = compute_decision_validations(rows, {})
    assert result == []


def test_ignores_rows_without_recommended_provider():
    rows = [_shadow_row(recommended=None, decision_changed=True)]
    result = compute_decision_validations(rows, {})
    assert result == []


def test_validated_true_when_recommended_has_better_success_rate():
    rows = [_shadow_row(current="espn", recommended="sportapi")]
    health = {"espn": _health(0.80), "sportapi": _health(0.95)}
    result = compute_decision_validations(rows, health)
    assert len(result) == 1
    assert result[0].validated is True
    assert result[0].current_success_rate_24h == 0.80
    assert result[0].recommended_success_rate_24h == 0.95


def test_validated_false_when_recommended_has_worse_success_rate():
    rows = [_shadow_row(current="espn", recommended="sportapi")]
    health = {"espn": _health(0.95), "sportapi": _health(0.80)}
    result = compute_decision_validations(rows, health)
    assert result[0].validated is False


def test_validated_false_when_success_rates_are_equal():
    """Egal nu confirma decizia -- strict "mai bun", nu "mai bun sau egal"."""
    rows = [_shadow_row(current="espn", recommended="sportapi")]
    health = {"espn": _health(0.90), "sportapi": _health(0.90)}
    result = compute_decision_validations(rows, health)
    assert result[0].validated is False


def test_validated_none_when_health_data_missing_for_either_provider():
    rows = [_shadow_row(current="espn", recommended="sportapi")]
    health = {"espn": _health(0.90)}  # sportapi lipsește
    result = compute_decision_validations(rows, health)
    assert result[0].validated is None


def test_validated_none_when_success_rate_itself_is_none():
    """Provider fara trafic in fereastra (total_calls=0) -> success_rate=None."""
    rows = [_shadow_row(current="espn", recommended="sportapi")]
    empty_health = HealthScoreWindow(provider_id="x", window_hours=24, total_calls=0,
                                      total_errors=0, success_rate=None, avg_latency_ms=None)
    health = {"espn": _health(0.90), "sportapi": empty_health}
    result = compute_decision_validations(rows, health)
    assert result[0].validated is None


def test_multiple_rows_processed_independently():
    rows = [
        _shadow_row(current="espn", recommended="sportapi"),
        _shadow_row(current="sportapi", recommended="footballdata", decision_changed=False),
        _shadow_row(current="footballdata", recommended="freelivefootball"),
    ]
    health = {"espn": _health(0.5), "sportapi": _health(0.9),
              "footballdata": _health(0.5), "freelivefootball": _health(0.9)}
    result = compute_decision_validations(rows, health)
    assert len(result) == 2  # al doilea rand e ignorat (decision_changed=False)


# ── summarize_validations ────────────────────────────────────────────────

def test_summarize_validations_empty():
    summary = summarize_validations([])
    assert summary == ValidationSummary(total_decisions=0, validated_count=0,
                                         contradicted_count=0, unknown_count=0)


def test_summarize_validations_counts_each_bucket():
    validations = [
        DecisionValidation("L", "fixtures", "a", "b", 0.5, 0.9, True),
        DecisionValidation("L", "fixtures", "a", "b", 0.9, 0.5, False),
        DecisionValidation("L", "fixtures", "a", "b", None, None, None),
    ]
    summary = summarize_validations(validations)
    assert summary.total_decisions == 3
    assert summary.validated_count == 1
    assert summary.contradicted_count == 1
    assert summary.unknown_count == 1


# ── get_decision_validations (dependinte injectate) ──────────────────────

def test_get_decision_validations_resolves_only_involved_providers():
    rows = [_shadow_row(current="espn", recommended="sportapi")]
    calls = []

    def _fake_health_fn(provider_id):
        calls.append(provider_id)
        return _health(0.8 if provider_id == "espn" else 0.95)

    result = get_decision_validations(shadow_rows=rows, health_score_fn=_fake_health_fn)
    assert sorted(calls) == ["espn", "sportapi"]
    assert len(result) == 1
    assert result[0].validated is True


def test_get_decision_validations_empty_when_no_changed_decisions():
    rows = [_shadow_row(decision_changed=False)]
    calls = []
    result = get_decision_validations(shadow_rows=rows, health_score_fn=lambda pid: calls.append(pid))
    assert result == []
    assert calls == []  # niciun provider de rezolvat -- 0 apeluri irosite


# ── build_validation_report ───────────────────────────────────────────────

def test_build_validation_report_empty():
    text = build_validation_report([])
    assert "Nicio decizie" in text


def test_build_validation_report_shows_summary_counts():
    validations = [
        DecisionValidation("Romania SuperLiga", "fixtures", "espn", "sportapi", 0.5, 0.9, True),
    ]
    text = build_validation_report(validations)
    assert "Decizii diferite analizate: 1" in text
    assert "Confirmate de Health Score 24h real:  1" in text
    assert "espn" in text and "sportapi" in text
