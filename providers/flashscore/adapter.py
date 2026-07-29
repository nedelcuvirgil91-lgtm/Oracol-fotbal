"""
================================================================================
FOOTBALL ORACLE — Flashscore Adapter (R-Sync-FLASH-01, ADR-042)
================================================================================
Module: providers/flashscore/adapter.py

Schelet — extinde `ScraperAdapterBase` (Faza 0), reutilizează
`_CssExtractionNormalizeMixin`/`_IdentityValidateMixin` (Faza 1.5) exact
ca `GenericPlaywrightMatchScraperAdapter`, la care se aliniază intenționat
(„zero cod nou de parsare generică" — vezi
`docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md`, §4).

`fetch()` rămâne neimplementat — Tier 2 (Playwright) n-are infrastructură
de randare vie în acest repo (rezervată Fazei 4, ADR-042 §16.2), la fel ca
`GenericPlaywrightMatchScraperAdapter`. `persist()` NU e no-op (spre
deosebire de adaptoarele generice de Fază 1.5) — scrie prin
`upsert_match_canonical` + INSERT în `player_match_stats`/`match_events`,
DAR rămâne și el `NotImplementedError` până migrarea din §3 a designului
e aprobată și aplicată — nicio scriere Supabase reală din acest fișier azi.

FLASH_PROVIDER_CAPABILITIES: declarație pură (§2 din design) — fiecare
`True` corespunde unui ✅ verificat direct în
`UDAL_FLASHSCORE_POC_10MATCHES_REPORT.md`, fiecare `False` unui ❌/⚠️ —
nicio stare necunoscută aproximată (North Star #8).
================================================================================
"""
from __future__ import annotations

from typing import Any

from acquisition_tier import AcquisitionTier
from generic_rich_match_scraper_adapter import (
    PlaywrightNotImplementedError,
    _CssExtractionNormalizeMixin,
    _IdentityValidateMixin,
)
from scraper_adapter_base import ScraperAdapterBase
from udal_validation import ValidationResult

from .extractor import LINEUPS_EXTRACTION_MAP, MATCH_SUMMARY_EXTRACTION_MAP

FLASH_PROVIDER_CAPABILITIES: dict[str, bool] = {
    "possession": True,
    "shots": True,
    "shots_on_target": True,
    "corners": True,
    "fouls": True,
    "yellow_cards": True,
    "red_cards": True,
    "offsides": True,
    "goalkeeper_saves": True,
    "lineups_starting_xi": True,
    "player_ratings": True,
    "substitution_events": True,
    "referee": True,
    "attendance": True,
    "stadium": True,
    "odds_snapshot": False,
    "xg": False,
    "weather": False,
    "h2h_history_rows": False,
    "coach_name": False,
    "bench_full_list": False,
}


class FlashscoreAdapter(_CssExtractionNormalizeMixin, _IdentityValidateMixin, ScraperAdapterBase):
    """[R-Sync-FLASH-01, design-only] Vezi docstring modul — nicio metodă
    de mai jos scrie sau citește live."""

    scraper_id = "flashscore_match_enrichment"
    tier = AcquisitionTier.PLAYWRIGHT
    _extraction_map = MATCH_SUMMARY_EXTRACTION_MAP | LINEUPS_EXTRACTION_MAP

    def fetch(self, params: dict) -> Any | None:
        raise PlaywrightNotImplementedError(
            "R-Sync-FLASH-01: fetch() live rezervat Fazei 4 (ADR-042 §16.2) — "
            "acest adaptor e design-only, vezi docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md."
        )

    def validate(self, records: list[Any]) -> ValidationResult:
        return _IdentityValidateMixin.validate(self, records)

    def persist(self, records: list[Any]) -> bool:
        raise NotImplementedError(
            "R-Sync-FLASH-01: persist() cere migrarea Supabase propusă (§3) — "
            "neaprobată, neaplicată. Nicio scriere reală din acest fișier azi."
        )
