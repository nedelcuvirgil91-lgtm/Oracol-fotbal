"""
================================================================================
FOOTBALL ORACLE — Sync Provider Manager (ADR-041, Faza 1)
================================================================================
Module: sync_provider_manager.py

Punctul unic de decizie "ce provider folosește Sync Layer-ul acum" pentru un
domeniu dat — niciun adaptor nu mai conține propria logică de fallback
(exact cerința explicită a Product Owner-ului).

Reutilizează integral Selection Engine-ul existent (ADR-034,
provider_selector.recommend_provider) — NU e un al doilea motor de scor.
Piesele noi, aditive, sunt strict: maparea domeniu -> (league, DataType),
lanțul static de urgență (folosit doar când flag-ul e dezactivat), și
alegerea presetului de ponderi LIVE/BACKFILL (ADR-041, fără nicio schimbare
a formulei de scor din provider_selector.py).

Flag implicit OFF (Regula #3, CLAUDE.md) — exact tiparul deja folosit de
shadow_config.py pentru Selection Engine shadow mode (ADR-034, PR5). Dacă
apare o problemă în producție, dezactivarea flagului revine INSTANT la
lanțul static, fără rollback de cod (cerință explicită, ADR-041).

Scop deliberat ÎNGUST azi: doar domeniile cu acoperire League Mapping v2
confirmată live intră pe calea Selection Engine (match_statistics, lineups,
managers). Team Form (owner încă nedecis — vezi Sprint 1 v6 §2) și Injuries
(restricția de sezon API-Football pe /injuries neverificată separat — vezi
Sprint 1 v6 §1) rămân STRICT pe lanțul static, ca să nu producă o decizie
falsă dintr-o presupunere nedovedită. Referees nu are un DataType propriu
în vocabularul ADR-034 (Regula 1) — extindere posibilă, decizie separată,
nu presupusă aici.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import supabase_client as sb
from provider_capabilities import DataType
from provider_selector import SELECTION_WEIGHTS, SELECTION_WEIGHTS_BACKFILL, recommend_provider

_DEFAULT_CONFIG = {"selection_engine_v2": False}


class Intent(Enum):
    LIVE = "LIVE"
    BACKFILL = "BACKFILL"


# Lanț static de urgență — folosit STRICT când selection_engine_v2 e
# dezactivat, sau ca fallback de ultimă instanță când niciun candidat nu
# trece filtrarea tare a Selection Engine-ului. Ordinea reflectă owner/
# fallback aprobate (Sprint 1 v6, §3) — nu se recalculează, e intenționat
# static, exact scopul unui kill-switch.
_STATIC_FALLBACK_CHAINS: dict[str, tuple[str, ...]] = {
    "match_statistics": ("soccerfootballinfo", "freelivefootball", "sportapi"),
    "lineups": ("soccerfootballinfo", "freelivefootball"),
    "managers": ("soccerfootballinfo", "apifootball"),
    "referees": ("soccerfootballinfo",),
    "team_form": ("freelivefootball", "footballdata", "soccerfootballinfo"),
    "injuries": ("apifootball",),
}

# Doar domenii cu DataType existent ÎN vocabularul ADR-034 și acoperire
# League Mapping v2 confirmată — vezi docstring-ul modulului.
_DOMAIN_TO_DATA_TYPE: dict[str, DataType] = {
    "match_statistics": DataType.STATISTICS,
    "lineups": DataType.LINEUPS,
    "managers": DataType.MANAGERS,
}


def is_selection_engine_v2_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("selection_engine_v2", False))


def _provider_priority_fn(provider_id: str) -> float:
    """[ADAUGAT ADR-041 Faza 1] "Priority ca valoare de config, nu cod"
    (Sprint 1 v6, §13, Faza 1 obligatorie) — injectat în
    `provider_selector.score_provider()`/`recommend_provider()` prin
    parametrul `priority_fn` (dependință explicită, Regula de Aur #5), NU
    citit direct în `provider_selector.py` (ar încălca "Dependency
    Direction" — acel modul nu importă niciodată `supabase_client`). Cheie
    nouă în același blob JSON (`model_config`, id=1) — `{}` implicit dacă
    lipsește -> 0.5 pentru orice provider, identic tie-breaker-ul static de
    azi (`_PROVIDER_PRIORITY = {}`), zero schimbare de comportament până la
    o configurare explicită (Regula #3, CLAUDE.md)."""
    cfg = sb.load_config({"provider_priority": {}})
    priorities = cfg.get("provider_priority") or {}
    return float(priorities.get(provider_id, 0.5))


@dataclass(frozen=True)
class ProviderChoice:
    provider_id: str | None
    via_selection_engine: bool
    weights_name: str | None
    weights_version: int | None
    reason: str


def fallback_chain(domain: str) -> tuple[str, ...]:
    """Accesor public al lanțului static COMPLET pentru un domeniu (Sprint 1
    v6, §3 — "Owner + Fallback"). `choose_provider()` întoarce un singur
    candidat "cel mai bun" pentru o pereche (domeniu, ligă) — un adaptor
    concret al Sync Layer-ului (ex. `sync/sync_match_statistics.py`) are însă
    nevoie de ordinea COMPLETĂ de încercare, ca să încerce providerul următor
    din lanț atunci când cel ales de `choose_provider()` nu produce date
    pentru un meci anume (ex. ligă neacoperită încă de Owner-ul nou) — fără
    asta, niciun provider existent nu ar mai rămâne accesibil ca fallback
    real, contrazicând cerința explicită de redundanță (Sprint 1 v6, §0)."""
    return _STATIC_FALLBACK_CHAINS.get(domain, ())


def choose_provider(domain: str, league: str, *, intent: Intent = Intent.LIVE) -> ProviderChoice:
    """Punct unic de decizie pentru Sync Layer — apelat de orice adaptor
    care are nevoie de un provider, niciodată calculat local de adaptor."""
    static_chain = _STATIC_FALLBACK_CHAINS.get(domain, ())

    if not is_selection_engine_v2_enabled():
        chosen = static_chain[0] if static_chain else None
        return ProviderChoice(
            provider_id=chosen, via_selection_engine=False,
            weights_name=None, weights_version=None,
            reason="selection_engine_v2 dezactivat — lanț static de urgență",
        )

    data_type = _DOMAIN_TO_DATA_TYPE.get(domain)
    if data_type is None:
        # Domeniu cunoscut lantului static (ex. team_form, injuries — decizii
        # deschise, vezi docstring-ul modulului), dar inca neacoperit de
        # Selection Engine — degradare gratioasa pe lantul static, nu None.
        chosen = static_chain[0] if static_chain else None
        return ProviderChoice(
            provider_id=chosen, via_selection_engine=False,
            weights_name=None, weights_version=None,
            reason=f"domeniu neacoperit de Selection Engine: {domain!r}",
        )
    if not static_chain:
        return ProviderChoice(
            provider_id=None, via_selection_engine=False,
            weights_name=None, weights_version=None,
            reason=f"domeniu necunoscut Provider Manager-ului: {domain!r}",
        )

    weights = SELECTION_WEIGHTS_BACKFILL if intent is Intent.BACKFILL else SELECTION_WEIGHTS
    weights_name = intent.value

    recommendation = recommend_provider(
        league, data_type, current_provider=static_chain[0], weights=weights,
        priority_fn=_provider_priority_fn,
    )
    if recommendation.recommended_provider is None:
        # Niciun candidat trece filtrarea tare a Selection Engine-ului —
        # cade pe lanțul static, nu pe None (degradare grațioasă, Regula #8).
        return ProviderChoice(
            provider_id=static_chain[0], via_selection_engine=False,
            weights_name=None, weights_version=None,
            reason="niciun candidat eligibil în Selection Engine — lanț static de urgență",
        )
    return ProviderChoice(
        provider_id=recommendation.recommended_provider,
        via_selection_engine=True,
        weights_name=weights_name, weights_version=weights.version,
        reason=f"Selection Engine ({weights_name} v{weights.version})",
    )
