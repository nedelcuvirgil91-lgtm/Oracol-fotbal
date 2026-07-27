"""Teste pentru provider_call_log_source_supabase.py (ADR-041 Faza 2) —
fără rețea, Supabase e mock-uit prin monkeypatch pe modulul supabase_client,
tipar identic cu test_provider_metrics_source_supabase.py."""
from __future__ import annotations

from provider_call_log_source import ProviderCallLogRow
from provider_call_log_source_supabase import SupabaseProviderCallLogSource, get_default_call_log_source


def test_get_calls_since_maps_rows_correctly(monkeypatch):
    def _fake_get_provider_call_log(provider, hours):
        assert provider == "sportapi"
        assert hours == 24
        return [
            {"provider": "sportapi", "endpoint": "fixtures", "success": True,
             "http_status": 200, "failure_reason": None, "cache_hit": False,
             "latency_ms": 120.0, "called_at": "2026-07-28T10:00:00+00:00"},
            {"provider": "sportapi", "endpoint": "odds", "success": False,
             "http_status": 429, "failure_reason": "quota", "cache_hit": False,
             "latency_ms": 30000.0, "called_at": "2026-07-28T09:00:00+00:00"},
        ]

    import supabase_client as _sb
    monkeypatch.setattr(_sb, "get_provider_call_log", _fake_get_provider_call_log)

    source = SupabaseProviderCallLogSource()
    rows = source.get_calls_since("sportapi", 24)
    assert len(rows) == 2
    assert all(isinstance(r, ProviderCallLogRow) for r in rows)
    assert rows[0].success is True and rows[0].http_status == 200
    assert rows[1].success is False and rows[1].http_status == 429 and rows[1].failure_reason == "quota"


def test_get_calls_since_empty_list_when_no_rows(monkeypatch):
    import supabase_client as _sb
    monkeypatch.setattr(_sb, "get_provider_call_log", lambda provider, hours: [])

    source = SupabaseProviderCallLogSource()
    assert source.get_calls_since("nu-exista", 24) == []


def test_get_calls_since_degrades_gracefully_when_supabase_raises(monkeypatch):
    import supabase_client as _sb

    def _raise(provider, hours):
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr(_sb, "get_provider_call_log", _raise)

    source = SupabaseProviderCallLogSource()
    assert source.get_calls_since("sportapi", 24) == []


def test_get_calls_since_defaults_missing_fields_gracefully(monkeypatch):
    def _fake_get_provider_call_log(provider, hours):
        return [{"provider": "sportapi", "endpoint": "fixtures", "success": True}]

    import supabase_client as _sb
    monkeypatch.setattr(_sb, "get_provider_call_log", _fake_get_provider_call_log)

    source = SupabaseProviderCallLogSource()
    rows = source.get_calls_since("sportapi", 24)
    assert rows[0].http_status is None
    assert rows[0].failure_reason is None
    assert rows[0].cache_hit is False
    assert rows[0].latency_ms is None


def test_get_default_call_log_source_is_singleton():
    a = get_default_call_log_source()
    b = get_default_call_log_source()
    assert a is b
