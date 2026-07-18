"""
================================================================================
FOOTBALL ORACLE — League Mapping v2 (ADR-034, Strat 3/6)
================================================================================
Module: league_mapping.py

Extensie ADITIVĂ peste mappings.LEAGUE_PROVIDERS existent — NU înlocuire,
NU modificare. Zero linii schimbate în mappings.py. Expune un API de
CITIRE, unificat, peste stările existente, traduse către un vocabular
generalizat (`ProviderState`) + un nivel de încredere explicit
(`Confidence`, Regula 3 din ADR-034), separat de starea binară/enumerată.

Nu cunoaște denumirile legacy ale providerilor (`football_data`/`tsdb`/
`odds`/`freelf`/`api_football`) direct — le traduce EXCLUSIV prin
provider_id_translation.py (Regula de Aur #3: legacy izolat într-un
adaptor dedicat, niciodată propagat în straturile noi).

Nu integrează starea runtime reală (`_dead_keys`/`_freelf_exhausted` din
oracle_api.py) — DEAD_KEY/QUOTA_EXHAUSTED rămân în vocabular pentru
consumatori viitori (Health Monitor, PR4), dar nimic din acest fișier le
produce azi. Zero comportament nou, zero apel HTTP, zero schimbare de flux.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mappings import LEAGUE_PROVIDERS
from provider_id_translation import to_legacy


class ProviderState(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNTESTED = "untested"          # "nu am testat încă" — mappings.py: "necunoscut"
    UNKNOWN = "unknown"            # "nu știm" — distinct de UNTESTED, rezervat
    PLAN_RESTRICTED = "plan_restricted"
    DEAD_KEY = "dead_key"
    QUOTA_EXHAUSTED = "quota_exhausted"


class Confidence(Enum):
    CONFIRMED = "confirmed"
    DOCUMENTED = "documented"
    ASSUMED = "assumed"
    UNKNOWN = "unknown"


# Stările non-AVAILABLE (o afirmație negativă/restrictivă) nu pot purta o
# încredere "presupusă" — ori a fost confirmată real, ori rămâne necunoscută
# explicit. Regulă impusă la construcție, nu doar documentată.
_NON_AVAILABLE_ALLOWED_CONFIDENCE = frozenset({Confidence.CONFIRMED, Confidence.UNKNOWN})


def _translate_legacy_state(raw: object) -> ProviderState:
    if raw is True:
        return ProviderState.AVAILABLE
    if raw is False:
        return ProviderState.UNAVAILABLE
    if raw == "necunoscut":
        return ProviderState.UNTESTED
    if raw == "plan_restricted":
        return ProviderState.PLAN_RESTRICTED
    raise ValueError(f"Stare necunoscută, nemapată, în mappings.py: {raw!r}")


@dataclass(frozen=True)
class LeagueProviderState:
    league: str
    provider_id: str      # canonic, din provider_registry.py
    legacy_key: str        # cheia brută din mappings.py, doar pentru trasabilitate
    state: ProviderState
    confidence: Confidence

    def __post_init__(self) -> None:
        if self.state != ProviderState.AVAILABLE and self.confidence not in _NON_AVAILABLE_ALLOWED_CONFIDENCE:
            raise ValueError(
                f"confidence={self.confidence} invalid pentru state={self.state} "
                f"({self.league!r}, {self.provider_id!r}) — stările non-AVAILABLE "
                f"acceptă doar CONFIRMED sau UNKNOWN, niciodată ASSUMED/DOCUMENTED."
            )


# Declarație NOUĂ, separată — confidence nu există deloc în mappings.py azi.
# Populată DOAR pentru perechi verificate live, explicit — implicit UNKNOWN
# pentru orice altă pereche, onest, nu presupus.
_CONFIDENCE_OVERRIDES: dict[tuple[str, str], Confidence] = {
    ("Romania SuperLiga", "apifootball"): Confidence.CONFIRMED,  # league_id=283, verificat live 2026-07-17
}


def get_league_provider_state(league: str, provider_id: str) -> LeagueProviderState | None:
    definition = LEAGUE_PROVIDERS.get(league)
    if definition is None:
        return None
    legacy_key = to_legacy(provider_id)
    if legacy_key is None or legacy_key not in definition.supported:
        return None
    raw = definition.supported[legacy_key]
    state = _translate_legacy_state(raw)
    confidence = _CONFIDENCE_OVERRIDES.get((league, provider_id), Confidence.UNKNOWN)
    return LeagueProviderState(
        league=league, provider_id=provider_id, legacy_key=legacy_key,
        state=state, confidence=confidence,
    )
