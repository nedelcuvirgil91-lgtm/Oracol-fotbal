"""
================================================================================
FOOTBALL ORACLE — Provider Metrics Source (ADR-034, port pentru Strat 4/6)
================================================================================
Module: provider_metrics_source.py

Acesta e PORTUL (in sensul ports-and-adapters) prin care Health Monitor
(provider_health.py) citeste metrici brute despre providers, fara sa
cunoasca vreodata tehnologia de stocare din spate (Regula de Aur #4 —
niciun obiect de domeniu nu are voie sa cunoasca Supabase/Postgres/REST).

ProviderMetricsSource e o interfata abstracta. Singura implementare reala
azi e SupabaseProviderMetricsSource (provider_metrics_source_supabase.py),
dar provider_health.py nu importa niciodata acel modul direct — foloseste
exclusiv get_default_metrics_source() de AICI, care rezolva lazy adaptorul
concret. Lantul de dependinta e strict:

    provider_health -> provider_metrics_source -> provider_metrics_source_supabase

niciodata provider_health -> provider_metrics_source_supabase direct.

Read-only: acest port nu scrie niciodata metrici, doar le citeste.
================================================================================
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderMetricsRow:
    """O linie bruta de metrici, per (provider, endpoint) — asa cum sunt
    stocate azi in tabela provider_metrics (vezi supabase_client.py,
    record_provider_call/get_provider_metrics).

    [ADAUGAT ADR-041 Faza 2, Sprint 1.1 #1] `last_success`/`last_failure` —
    coloane deja scrise de `record_provider_call()` (ISO 8601 UTC, sau
    `None` daca nu s-a intamplat inca), doar neexpuse pana acum prin acest
    port. Ramase string-uri brute la acest nivel (nu `datetime`) — parsarea
    e responsabilitatea consumatorului (ex. Health Score pe ferestre
    24h/7zile, Sprint 1.1 #2), acest port ramane strict o oglinda fidela a
    randului din baza de date, fara logica suplimentara."""
    endpoint: str
    calls: int
    errors: int
    consecutive_failures: int
    avg_latency_ms: float | None
    last_success: str | None = None
    last_failure: str | None = None


class ProviderMetricsSource(ABC):
    """Interfata abstracta — orice sursa de metrici (Supabase azi, altceva
    maine) trebuie sa o implementeze. Niciun apelant nu are voie sa
    presupuna tehnologia din spate."""

    @abstractmethod
    def get_metrics_rows(self, provider_id: str) -> list[ProviderMetricsRow]:
        """Returneaza toate liniile de metrici pentru provider_id (una per
        endpoint distinct apelat). Lista goala daca nu exista niciun
        apel inregistrat sau sursa e indisponibila — niciodata None."""
        raise NotImplementedError


def get_default_metrics_source() -> ProviderMetricsSource:
    """Rezolva lazy implementarea concreta implicita (Supabase). Import
    intern, nu la nivel de modul — asa nu se incarca niciodata
    supabase_client.py doar prin faptul ca cineva a importat
    provider_metrics_source.py (sau provider_health.py, care importa doar
    de aici)."""
    from provider_metrics_source_supabase import get_default_metrics_source as _get_supabase_source
    return _get_supabase_source()
