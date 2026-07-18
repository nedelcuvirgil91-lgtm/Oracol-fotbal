"""
================================================================================
FOOTBALL ORACLE — Provider Metrics Source: adaptor Supabase (ADR-034)
================================================================================
Module: provider_metrics_source_supabase.py

Singurul fisier din intreaga arhitectura de selectie a providerilor
(ADR-034) caruia ii este permis sa cunoasca Supabase. Implementeaza
portul ProviderMetricsSource (provider_metrics_source.py) peste
supabase_client.get_provider_metrics(), care citeste azi tabela
provider_metrics (scrisa deja de record_provider_call() din
oracle_api.py/football_providers.py — vezi ADR-003).

Importul catre supabase_client e LAZY (in interiorul metodei), nu la
nivel de modul — consistent cu restul codului legacy (key_manager.py
foloseste acelasi tipar) si cu principiul degradarii gratioase: daca
Supabase nu e disponibil, get_metrics_rows() returneaza lista goala,
nu arunca.
================================================================================
"""
from __future__ import annotations

from provider_metrics_source import ProviderMetricsRow, ProviderMetricsSource


class SupabaseProviderMetricsSource(ProviderMetricsSource):
    def get_metrics_rows(self, provider_id: str) -> list[ProviderMetricsRow]:
        try:
            import supabase_client as _sb
            raw_rows = _sb.get_provider_metrics()
        except Exception:
            return []

        return [
            ProviderMetricsRow(
                endpoint=row.get("endpoint", ""),
                calls=row.get("calls", 0) or 0,
                errors=row.get("errors", 0) or 0,
                consecutive_failures=row.get("consecutive_failures", 0) or 0,
                avg_latency_ms=row.get("avg_latency_ms"),
            )
            for row in raw_rows
            if row.get("provider") == provider_id
        ]


_default_instance: SupabaseProviderMetricsSource | None = None


def get_default_metrics_source() -> SupabaseProviderMetricsSource:
    global _default_instance
    if _default_instance is None:
        _default_instance = SupabaseProviderMetricsSource()
    return _default_instance
