"""
================================================================================
FOOTBALL ORACLE — Provider Call Log Source (ADR-041 Faza 2, port)
================================================================================
Module: provider_call_log_source.py

Portul (ports-and-adapters) prin care Health Score pe ferestre
(provider_health_score.py) citește evenimente brute per-apel, fără să
cunoască vreodată tehnologia de stocare din spate (Regula de Aur #4 —
niciun obiect de domeniu nu are voie să cunoască Supabase/Postgres/REST).

Distinct de `provider_metrics_source.py` — acela citește starea CUMULATIVĂ
all-time (o linie per (provider, endpoint), actualizată in-place);
acesta citește EVENIMENTE (o linie per apel real, cu timestamp), sursa
necesară pentru orice fereastră de timp (24h/7zile — Sprint 1.1 #2) sau
breakdown per tip de eroare (Sprint 1.1 #3). Cele două porturi coexistă
deliberat — `provider_metrics` rămâne EXACT cum era (cache agregat),
`provider_call_log` e aditiv.

Lanțul de dependință e strict, identic tiparul deja stabilit:

    provider_health_score -> provider_call_log_source -> provider_call_log_source_supabase

niciodată provider_health_score -> provider_call_log_source_supabase direct.

Read-only: acest port nu scrie niciodată — scrierea trăiește exclusiv în
`supabase_client.record_provider_call()` (punct unic, ADR-041 Faza 1).
================================================================================
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCallLogRow:
    """O linie brută din `provider_call_log` — un apel HTTP real. Câmpurile
    reflectă fidel schema tabelei (aprobată explicit, proprietar produs,
    ADR-041 Faza 2): `http_status`/`failure_reason` nu sunt un enum închis
    (deliberat — orice tip nou de eroare se poate analiza fără migrare
    nouă), `cache_hit` servește cost estimation (Sprint 1.1 #4), nu Health
    Score. `called_at` rămâne string ISO 8601 UTC brut (nu `datetime`) —
    identic convenția deja folosită de `last_success`/`last_failure` în
    `provider_metrics_source.py`; parsarea, dacă e nevoie, e a
    consumatorului."""
    provider: str
    endpoint: str
    success: bool
    http_status: int | None
    failure_reason: str | None
    cache_hit: bool
    latency_ms: float | None
    called_at: str


class ProviderCallLogSource(ABC):
    """Interfață abstractă — orice sursă de evenimente (Supabase azi,
    altceva mâine) trebuie să o implementeze."""

    @abstractmethod
    def get_calls_since(self, provider_id: str, hours: int) -> list[ProviderCallLogRow]:
        """Toate apelurile pentru `provider_id` din ultimele `hours` ore.
        Lista goală dacă nu există niciun apel în fereastră sau sursa e
        indisponibilă — niciodată `None` (Regula #8, CLAUDE.md)."""
        raise NotImplementedError


def get_default_call_log_source() -> ProviderCallLogSource:
    """Rezolvă lazy implementarea concretă implicită (Supabase). Import
    intern, nu la nivel de modul — identic tiparul din
    `provider_metrics_source.get_default_metrics_source()`."""
    from provider_call_log_source_supabase import get_default_call_log_source as _get_supabase_source
    return _get_supabase_source()
