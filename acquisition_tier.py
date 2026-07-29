"""
================================================================================
FOOTBALL ORACLE — Acquisition Tier (UDAL Faza 0, ADR-042)
================================================================================
Module: acquisition_tier.py

Enum minimal, independent — NU face parte din `provider_capabilities.py`
sau `scraper_registry.py`, ca ambele module să-l poată importa fără
dependință circulară (Capability Registry descrie provideri Tier API,
Scraper Registry descrie surse Tier HTTP_SCRAPER/PLAYWRIGHT — ambele au
nevoie de același enum de tier).

Ordinea de achiziție e o AXĂ STRICTĂ (ADR-042 §2, UDAL_ARCHITECTURE_SPEC
§1/§7): API → HTTP_SCRAPER → PLAYWRIGHT → Validare → Supabase, niciodată
inversată. Selection Engine-ul (`provider_selector.py`, neatins în Faza 0)
va grupa candidații întâi pe acest enum, înaintea scorului ponderat —
integrarea efectivă în Selection Engine rămâne pentru o fază ulterioară
(Faza 1+), Faza 0 introduce DOAR enum-ul, aditiv, fără nicio schimbare de
comportament în codul existent.
================================================================================
"""
from __future__ import annotations

from enum import Enum


class AcquisitionTier(Enum):
    API = "api"
    HTTP_SCRAPER = "http_scraper"
    PLAYWRIGHT = "playwright"


# Ordine explicită de precedență — index mai mic = încercat primul.
# Folosit de orice cod viitor care trebuie să compare doi candidați din
# tier-uri diferite (Faza 1+); Faza 0 doar declară ordinea, nu o consumă.
TIER_PRECEDENCE: tuple[AcquisitionTier, ...] = (
    AcquisitionTier.API,
    AcquisitionTier.HTTP_SCRAPER,
    AcquisitionTier.PLAYWRIGHT,
)


def tier_rank(tier: AcquisitionTier) -> int:
    """Index de precedență — mai mic înseamnă preferat mai devreme.
    Aruncă ValueError pentru un tier necunoscut (nu presupune un rang
    implicit — o eroare explicită e mai sigură decât o clasare tăcută greșită)."""
    return TIER_PRECEDENCE.index(tier)
