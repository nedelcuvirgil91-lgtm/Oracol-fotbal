"""
================================================================================
FOOTBALL ORACLE — Health Score pe ferestre (ADR-041 Faza 2, Sprint 1.1 #2)
================================================================================
Module: provider_health_score.py

Health Score CITEȘTE, NORMALIZEAZĂ și EXPUNE sănătatea unui provider pe o
FEREASTRĂ de timp (24h, 7 zile) — distinct de `provider_health.py`
(`ProviderHealth`), care rămâne starea cumulativă ALL-TIME, neschimbată.
Cele două module coexistă deliberat, exact cum `provider_call_log` (per
eveniment) coexistă cu `provider_metrics` (agregat) la nivel de date.

NU decide nimic — nu alege provideri, nu calculează scoruri de selecție
(Selection Engine, provider_selector.py, neatins de acest modul). Un
consumator primește fapte observate pe o fereastră, nu o recomandare.

Agregare STRICT determinist funcțională: filtrarea temporală ("ultimele N
ore față de acum") se face EXCLUSIV la nivelul adaptorului
(provider_call_log_source_supabase.py, care poate citi ceasul) — acest
modul primește mereu o listă deja filtrată de ProviderCallLogRow și doar o
agregă. Aceeași listă produce mereu exact același HealthScoreWindow (Regula
de Aur #4) — nicio citire de ceas aici.

Dependințe la nivel de modul: DOAR provider_call_log_source (portul, nu
adaptorul Supabase) — niciodată supabase_client,
provider_call_log_source_supabase.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass

from provider_call_log_source import ProviderCallLogRow, ProviderCallLogSource, get_default_call_log_source

WINDOW_24H_HOURS = 24
WINDOW_7D_HOURS = 24 * 7


@dataclass(frozen=True)
class HealthScoreWindow:
    provider_id: str
    window_hours: int
    total_calls: int
    total_errors: int
    success_rate: float | None    # None daca total_calls == 0
    avg_latency_ms: float | None  # None daca nicio linie n-are latenta


def compute_health_score_window(
    provider_id: str, window_hours: int, rows: list[ProviderCallLogRow],
) -> HealthScoreWindow:
    """Funcție pură — aceeași listă de rânduri produce mereu exact același
    rezultat. Nu presupune că `rows` conțin STRICT apeluri din fereastra
    declarată de `window_hours` — filtrarea temporală e responsabilitatea
    apelantului (get_health_score_window/adaptor), acest calcul doar
    agregă ce primește."""
    total_calls = len(rows)
    total_errors = sum(1 for r in rows if not r.success)
    success_rate = None if total_calls == 0 else 1.0 - (total_errors / total_calls)

    latencies = [r.latency_ms for r in rows if r.latency_ms is not None]
    avg_latency_ms = (sum(latencies) / len(latencies)) if latencies else None

    return HealthScoreWindow(
        provider_id=provider_id, window_hours=window_hours,
        total_calls=total_calls, total_errors=total_errors,
        success_rate=success_rate, avg_latency_ms=avg_latency_ms,
    )


def get_health_score_window(
    provider_id: str, window_hours: int, *, source: ProviderCallLogSource | None = None,
) -> HealthScoreWindow:
    source = source or get_default_call_log_source()
    rows = source.get_calls_since(provider_id, window_hours)
    return compute_health_score_window(provider_id, window_hours, rows)


def get_health_score_24h(provider_id: str, *, source: ProviderCallLogSource | None = None) -> HealthScoreWindow:
    return get_health_score_window(provider_id, WINDOW_24H_HOURS, source=source)


def get_health_score_7d(provider_id: str, *, source: ProviderCallLogSource | None = None) -> HealthScoreWindow:
    return get_health_score_window(provider_id, WINDOW_7D_HOURS, source=source)
