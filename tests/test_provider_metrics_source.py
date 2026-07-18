"""Teste pentru provider_metrics_source.py (ADR-034, PR4) — fără rețea."""
from __future__ import annotations

import pytest

from provider_metrics_source import ProviderMetricsRow, ProviderMetricsSource, get_default_metrics_source


def test_provider_metrics_row_is_frozen():
    row = ProviderMetricsRow(endpoint="fixtures", calls=1, errors=0,
                              consecutive_failures=0, avg_latency_ms=100.0)
    with pytest.raises(Exception):
        row.calls = 2  # type: ignore[misc]


def test_provider_metrics_source_is_abstract():
    with pytest.raises(TypeError):
        ProviderMetricsSource()  # type: ignore[abstract]


def test_get_default_metrics_source_returns_supabase_adapter_instance():
    """Rezolva lazy - dar rezultatul trebuie sa respecte portul (sa fie o
    instanta de ProviderMetricsSource)."""
    source = get_default_metrics_source()
    assert isinstance(source, ProviderMetricsSource)


def test_get_default_metrics_source_does_not_import_supabase_client_eagerly():
    """provider_metrics_source.py nu are voie sa importe supabase_client
    (nici direct, nici indirect la nivel de modul) - doar in interiorul
    functiei de rezolvare, si doar prin provider_metrics_source_supabase."""
    import provider_metrics_source
    assert "supabase_client" not in vars(provider_metrics_source)


def test_get_default_metrics_source_is_singleton_across_calls():
    a = get_default_metrics_source()
    b = get_default_metrics_source()
    assert a is b
