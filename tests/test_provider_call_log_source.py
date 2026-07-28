"""Teste pentru provider_call_log_source.py (ADR-041 Faza 2, port) — fără
rețea. Oglindește tests/test_provider_metrics_source.py, același tipar de
port (ABC + dataclass frozen + rezolvare lazy singleton)."""
from __future__ import annotations

import pytest

from provider_call_log_source import (
    ProviderCallLogRow,
    ProviderCallLogSource,
    get_default_call_log_source,
)


def test_provider_call_log_row_is_frozen():
    row = ProviderCallLogRow(
        provider="apifootball", endpoint="injuries", success=True,
        http_status=200, failure_reason=None, cache_hit=False,
        latency_ms=123.4, called_at="2026-07-28T04:00:00+00:00",
    )
    with pytest.raises(Exception):
        row.success = False  # type: ignore[misc]


def test_provider_call_log_source_is_abstract():
    with pytest.raises(TypeError):
        ProviderCallLogSource()  # type: ignore[abstract]


def test_get_default_call_log_source_returns_supabase_adapter_instance():
    """Rezolva lazy - dar rezultatul trebuie sa respecte portul (sa fie o
    instanta de ProviderCallLogSource)."""
    source = get_default_call_log_source()
    assert isinstance(source, ProviderCallLogSource)


def test_get_default_call_log_source_does_not_import_supabase_client_eagerly():
    """provider_call_log_source.py nu are voie sa importe supabase_client
    (nici direct, nici indirect la nivel de modul) - doar in interiorul
    functiei de rezolvare, si doar prin provider_call_log_source_supabase."""
    import provider_call_log_source
    assert "supabase_client" not in vars(provider_call_log_source)


def test_get_default_call_log_source_is_singleton_across_calls():
    a = get_default_call_log_source()
    b = get_default_call_log_source()
    assert a is b
