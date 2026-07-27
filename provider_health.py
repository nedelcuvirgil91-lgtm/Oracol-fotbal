"""
================================================================================
FOOTBALL ORACLE — Health Monitor (ADR-034, Strat 4/6)
================================================================================
Module: provider_health.py

Health Monitor CITEȘTE, NORMALIZEAZĂ și EXPUNE starea curentă de sănătate
a unui provider. NU decide nimic — nu alege provideri, nu calculează
scoruri de selecție (asta e Selection Engine, Strat 6/6, PR5), nu
declanșează fallback. Un consumator al acestui modul primește fapte
observate, nu o recomandare.

Dependințe la nivel de modul: DOAR provider_metrics_source (portul, nu
adaptorul Supabase) și provider_registry. Niciodată supabase_client,
niciodată provider_metrics_source_supabase — respectă Regula de Aur #4
(niciun obiect de domeniu nu cunoaște tehnologia de stocare din spate) și
lanțul strict de dependință:

    provider_health -> provider_metrics_source -> provider_metrics_source_supabase

Agregare STRICT determinist funcțională: aceeași listă de
ProviderMetricsRow produce mereu exact același ProviderHealth. Fără side
effects, fără cache intern, fără actualizări de stare — o simplă funcție
pură de agregare peste datele citite la momentul apelului.

[ADAUGAT ADR-041 Faza 2, Sprint 1.1 #1] `last_success`/`last_failure` SUNT
acum expuse (cel mai recent, pe toate endpoint-urile unui provider) — nu
mai sunt tratate ca "istoric" incompatibil cu "sănătate curentă": sunt ele
însele stare curentă ("ultima dată când a mers"/"ultima dată când n-a
mers"), exact tipul de fapt observat pe care acest modul îl expune deja
pentru alte câmpuri (`consecutive_failures`). Agregarea rămâne strict
determinist funcțională — `max()` lexicografic pe string-uri ISO 8601 UTC,
fără parsare la `datetime`, fără citire a ceasului (Regula de Aur #4).
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass

from provider_metrics_source import ProviderMetricsRow, ProviderMetricsSource, get_default_metrics_source
from provider_registry import ProviderRegistry, get_provider_registry


@dataclass(frozen=True)
class ProviderHealth:
    provider_id: str
    available: bool
    reliability: float | None          # 1 - errors/calls; None daca total_calls == 0
    avg_latency_ms: float | None       # medie ponderată cu numărul de apeluri; None daca nicio linie n-are latență
    quota_remaining_pct: float | None  # None daca providerul nu are concept de cotă
    consecutive_failures: int
    total_calls: int
    total_errors: int
    # [ADAUGAT ADR-041 Faza 2, Sprint 1.1 #1] cel mai recent succes/eșec, pe
    # toate endpoint-urile providerului — string ISO 8601 UTC, sau None daca
    # nu s-a întâmplat încă niciodată.
    last_success: str | None = None
    last_failure: str | None = None


def _aggregate_rows(rows: list[ProviderMetricsRow]) -> tuple[int, int, int, float | None]:
    """Funcție pură: (total_calls, total_errors, consecutive_failures_max, avg_latency_ms).
    Nicio linie -> (0, 0, 0, None)."""
    total_calls = sum(row.calls for row in rows)
    total_errors = sum(row.errors for row in rows)
    consecutive_failures = max((row.consecutive_failures for row in rows), default=0)

    latency_weight = sum(row.calls for row in rows if row.avg_latency_ms is not None)
    if latency_weight > 0:
        latency_sum = sum(
            row.avg_latency_ms * row.calls for row in rows if row.avg_latency_ms is not None
        )
        avg_latency_ms = latency_sum / latency_weight
    else:
        avg_latency_ms = None

    return total_calls, total_errors, consecutive_failures, avg_latency_ms


def _latest_timestamp(values: list[str | None]) -> str | None:
    """Cel mai recent timestamp ISO 8601 UTC dintr-o listă (poate conține
    `None`) — comparație lexicografică, validă pentru ISO 8601 cu format
    consistent (exact ce scrie `record_provider_call()`, `datetime.now
    (timezone.utc).isoformat()`). `None` dacă toate valorile sunt `None`."""
    present = [v for v in values if v is not None]
    return max(present) if present else None


def _quota_remaining_pct(registry: ProviderRegistry, provider_id: str) -> float | None:
    """Cea mai buna cheie disponibila determina cota ramasa reala a
    providerului — daca ORICE cheie mai are loc, providerul tot poate
    servi (asa se comporta si _get_active_key() din key_manager.py:
    prima cheie ne-epuizata castiga). None daca providerul n-are deloc
    concept de cota (fara credentiale sau necunoscut)."""
    status = registry.get_quota_status(provider_id)
    if status is None:
        return None
    keys = status.get("keys", [])
    if not keys:
        return None
    return max(100.0 - key["pct"] for key in keys)


def get_provider_health(
    provider_id: str,
    registry: ProviderRegistry | None = None,
    metrics_source: ProviderMetricsSource | None = None,
) -> ProviderHealth | None:
    registry = registry or get_provider_registry()
    record = registry.get_provider(provider_id)
    if record is None:
        return None

    metrics_source = metrics_source or get_default_metrics_source()
    rows = metrics_source.get_metrics_rows(provider_id)

    total_calls, total_errors, consecutive_failures, avg_latency_ms = _aggregate_rows(rows)
    reliability = None if total_calls == 0 else 1.0 - (total_errors / total_calls)

    return ProviderHealth(
        provider_id=provider_id,
        available=registry.is_available(provider_id),
        reliability=reliability,
        avg_latency_ms=avg_latency_ms,
        quota_remaining_pct=_quota_remaining_pct(registry, provider_id),
        consecutive_failures=consecutive_failures,
        total_calls=total_calls,
        total_errors=total_errors,
        last_success=_latest_timestamp([row.last_success for row in rows]),
        last_failure=_latest_timestamp([row.last_failure for row in rows]),
    )
