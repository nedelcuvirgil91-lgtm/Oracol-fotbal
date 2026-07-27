"""
================================================================================
FOOTBALL ORACLE — Capability Registry (ADR-034, Strat 2/6)
================================================================================
Module: provider_capabilities.py

Capability Registry este un registry declarativ și imuabil. Nu poate fi
modificat în runtime. Orice schimbare a capabilităților unui provider se
face prin modificarea registry-ului și, dacă schimbarea este incompatibilă,
prin incrementarea versiunii și actualizarea ADR-urilor relevante.

Capability Registry descrie capabilitățile MAXIME TEORETICE ale
providerului — nu dacă funcționează azi, pentru o ligă anume. Diferența e
intenționată: dacă API-Football poate tehnic servi `injuries`, rămâne listat
aici indiferent dacă o ligă specifică e blocată de plan (`"plan_restricted"`,
vezi mappings.py) — acel gen de disponibilitate REALĂ, per ligă, e
responsabilitatea League Mapping (Strat 3/6), nu a acestui registry.
Capability = ce POATE providerul. League Mapping = UNDE funcționează.

Acoperă exact toți providerii enumerați de ProviderRegistry
(provider_registry.py, PR1) — inclusiv ESPN și TheSportsDB, care nu
necesită credențiale (`requires_credentials=False`). Provider Registry e o
declarație de DOMENIU, independentă de key_manager.py — Capability Registry
o respectă la fel: „ce poate providerul" nu depinde de dacă are sau nu o
cheie API, e o proprietate a sursei de date, nu a infrastructurii de
autentificare.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class DataType(Enum):
    FIXTURES = "fixtures"
    ODDS = "odds"
    STANDINGS = "standings"
    STATISTICS = "statistics"
    LINEUPS = "lineups"
    PLAYER_RATINGS = "player_ratings"
    XG = "xg"
    H2H = "h2h"
    MANAGERS = "managers"
    INJURIES = "injuries"
    TRANSFERS = "transfers"


class CostClass(Enum):
    FREE_UNLIMITED = "free_unlimited"
    RATE_LIMITED = "rate_limited"
    MONTHLY_QUOTA = "monthly_quota"
    MONTHLY_QUOTA_STRICT = "monthly_quota_strict"
    PAID = "paid"


@dataclass(frozen=True)
class ProviderCapability:
    provider_id: str
    version: int
    data_types: frozenset[DataType]
    cost_class: CostClass
    cache_ttl_hours: Mapping[DataType, int]  # contract public — Mapping, nu MappingProxyType

    def __post_init__(self):
        # frozen=True tot permite mutatie pe un dict mutabil primit ca arg -
        # fortam MappingProxyType intern, indiferent ce s-a primit la construire.
        object.__setattr__(self, "cache_ttl_hours", MappingProxyType(dict(self.cache_ttl_hours)))


_CAPABILITIES: dict[str, ProviderCapability] = {
    "apifootball": ProviderCapability(
        provider_id="apifootball", version=1,
        # [REPARAT R4.1] DataType.ODDS eliminat - drift real intre declarat
        # si implementat, confirmat prin audit (§1/§16): nicio cale de cod nu
        # a apelat vreodata un endpoint de odds pe API-Football; sursa de
        # odds a proiectului ramane Odds API (Frozen, ADR-005/006).
        data_types=frozenset({DataType.FIXTURES, DataType.INJURIES, DataType.MANAGERS}),
        cost_class=CostClass.MONTHLY_QUOTA,
        cache_ttl_hours={DataType.FIXTURES: 1, DataType.INJURIES: 4, DataType.MANAGERS: 72},
    ),
    "sportapi": ProviderCapability(
        provider_id="sportapi", version=1,
        data_types=frozenset({DataType.FIXTURES, DataType.ODDS, DataType.STANDINGS, DataType.STATISTICS,
                               DataType.LINEUPS, DataType.PLAYER_RATINGS, DataType.XG,
                               DataType.H2H, DataType.MANAGERS}),
        cost_class=CostClass.MONTHLY_QUOTA_STRICT,
        cache_ttl_hours={DataType.FIXTURES: 168, DataType.STANDINGS: 168, DataType.ODDS: 24,
                          DataType.STATISTICS: 720, DataType.LINEUPS: 720, DataType.PLAYER_RATINGS: 720,
                          DataType.XG: 720, DataType.H2H: 720, DataType.MANAGERS: 720},
    ),
    "freelivefootball": ProviderCapability(
        provider_id="freelivefootball", version=1,
        data_types=frozenset({DataType.FIXTURES, DataType.STANDINGS, DataType.STATISTICS,
                               DataType.H2H, DataType.LINEUPS}),
        cost_class=CostClass.MONTHLY_QUOTA,
        cache_ttl_hours={DataType.FIXTURES: 1, DataType.STANDINGS: 12, DataType.STATISTICS: 2,
                          DataType.H2H: 48, DataType.LINEUPS: 1},
    ),
    "oddsapi": ProviderCapability(
        provider_id="oddsapi", version=1,
        data_types=frozenset({DataType.FIXTURES, DataType.ODDS}),
        cost_class=CostClass.MONTHLY_QUOTA,
        cache_ttl_hours={DataType.FIXTURES: 1, DataType.ODDS: 4},
    ),
    "footballdata": ProviderCapability(
        provider_id="footballdata", version=1,
        data_types=frozenset({DataType.FIXTURES, DataType.STANDINGS}),
        cost_class=CostClass.RATE_LIMITED,
        cache_ttl_hours={DataType.FIXTURES: 1, DataType.STANDINGS: 12},
    ),
    "weatherapi": ProviderCapability(
        # Nu e o sursa de date de fotbal - inregistrata aici DOAR ca sa
        # respecte completitudinea bidirectionala cu Provider Registry.
        # Niciun DataType curent nu se aplica - frozenset() gol,
        # intentionat, nu omisiune.
        provider_id="weatherapi", version=1,
        data_types=frozenset(),
        cost_class=CostClass.FREE_UNLIMITED,
        cache_ttl_hours={},
    ),
    "espn": ProviderCapability(
        provider_id="espn", version=1,
        data_types=frozenset({DataType.FIXTURES}),
        cost_class=CostClass.FREE_UNLIMITED,
        cache_ttl_hours={DataType.FIXTURES: 1},
    ),
    "thesportsdb": ProviderCapability(
        provider_id="thesportsdb", version=1,
        data_types=frozenset({DataType.FIXTURES}),
        cost_class=CostClass.FREE_UNLIMITED,
        cache_ttl_hours={DataType.FIXTURES: 1},
    ),
}

CAPABILITIES: Mapping[str, ProviderCapability] = MappingProxyType(_CAPABILITIES)


def get_capability(provider_id: str) -> ProviderCapability | None:
    return CAPABILITIES.get(provider_id)


def supports(provider_id: str, data_type: DataType) -> bool:
    cap = get_capability(provider_id)
    return cap is not None and data_type in cap.data_types
