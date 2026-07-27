"""Teste pentru provider_cost_estimator.py (ADR-041 Faza 2, Sprint 1.1 #4) —
fără rețea, izolate prin ProviderRegistry/ProviderCallLogSource fake."""
from __future__ import annotations

import pytest

from provider_call_log_source import ProviderCallLogRow, ProviderCallLogSource
from provider_cost_estimator import _quota_snapshot, compute_cost_estimate, get_cost_estimate


class _FakeRegistry:
    def __init__(self, quota_status_by_provider: dict[str, dict | None]):
        self._quota_status = quota_status_by_provider

    def get_quota_status(self, provider_id):
        return self._quota_status.get(provider_id)


class _FakeCallLogSource(ProviderCallLogSource):
    def __init__(self, rows_by_provider: dict[str, list[ProviderCallLogRow]]):
        self._rows_by_provider = rows_by_provider
        self.calls: list[tuple[str, int]] = []

    def get_calls_since(self, provider_id, hours):
        self.calls.append((provider_id, hours))
        return self._rows_by_provider.get(provider_id, [])


def _row():
    return ProviderCallLogRow(
        provider="alpha", endpoint="fixtures", success=True,
        http_status=200, failure_reason=None, cache_hit=False,
        latency_ms=100.0, called_at="2026-07-28T10:00:00+00:00",
    )


# ── _quota_snapshot ──────────────────────────────────────────────────────

def test_quota_snapshot_none_when_provider_has_no_quota_concept():
    reg = _FakeRegistry({"alpha": None})
    assert _quota_snapshot(reg, "alpha") == (None, None)


def test_quota_snapshot_none_when_no_keys():
    reg = _FakeRegistry({"alpha": {"keys": []}})
    assert _quota_snapshot(reg, "alpha") == (None, None)


def test_quota_snapshot_picks_key_with_lowest_pct_used():
    reg = _FakeRegistry({"alpha": {"keys": [
        {"limit": 100, "pct": 90.0}, {"limit": 200, "pct": 20.0},
    ]}})
    assert _quota_snapshot(reg, "alpha") == (200, 20.0)


# ── compute_cost_estimate (pur) ──────────────────────────────────────────

def test_compute_cost_estimate_no_quota_no_projection():
    result = compute_cost_estimate("alpha", 24, calls_in_window=10, quota_limit=None, quota_used_pct=None)
    assert result.projected_hours_to_exhaustion is None
    assert result.estimated_cost is None


def test_compute_cost_estimate_zero_calls_no_projection():
    """Fara trafic in fereastra -- rata de consum e 0, nu se poate proiecta
    o epuizare (ar da diviziune la 0 / un rezultat fals de "niciodata")."""
    result = compute_cost_estimate("alpha", 24, calls_in_window=0, quota_limit=100, quota_used_pct=50.0)
    assert result.projected_hours_to_exhaustion is None


def test_compute_cost_estimate_projects_exhaustion_correctly():
    # 24 apeluri in 24h -> 1 apel/h. Cota 100, 50% folosit -> 50 ramase.
    # Proiectie: 50 / 1 = 50h pana la epuizare.
    result = compute_cost_estimate("alpha", 24, calls_in_window=24, quota_limit=100, quota_used_pct=50.0)
    assert result.projected_hours_to_exhaustion == pytest.approx(50.0)


def test_compute_cost_estimate_already_exhausted_gives_zero_not_negative():
    result = compute_cost_estimate("alpha", 24, calls_in_window=24, quota_limit=100, quota_used_pct=100.0)
    assert result.projected_hours_to_exhaustion == 0.0


def test_compute_cost_estimate_with_rate_computes_monetary_cost():
    result = compute_cost_estimate("alpha", 24, calls_in_window=50, quota_limit=None,
                                    quota_used_pct=None, rate_per_call=0.002)
    assert result.estimated_cost == pytest.approx(0.1)


def test_compute_cost_estimate_without_rate_leaves_cost_none():
    result = compute_cost_estimate("alpha", 24, calls_in_window=50, quota_limit=None, quota_used_pct=None)
    assert result.estimated_cost is None
    assert result.rate_per_call is None


def test_compute_cost_estimate_is_pure_same_input_same_output():
    r1 = compute_cost_estimate("alpha", 24, 10, 100, 50.0, rate_per_call=0.01)
    r2 = compute_cost_estimate("alpha", 24, 10, 100, 50.0, rate_per_call=0.01)
    assert r1 == r2


def test_cost_estimate_is_frozen():
    result = compute_cost_estimate("alpha", 24, 0, None, None)
    with pytest.raises(Exception):
        result.calls_in_window = 999  # type: ignore[misc]


# ── get_cost_estimate (integrare, dependinte injectate) ──────────────────

def test_get_cost_estimate_delegates_with_correct_hours():
    registry = _FakeRegistry({"alpha": {"keys": [{"limit": 200, "pct": 10.0}]}})
    source = _FakeCallLogSource({"alpha": [_row(), _row()]})
    result = get_cost_estimate("alpha", 48, registry=registry, call_log_source=source, rate_per_call=0.0)
    assert source.calls == [("alpha", 48)]
    assert result.calls_in_window == 2
    assert result.quota_limit == 200
    assert result.quota_used_pct == 10.0


def test_get_cost_estimate_explicit_rate_overrides_config_lookup():
    registry = _FakeRegistry({"alpha": None})
    source = _FakeCallLogSource({"alpha": []})
    result = get_cost_estimate("alpha", 24, registry=registry, call_log_source=source, rate_per_call=0.5)
    assert result.rate_per_call == 0.5


def test_get_cost_estimate_falls_back_to_none_rate_without_supabase():
    """Fara rata explicita si fara Supabase configurat -- _default_rate_per_call
    degradeaza gratios la None, nu arunca."""
    registry = _FakeRegistry({"alpha": None})
    source = _FakeCallLogSource({"alpha": []})
    result = get_cost_estimate("alpha", 24, registry=registry, call_log_source=source)
    assert result.rate_per_call is None
    assert result.estimated_cost is None
