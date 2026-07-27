"""
================================================================================
FOOTBALL ORACLE — Provider Call Log Source: adaptor Supabase (ADR-041 Faza 2)
================================================================================
Module: provider_call_log_source_supabase.py

Singurul fișier (alături de provider_metrics_source_supabase.py) căruia îi
este permis să cunoască Supabase pentru datele de sănătate a providerilor.
Implementează portul ProviderCallLogSource (provider_call_log_source.py)
peste supabase_client.get_provider_call_log(), care citește tabela
`provider_call_log` (scrisă deja de record_provider_call() — ADR-041
Faza 1/2, punct unic de scriere).

Importul către supabase_client e LAZY (în interiorul metodei), consistent
cu provider_metrics_source_supabase.py — degradare grațioasă: dacă Supabase
nu e disponibil, get_calls_since() returnează lista goală, nu aruncă.
================================================================================
"""
from __future__ import annotations

from provider_call_log_source import ProviderCallLogRow, ProviderCallLogSource


class SupabaseProviderCallLogSource(ProviderCallLogSource):
    def get_calls_since(self, provider_id: str, hours: int) -> list[ProviderCallLogRow]:
        try:
            import supabase_client as _sb
            raw_rows = _sb.get_provider_call_log(provider_id, hours)
        except Exception:
            return []

        return [
            ProviderCallLogRow(
                provider=row.get("provider", ""),
                endpoint=row.get("endpoint", ""),
                success=bool(row.get("success")),
                http_status=row.get("http_status"),
                failure_reason=row.get("failure_reason"),
                cache_hit=bool(row.get("cache_hit", False)),
                latency_ms=row.get("latency_ms"),
                called_at=row.get("called_at", ""),
            )
            for row in raw_rows
        ]


_default_instance: SupabaseProviderCallLogSource | None = None


def get_default_call_log_source() -> SupabaseProviderCallLogSource:
    global _default_instance
    if _default_instance is None:
        _default_instance = SupabaseProviderCallLogSource()
    return _default_instance
