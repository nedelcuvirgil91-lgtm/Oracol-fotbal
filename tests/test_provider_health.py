"""Teste pentru provider_health.py (ADR-034, PR4) — fără rețea, izolate prin
fakes injectate (ProviderRegistry fake + ProviderMetricsSource fake), fără
nicio dependință de Supabase sau key_manager reale."""
from __future__ import annotations

import pytest

from provider_health import ProviderHealth, get_provider_health
from provider_metrics_source import ProviderMetricsRow, ProviderMetricsSource
from provider_registry import ProviderRegistry, ProviderRecord


_FAKE_PROVIDERS = (
    ProviderRecord("alpha", "Alpha Provider", requires_credentials=True),
    ProviderRecord("beta", "Beta Provider (public)", requires_credentials=False),
)


class _FakeKeyManager:
    def is_available(self, provider_id):
        return provider_id == "alpha"

    def get_headers(self, provider_id):
        return None

    def record_request(self, provider_id):
        pass

    def get_status(self):
        return {
            "month": "2026-07",
            "providers": {
                "alpha": {
                    "name": "Alpha Provider",
                    "keys": [
                        {"label": "Alpha-Key1", "used": 80, "limit": 100, "remaining": 20,
                         "pct": 80.0, "status": "warning", "icon": "🟡"},
                    ],
                    "status": "ok",
                },
            },
        }


class _FakeMetricsSource(ProviderMetricsSource):
    def __init__(self, rows_by_provider: dict[str, list[ProviderMetricsRow]]):
        self._rows_by_provider = rows_by_provider

    def get_metrics_rows(self, provider_id):
        return self._rows_by_provider.get(provider_id, [])


def _registry() -> ProviderRegistry:
    return ProviderRegistry(key_manager=_FakeKeyManager(), providers=_FAKE_PROVIDERS)


def test_returns_none_for_unknown_provider():
    reg = _registry()
    source = _FakeMetricsSource({})
    assert get_provider_health("gamma-nu-exista", registry=reg, metrics_source=source) is None


def test_available_delegates_to_registry():
    reg = _registry()
    source = _FakeMetricsSource({})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)
    assert health.available is True

    health_beta = get_provider_health("beta", registry=reg, metrics_source=source)
    assert health_beta.available is True  # keyless, mereu disponibil


def test_reliability_none_when_no_calls_recorded():
    reg = _registry()
    source = _FakeMetricsSource({})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)
    assert health.total_calls == 0
    assert health.total_errors == 0
    assert health.reliability is None
    assert health.avg_latency_ms is None
    assert health.consecutive_failures == 0


def test_reliability_computed_from_aggregated_calls_and_errors():
    rows = [
        ProviderMetricsRow(endpoint="fixtures", calls=8, errors=2, consecutive_failures=1, avg_latency_ms=100.0),
        ProviderMetricsRow(endpoint="odds", calls=2, errors=0, consecutive_failures=0, avg_latency_ms=200.0),
    ]
    reg = _registry()
    source = _FakeMetricsSource({"alpha": rows})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)

    assert health.total_calls == 10
    assert health.total_errors == 2
    assert health.reliability == pytest.approx(0.8)  # 1 - 2/10


def test_consecutive_failures_is_max_across_rows_not_sum():
    rows = [
        ProviderMetricsRow(endpoint="fixtures", calls=5, errors=5, consecutive_failures=5, avg_latency_ms=None),
        ProviderMetricsRow(endpoint="odds", calls=5, errors=1, consecutive_failures=1, avg_latency_ms=None),
    ]
    reg = _registry()
    source = _FakeMetricsSource({"alpha": rows})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)
    assert health.consecutive_failures == 5  # max(5, 1), nu 6


def test_avg_latency_is_weighted_by_calls():
    rows = [
        ProviderMetricsRow(endpoint="fixtures", calls=8, errors=0, consecutive_failures=0, avg_latency_ms=100.0),
        ProviderMetricsRow(endpoint="odds", calls=2, errors=0, consecutive_failures=0, avg_latency_ms=200.0),
    ]
    reg = _registry()
    source = _FakeMetricsSource({"alpha": rows})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)
    # (8*100 + 2*200) / 10 = 120.0
    assert health.avg_latency_ms == pytest.approx(120.0)


def test_avg_latency_ignores_rows_without_latency():
    rows = [
        ProviderMetricsRow(endpoint="fixtures", calls=5, errors=0, consecutive_failures=0, avg_latency_ms=None),
        ProviderMetricsRow(endpoint="odds", calls=5, errors=0, consecutive_failures=0, avg_latency_ms=150.0),
    ]
    reg = _registry()
    source = _FakeMetricsSource({"alpha": rows})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)
    assert health.avg_latency_ms == pytest.approx(150.0)


def test_avg_latency_none_when_no_row_has_latency():
    rows = [
        ProviderMetricsRow(endpoint="fixtures", calls=5, errors=0, consecutive_failures=0, avg_latency_ms=None),
    ]
    reg = _registry()
    source = _FakeMetricsSource({"alpha": rows})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)
    assert health.avg_latency_ms is None


def test_quota_remaining_pct_for_credentialed_provider():
    reg = _registry()
    source = _FakeMetricsSource({})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)
    assert health.quota_remaining_pct == pytest.approx(20.0)  # 100 - 80


def test_quota_remaining_pct_none_for_keyless_provider():
    reg = _registry()
    source = _FakeMetricsSource({})
    health = get_provider_health("beta", registry=reg, metrics_source=source)
    assert health.quota_remaining_pct is None


def test_aggregation_is_deterministic_across_repeated_calls():
    """Regula ceruta explicit: aceeasi lista de metrici citita de 100 de ori
    trebuie sa produca ProviderHealth identic de 100 de ori - fara
    timestamp-uri, fara side effects, fara cache intern, fara actualizari."""
    rows = [
        ProviderMetricsRow(endpoint="fixtures", calls=8, errors=2, consecutive_failures=1, avg_latency_ms=100.0),
        ProviderMetricsRow(endpoint="odds", calls=2, errors=0, consecutive_failures=0, avg_latency_ms=200.0),
    ]
    reg = _registry()
    source = _FakeMetricsSource({"alpha": rows})

    results = [get_provider_health("alpha", registry=reg, metrics_source=source) for _ in range(100)]
    assert all(r == results[0] for r in results)


def test_provider_health_has_no_timestamp_fields():
    """Regresie directa impotriva reintroducerii last_success/last_failure -
    ProviderHealth descrie starea CURENTA, nu istoricul."""
    field_names = set(ProviderHealth.__dataclass_fields__.keys())
    assert "last_success" not in field_names
    assert "last_failure" not in field_names


def test_provider_health_is_frozen():
    reg = _registry()
    source = _FakeMetricsSource({})
    health = get_provider_health("alpha", registry=reg, metrics_source=source)
    with pytest.raises(Exception):
        health.total_calls = 999  # type: ignore[misc]


def test_get_provider_health_uses_default_registry_and_metrics_source_when_omitted():
    """Integrare reala minimala: fara argumente injectate, trebuie sa
    functioneze folosind singletonii impliciti (Registry real +
    get_default_metrics_source(), care se degradeaza gratios fara retea)."""
    health = get_provider_health("apifootball")
    assert health is not None
    assert health.provider_id == "apifootball"
