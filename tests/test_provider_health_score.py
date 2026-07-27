"""Teste pentru provider_health_score.py (ADR-041 Faza 2, Sprint 1.1 #2) —
fără rețea, izolate prin ProviderCallLogSource fake, tipar identic cu
test_provider_health.py."""
from __future__ import annotations

import pytest

from provider_call_log_source import ProviderCallLogRow, ProviderCallLogSource
from provider_health_score import (
    WINDOW_24H_HOURS, WINDOW_7D_HOURS,
    HealthScoreWindow, compute_health_score_window,
    get_health_score_24h, get_health_score_7d, get_health_score_window,
    ErrorBreakdown, compute_error_breakdown,
    get_error_breakdown_24h, get_error_breakdown_7d, get_error_breakdown_window,
)


class _FakeCallLogSource(ProviderCallLogSource):
    def __init__(self, rows_by_provider: dict[str, list[ProviderCallLogRow]]):
        self._rows_by_provider = rows_by_provider
        self.calls: list[tuple[str, int]] = []

    def get_calls_since(self, provider_id, hours):
        self.calls.append((provider_id, hours))
        return self._rows_by_provider.get(provider_id, [])


def _row(success=True, latency_ms=100.0):
    return ProviderCallLogRow(
        provider="alpha", endpoint="fixtures", success=success,
        http_status=200 if success else 500, failure_reason=None if success else "boom",
        cache_hit=False, latency_ms=latency_ms, called_at="2026-07-28T10:00:00+00:00",
    )


def test_compute_health_score_window_empty_rows():
    result = compute_health_score_window("alpha", 24, [])
    assert result == HealthScoreWindow(
        provider_id="alpha", window_hours=24, total_calls=0, total_errors=0,
        success_rate=None, avg_latency_ms=None,
    )


def test_compute_health_score_window_all_success():
    rows = [_row(success=True), _row(success=True)]
    result = compute_health_score_window("alpha", 24, rows)
    assert result.total_calls == 2
    assert result.total_errors == 0
    assert result.success_rate == 1.0


def test_compute_health_score_window_mixed_success_and_failure():
    rows = [_row(success=True), _row(success=False), _row(success=False)]
    result = compute_health_score_window("alpha", 24, rows)
    assert result.total_calls == 3
    assert result.total_errors == 2
    assert result.success_rate == pytest.approx(1.0 / 3.0)


def test_compute_health_score_window_avg_latency_ignores_missing_values():
    rows = [_row(latency_ms=100.0), _row(latency_ms=None), _row(latency_ms=200.0)]
    result = compute_health_score_window("alpha", 24, rows)
    assert result.avg_latency_ms == 150.0


def test_compute_health_score_window_avg_latency_none_when_no_row_has_latency():
    rows = [_row(latency_ms=None), _row(latency_ms=None)]
    result = compute_health_score_window("alpha", 24, rows)
    assert result.avg_latency_ms is None


def test_compute_health_score_window_is_pure_same_input_same_output():
    rows = [_row(success=True), _row(success=False)]
    r1 = compute_health_score_window("alpha", 24, rows)
    r2 = compute_health_score_window("alpha", 24, rows)
    assert r1 == r2


def test_get_health_score_window_delegates_to_source_with_correct_hours():
    source = _FakeCallLogSource({"alpha": [_row(), _row()]})
    result = get_health_score_window("alpha", 48, source=source)
    assert source.calls == [("alpha", 48)]
    assert result.window_hours == 48
    assert result.total_calls == 2


def test_get_health_score_24h_uses_24_hour_window():
    source = _FakeCallLogSource({"alpha": []})
    get_health_score_24h("alpha", source=source)
    assert source.calls == [("alpha", WINDOW_24H_HOURS)]
    assert WINDOW_24H_HOURS == 24


def test_get_health_score_7d_uses_168_hour_window():
    source = _FakeCallLogSource({"alpha": []})
    get_health_score_7d("alpha", source=source)
    assert source.calls == [("alpha", WINDOW_7D_HOURS)]
    assert WINDOW_7D_HOURS == 24 * 7


def test_health_score_window_is_frozen():
    result = compute_health_score_window("alpha", 24, [])
    with pytest.raises(Exception):
        result.total_calls = 999  # type: ignore[misc]


# ── Breakdown pe tip de eroare (Sprint 1.1 #3) ─────────────────────────────

def _failure_row(reason):
    return ProviderCallLogRow(
        provider="alpha", endpoint="fixtures", success=False,
        http_status=None, failure_reason=reason, cache_hit=False,
        latency_ms=None, called_at="2026-07-28T10:00:00+00:00",
    )


def test_compute_error_breakdown_empty_rows():
    result = compute_error_breakdown("alpha", 24, [])
    assert result == ErrorBreakdown(
        provider_id="alpha", window_hours=24, total_errors=0,
        quota=0, forbidden=0, timeout=0, upstream_5xx=0, other=0,
    )


def test_compute_error_breakdown_counts_each_known_reason():
    rows = [
        _failure_row("quota"), _failure_row("quota"),
        _failure_row("forbidden"),
        _failure_row("timeout"), _failure_row("timeout"), _failure_row("timeout"),
        _failure_row("upstream_5xx"),
    ]
    result = compute_error_breakdown("alpha", 24, rows)
    assert result.total_errors == 7
    assert result.quota == 2
    assert result.forbidden == 1
    assert result.timeout == 3
    assert result.upstream_5xx == 1
    assert result.other == 0


def test_compute_error_breakdown_unknown_reason_falls_into_other():
    """failure_reason NU e un enum inchis — orice valoare noua/necunoscuta
    (ex. 'network', 'other_error', sau chiar None) intra la 'other', nu se
    pierde din total_errors."""
    rows = [_failure_row("network"), _failure_row("other_error"), _failure_row(None)]
    result = compute_error_breakdown("alpha", 24, rows)
    assert result.total_errors == 3
    assert result.other == 3


def test_compute_error_breakdown_ignores_successful_rows():
    success_row = ProviderCallLogRow(
        provider="alpha", endpoint="fixtures", success=True,
        http_status=200, failure_reason=None, cache_hit=False,
        latency_ms=100.0, called_at="2026-07-28T10:00:00+00:00",
    )
    rows = [success_row, _failure_row("quota")]
    result = compute_error_breakdown("alpha", 24, rows)
    assert result.total_errors == 1
    assert result.quota == 1


def test_compute_error_breakdown_is_pure_same_input_same_output():
    rows = [_failure_row("quota"), _failure_row("timeout")]
    r1 = compute_error_breakdown("alpha", 24, rows)
    r2 = compute_error_breakdown("alpha", 24, rows)
    assert r1 == r2


def test_get_error_breakdown_window_delegates_to_source_with_correct_hours():
    source = _FakeCallLogSource({"alpha": [_failure_row("quota")]})
    result = get_error_breakdown_window("alpha", 48, source=source)
    assert source.calls == [("alpha", 48)]
    assert result.window_hours == 48
    assert result.quota == 1


def test_get_error_breakdown_24h_uses_24_hour_window():
    source = _FakeCallLogSource({"alpha": []})
    get_error_breakdown_24h("alpha", source=source)
    assert source.calls == [("alpha", WINDOW_24H_HOURS)]


def test_get_error_breakdown_7d_uses_168_hour_window():
    source = _FakeCallLogSource({"alpha": []})
    get_error_breakdown_7d("alpha", source=source)
    assert source.calls == [("alpha", WINDOW_7D_HOURS)]


def test_error_breakdown_is_frozen():
    result = compute_error_breakdown("alpha", 24, [])
    with pytest.raises(Exception):
        result.total_errors = 999  # type: ignore[misc]
