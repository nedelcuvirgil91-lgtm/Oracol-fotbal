"""
================================================================================
FOOTBALL ORACLE — Scraper Registry (UDAL Faza 0, ADR-042)
================================================================================
Module: scraper_registry.py

Oglindă structurală deliberată a `provider_capabilities.py` (ADR-034,
Capability Registry) — registry declarativ, imuabil, dar NU forțat în
același `dataclass`: metadatele Tier 1/2 (URL template, hartă de
selectori, politică de politețe, aprobare ToS) nu au echivalent la un
provider API și ar forța o formă artificială comună (UDAL_ARCHITECTURE_SPEC
v1.0, §8).

Scraper Registry descrie DOAR ce POATE tehnic o sursă de scraping — la fel
ca la Capability Registry, „ce poate" e separat de „unde funcționează azi"
(acela ar fi League Mapping, neatins aici).

[UDAL Faza 0] Acest registry a fost intenționat GOL de intrări reale în
Faza 0 — doar infrastructura (enum, contracte, tabele, flag-uri).

[UDAL Faza 1] O singură intrare, PILOT, GENERICĂ — `udal_pilot_generic_html_stats`.
Decizie explicită a proprietarului produsului: pilotul NU se proiectează
pentru un anumit site ("Nu vreau o sursă hardcodată... Pilotul nu trebuie
proiectat pentru un anumit site") — `target_url_template` e un placeholder
needereferențiat, `tos_reviewed=False` (rămâne așa până la
`POC_SCRAPER_SOURCE_01`, pas separat, după validarea pilotului — vezi
`docs/06_UDAL/SCRAPER_SOURCE_EVALUATION.md`). Pilotul rulează exclusiv
contra unui fixture HTML local (`docs/06_UDAL/fixtures/pilot_match_statistics.html`),
niciodată contra acestui URL placeholder.

`tos_reviewed` e un câmp BLOCANT, nu informativ: nicio sursă cu
`tos_reviewed=False` nu are voie să ruleze, nici măcar în shadow mode —
impus de `is_runnable()` de mai jos, nu doar documentat (UDAL_ARCHITECTURE_SPEC
v1.0, §16.1 — riscul legal/ToS rămâne decizie a proprietarului produsului,
per sursă, arhitectura doar impune verificarea explicită).
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from acquisition_tier import AcquisitionTier
from provider_capabilities import DataType


@dataclass(frozen=True)
class ScraperCapability:
    scraper_id: str
    version: int
    tier: AcquisitionTier  # HTTP_SCRAPER sau PLAYWRIGHT — API n-are ce căuta aici
    data_types: frozenset[DataType]
    # Parametrizat — {league}/{season}/{date} — niciodată un URL literal
    # per ligă în cod (cerința explicită „zero cod hardcodat pe competiții").
    target_url_template: str
    # Referință la rândul curent din tabela Supabase `scraper_selector_registry`
    # (versionată) — harta efectivă de selectori NU trăiește în Python,
    # tocmai ca să poată fi actualizată fără deploy de cod, condiție
    # necesară pentru detectarea de drift (viitoare, neimplementată).
    selector_map_ref: str
    politeness_policy_ref: str
    tos_reviewed: bool
    tos_reviewed_by: str | None
    tos_reviewed_at: datetime | None

    def __post_init__(self):
        if self.tier is AcquisitionTier.API:
            raise ValueError(
                f"{self.scraper_id!r}: tier=API nu e valid într-un Scraper "
                "Registry — provideri API aparțin exclusiv provider_capabilities.py."
            )
        object.__setattr__(self, "data_types", frozenset(self.data_types))


# [UDAL Faza 1] O singură intrare, pilot, generică — vezi docstring-ul
# modulului. `tos_reviewed=False` — rămâne așa până la `POC_SCRAPER_SOURCE_01`
# + aprobare separată, explicită, a proprietarului produsului.
_SCRAPERS: dict[str, ScraperCapability] = {
    "udal_pilot_generic_html_stats": ScraperCapability(
        scraper_id="udal_pilot_generic_html_stats", version=1,
        tier=AcquisitionTier.HTTP_SCRAPER,
        data_types=frozenset({DataType.STATISTICS}),
        # Placeholder needereferențiat — niciun cod nu are voie să facă
        # request real către acest URL (adaptorul Fazei 1 citește exclusiv
        # fixture-ul local, vezi generic_html_stats_scraper_adapter.py).
        target_url_template="https://neconfirmat.example.invalid/{league}/{season}/stats",
        selector_map_ref="udal_pilot_generic_html_stats-v1",
        politeness_policy_ref="udal_pilot_generic_html_stats-politeness-v1",
        tos_reviewed=False, tos_reviewed_by=None, tos_reviewed_at=None,
    ),
}

SCRAPERS: Mapping[str, ScraperCapability] = MappingProxyType(_SCRAPERS)


def get_capability(scraper_id: str) -> ScraperCapability | None:
    return SCRAPERS.get(scraper_id)


def supports(scraper_id: str, data_type: DataType) -> bool:
    cap = get_capability(scraper_id)
    return cap is not None and data_type in cap.data_types


def is_runnable(scraper_id: str) -> bool:
    """Gate blocant, nu informativ — o sursă fără ToS revizuit explicit nu
    rulează niciodată, nici măcar în shadow mode (UDAL_ARCHITECTURE_SPEC
    v1.0, §16.1). Un scraper inexistent nu e „runnable" (fail-closed, nu
    fail-open — diferit deliberat de `key_manager.is_available()`, care
    e fail-open pt provideri necunoscuți la nivel de cotă, nu la nivel
    legal)."""
    cap = get_capability(scraper_id)
    return cap is not None and cap.tos_reviewed is True
