"""
================================================================================
FOOTBALL ORACLE — Scraper Adapter Base (UDAL Faza 0, ADR-042)
================================================================================
Module: scraper_adapter_base.py

Extinde `sync_adapter.SyncAdapter` (contract neschimbat — fetch/normalize/
validate/persist/coverage_check) cu exact ce e specific tier-urilor 1/2
(HTTP Scraper, Playwright), fără să redefinească nimic din contractul de
bază. Orice `*ScraperAdapter`/`*PlaywrightAdapter` concret (Faza 1+)
moștenește de aici, nu direct din `SyncAdapter`.

[UDAL Faza 0] Acest modul e STRICT contract — `fetch()` rămâne abstractă,
neimplementată. Nicio țintă reală de scraping nu există în Faza 0 (decizia
explicită a proprietarului produsului: „În această fază nu implementăm
scraping"). Clasa există ca infrastructură pe care Faza 1 o va folosi
pentru prima țintă pilot (statistici Romania SuperLiga, shadow-only).

Gate obligatoriu, impus structural — `preflight()` respinge orice
încercare de rulare pentru o sursă cu `tos_reviewed=False`
(scraper_registry.is_runnable()), INDIFERENT dacă apelantul verifică
singur asta — un adaptor concret nu poate ocoli acest gate fără să
suprascrie explicit `preflight()`, ceea ce ar fi o schimbare de
comportament vizibilă la code review, nu o omisiune tăcută.
================================================================================
"""
from __future__ import annotations

from abc import abstractmethod
from typing import Any

from acquisition_tier import AcquisitionTier
import scraper_registry
from sync_adapter import SyncAdapter


class ScraperPreflightError(Exception):
    """Ridicată de `preflight()` — sursa nu are voie să ruleze (ToS
    nerevizuit, sau nu e înregistrată deloc în Scraper Registry)."""


class ScraperAdapterBase(SyncAdapter):
    """Contract comun pentru Tier 1 (HTTP Scraper) și Tier 2 (Playwright).
    Nu implementează `fetch()` — rămâne per adaptor concret, exact ca la
    `SyncAdapter`. `persist()` rămâne de asemenea per adaptor concret,
    fără nicio deviere de la ownership-ul unic per coloană (ADR-036) —
    acest modul nu introduce niciun scriitor nou, doar orchestrează
    fetch/normalize/validate înaintea lui."""

    scraper_id: str
    tier: AcquisitionTier

    def preflight(self) -> None:
        """Verificare obligatorie înainte de orice `fetch()` — apelată
        explicit de orice orchestrator (Faza 1+), nu implicit din
        `fetch()` însuși (SyncAdapter.fetch() rămâne un contract simplu,
        fără efecte secundare ascunse)."""
        if not scraper_registry.is_runnable(self.scraper_id):
            raise ScraperPreflightError(
                f"{self.scraper_id!r}: nu poate rula — fie nu e înregistrat "
                "în Scraper Registry, fie tos_reviewed=False (UDAL_ARCHITECTURE_SPEC "
                "v1.0, §16.1 — decizie legală explicită necesară per sursă, "
                "niciodată presupusă)."
            )

    @abstractmethod
    def fetch(self, params: dict) -> Any | None:
        """[Faza 1+] Unicul punct de acces la sursa Tier 1/2 — trece prin
        Rate Limit / Politeness Manager (proiectat, neimplementat în Faza
        0), niciodată direct. Rămâne abstractă în Faza 0 — nicio
        implementare concretă nu există încă."""
        ...
