"""Teste pentru provider_metrics_source_supabase.py (ADR-034, PR4) — fără
rețea, Supabase e mock-uit prin monkeypatch pe modulul supabase_client
(nu se face niciun apel real)."""
from __future__ import annotations

from provider_metrics_source import ProviderMetricsRow
from provider_metrics_source_supabase import SupabaseProviderMetricsSource, get_default_metrics_source


def test_get_metrics_rows_filters_by_provider_id(monkeypatch):
    def _fake_get_provider_metrics():
        return [
            {"provider": "sportapi", "endpoint": "fixtures", "calls": 10, "errors": 1,
             "consecutive_failures": 0, "avg_latency_ms": 120.0},
            {"provider": "sportapi", "endpoint": "odds", "calls": 5, "errors": 0,
             "consecutive_failures": 0, "avg_latency_ms": 80.0},
            {"provider": "apifootball", "endpoint": "fixtures", "calls": 3, "errors": 3,
             "consecutive_failures": 3, "avg_latency_ms": None},
        ]

    import supabase_client as _sb
    monkeypatch.setattr(_sb, "get_provider_metrics", _fake_get_provider_metrics)

    source = SupabaseProviderMetricsSource()
    rows = source.get_metrics_rows("sportapi")
    assert len(rows) == 2
    assert all(isinstance(r, ProviderMetricsRow) for r in rows)
    assert {r.endpoint for r in rows} == {"fixtures", "odds"}


def test_get_metrics_rows_empty_list_for_unknown_provider(monkeypatch):
    import supabase_client as _sb
    monkeypatch.setattr(_sb, "get_provider_metrics", lambda: [])

    source = SupabaseProviderMetricsSource()
    assert source.get_metrics_rows("nu-exista") == []


def test_get_metrics_rows_degrades_gracefully_when_supabase_raises(monkeypatch):
    import supabase_client as _sb

    def _raise():
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr(_sb, "get_provider_metrics", _raise)

    source = SupabaseProviderMetricsSource()
    assert source.get_metrics_rows("sportapi") == []


def test_get_default_metrics_source_is_singleton():
    a = get_default_metrics_source()
    b = get_default_metrics_source()
    assert a is b
