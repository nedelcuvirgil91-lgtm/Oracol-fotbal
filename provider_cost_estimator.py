"""
================================================================================
FOOTBALL ORACLE — Cost Estimate per Provider (ADR-041 Faza 2, Sprint 1.1 #4)
================================================================================
Module: provider_cost_estimator.py

Nu inventează niciun preț în $ — niciun provider din proiect nu are azi o
rată monetară reală documentată (toți sunt planuri gratuite cu cotă,
`CostClass` din `provider_capabilities.py` confirmă asta explicit:
`FREE_UNLIMITED`/`MONTHLY_QUOTA`/`MONTHLY_QUOTA_STRICT`/`RATE_LIMITED`,
niciun `PAID`). „Cost" înseamnă aici, în primul rând, CONSUM DE COTĂ — un
proxy real, măsurabil, pentru cât de „scump" e un provider față de limita
lui gratuită, plus o proiecție de epuizare. Un cost monetar (`rate_per_call`)
e expus DOAR dacă a fost configurat explicit (`provider_cost_rates` în
`model_config`) — niciodată presupus (Regula #8, CLAUDE.md).

Reutilizează:
  - `ProviderRegistry.get_quota_status()` — deja folosit de
    `provider_health._quota_remaining_pct()` — pentru starea CURENTĂ de
    cotă, nu o citire nouă/paralelă.
  - `provider_call_log_source` (Sprint 1.1 #2) — pentru volumul REAL de
    apeluri dintr-o fereastră de timp, necesar pentru proiecția de
    epuizare (rată de consum × cotă rămasă).

Agregare determinist funcțională (`compute_cost_estimate`) — accesorii de
conveniență (`get_cost_estimate`) rezolvă dependințele implicite prin
import leneș, exact tiparul deja folosit de
`get_default_metrics_source()`/`get_default_call_log_source()`.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass

from provider_call_log_source import ProviderCallLogSource, get_default_call_log_source
from provider_registry import ProviderRegistry, get_provider_registry


@dataclass(frozen=True)
class CostEstimate:
    provider_id: str
    window_hours: int
    calls_in_window: int
    quota_limit: int | None                       # None daca providerul n-are concept de cota
    quota_used_pct: float | None                   # starea CURENTA (nu din fereastra) a cheii active
    projected_hours_to_exhaustion: float | None     # None daca fara cota, sau fara trafic in fereastra
    rate_per_call: float | None                     # $ per apel, DOAR daca configurat explicit
    estimated_cost: float | None                    # calls_in_window * rate_per_call, None daca rate necunoscut


def _quota_snapshot(registry: ProviderRegistry, provider_id: str) -> tuple[int | None, float | None]:
    """(quota_limit, quota_used_pct) din cheia „activă" (cea cu cel mai mic
    % folosit — identică logica din `key_manager._get_active_key()`, prima
    cheie ne-epuizată câștigă). `None, None` dacă providerul n-are concept
    de cotă (fără credențiale) sau nicio cheie configurată."""
    status = registry.get_quota_status(provider_id)
    if status is None:
        return None, None
    keys = status.get("keys", [])
    if not keys:
        return None, None
    best = min(keys, key=lambda k: k["pct"])
    return best.get("limit"), best.get("pct")


def compute_cost_estimate(
    provider_id: str, window_hours: int, calls_in_window: int,
    quota_limit: int | None, quota_used_pct: float | None,
    rate_per_call: float | None = None,
) -> CostEstimate:
    """Funcție pură — nicio citire externă aici, doar agregare peste ce
    primește (Regula de Aur #4)."""
    projected_hours = None
    if quota_limit is not None and quota_used_pct is not None and window_hours > 0:
        calls_per_hour = calls_in_window / window_hours
        if calls_per_hour > 0:
            remaining_calls = quota_limit * (1.0 - quota_used_pct / 100.0)
            projected_hours = max(0.0, remaining_calls) / calls_per_hour

    estimated_cost = None
    if rate_per_call is not None:
        estimated_cost = calls_in_window * rate_per_call

    return CostEstimate(
        provider_id=provider_id, window_hours=window_hours, calls_in_window=calls_in_window,
        quota_limit=quota_limit, quota_used_pct=quota_used_pct,
        projected_hours_to_exhaustion=projected_hours,
        rate_per_call=rate_per_call, estimated_cost=estimated_cost,
    )


def _default_rate_per_call(provider_id: str) -> float | None:
    """Config opțional (`model_config`, cheia `provider_cost_rates`) — $ per
    apel, populat DOAR dacă utilizatorul îl configurează explicit. Import
    leneș — modulul rămâne fără dependință de `supabase_client` la nivel de
    import (Regula de Aur #4); doar acest accesor de conveniență o atinge,
    exact tiparul deja folosit de `get_default_call_log_source()`."""
    try:
        import supabase_client as _sb
        cfg = _sb.load_config({"provider_cost_rates": {}})
        rates = cfg.get("provider_cost_rates") or {}
        value = rates.get(provider_id)
        return float(value) if value is not None else None
    except Exception:
        return None


def get_cost_estimate(
    provider_id: str, window_hours: int, *,
    registry: ProviderRegistry | None = None,
    call_log_source: ProviderCallLogSource | None = None,
    rate_per_call: float | None = None,
) -> CostEstimate:
    registry = registry or get_provider_registry()
    call_log_source = call_log_source or get_default_call_log_source()
    if rate_per_call is None:
        rate_per_call = _default_rate_per_call(provider_id)

    rows = call_log_source.get_calls_since(provider_id, window_hours)
    quota_limit, quota_used_pct = _quota_snapshot(registry, provider_id)

    return compute_cost_estimate(
        provider_id, window_hours, len(rows),
        quota_limit, quota_used_pct, rate_per_call=rate_per_call,
    )
