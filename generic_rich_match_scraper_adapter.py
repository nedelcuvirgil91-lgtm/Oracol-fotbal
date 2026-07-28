"""
================================================================================
FOOTBALL ORACLE — Generic Rich Match Scraper Adapters (UDAL Faza 1.5, ADR-042)
================================================================================
Module: generic_rich_match_scraper_adapter.py

Trei adaptoare, TOATE construite pe `udal_extraction.extract()` — proba
directă a cerinței explicite: „GenericHtmlScraperAdapter poate funcționa
pentru toate sursele schimbând doar selector map/config, NU codul".

  - `GenericRichMatchScraperAdapter` (Tier 1, HTTP+CSS) — `fetch()` citește
    HTML local, `normalize()` extrage via `CSS_RESOLVER`.
  - `GenericPlaywrightMatchScraperAdapter` (Tier 2, Playwright+CSS) —
    `fetch()` ridică `NotImplementedError` (infra Playwright rezervată
    Fazei 4, ADR-042 §16.2 — nu există încă), dar `normalize()` e MOȘTENIT
    NESCHIMBAT din `_CssExtractionNormalizeMixin` — EXACT aceeași logică
    de extragere ca Tier 1, aplicată pe DOM post-randare (nu pe HTTP brut).
    Asta demonstrează: doar `fetch()` diferă structural între tier-uri,
    parsarea rămâne 100% comună.
  - `GenericJsonMatchScraperAdapter` (Tier 1, HTTP+JSON path) — pentru
    surse tip SofaScore (API neoficială, JSON, dar tot acces HTTP simplu,
    fără browser) — `normalize()` folosește `JSON_RESOLVER` în loc de
    `CSS_RESOLVER`, dovedind a doua axă (tip de extracție), ORTOGONALĂ
    față de tier — nu un tier nou, un mecanism de parsare diferit.

[UDAL Faza 1.5] `fetch()` (unde există) citește STRICT un fixture local —
"Nu implementa scraping live" rămâne respectat identic Fazei 1.
`persist()` rămâne no-op în toate trei — nicio scriere canonică.
================================================================================
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from acquisition_tier import AcquisitionTier
from scraper_adapter_base import ScraperAdapterBase
from udal_extraction import CSS_RESOLVER, JSON_RESOLVER, extract
from udal_validation import ValidationResult, validate_identity_only


class LiveFetchNotAllowedError(Exception):
    """[UDAL Faza 1/1.5] fetch() cere STRICT mode="fixture" — nicio altă
    valoare, indiferent de tier."""


class PlaywrightNotImplementedError(NotImplementedError):
    """[UDAL Faza 1.5] Tier 2 rămâne fără fetch() real — infrastructură
    de randare browser rezervată explicit Fazei 4 (ADR-042 §16.2)."""


class _CssExtractionNormalizeMixin:
    """`normalize()` COMUN — orice sursă ale cărei date ajung ca HTML
    (Tier 1 direct din HTTP, Tier 2 după randare) folosește ACEEAȘI
    metodă, fără nicio ramură per tier."""

    _extraction_map: dict

    def normalize(self, raw_payload: Any) -> list[dict]:
        if not raw_payload:
            return []
        soup = BeautifulSoup(raw_payload, "html.parser")
        return [extract(soup, self._extraction_map, CSS_RESOLVER)]


class _IdentityValidateMixin:
    def validate(self, records: list[Any]) -> ValidationResult:
        return validate_identity_only(records, source_tier=self.tier.value, source_id=self.scraper_id)


class _NoopPersistMixin:
    def persist(self, records: list[Any]) -> bool:
        """[UDAL Faza 1/1.5] No-op deliberat — nicio scriere canonică."""
        return True


class GenericRichMatchScraperAdapter(
    _CssExtractionNormalizeMixin, _IdentityValidateMixin, _NoopPersistMixin, ScraperAdapterBase,
):
    tier = AcquisitionTier.HTTP_SCRAPER

    def __init__(self, scraper_id: str, extraction_map: dict, provider_id: str | None = None):
        self.scraper_id = scraper_id
        self.provider_id = provider_id or scraper_id
        self._extraction_map = extraction_map

    def fetch(self, params: dict) -> Any | None:
        if params.get("mode") != "fixture":
            raise LiveFetchNotAllowedError(
                f"mode={params.get('mode')!r} nu e permis — doar 'fixture' "
                "(Faza 1.5, 'Nu implementa scraping live')."
            )
        return Path(params["fixture_path"]).read_text(encoding="utf-8")


class GenericPlaywrightMatchScraperAdapter(
    _CssExtractionNormalizeMixin, _IdentityValidateMixin, _NoopPersistMixin, ScraperAdapterBase,
):
    tier = AcquisitionTier.PLAYWRIGHT

    def __init__(self, scraper_id: str, extraction_map: dict, provider_id: str | None = None):
        self.scraper_id = scraper_id
        self.provider_id = provider_id or scraper_id
        self._extraction_map = extraction_map

    def fetch(self, params: dict) -> Any | None:
        raise PlaywrightNotImplementedError(
            "Tier 2 (Playwright) nu are fetch() real în acest repo — rezervat "
            "Fazei 4 (ADR-042 §16.2). normalize() e disponibil și testat "
            "separat, contra unui fixture care reprezintă DOM POST-RANDARE."
        )


class GenericJsonMatchScraperAdapter(_IdentityValidateMixin, _NoopPersistMixin, ScraperAdapterBase):
    """Tier 1 (HTTP simplu, fără browser) — dar extracție JSON path, nu CSS.
    A doua axă, ORTOGONALĂ față de tier (vezi docstring modul)."""

    tier = AcquisitionTier.HTTP_SCRAPER

    def __init__(self, scraper_id: str, extraction_map: dict, provider_id: str | None = None):
        self.scraper_id = scraper_id
        self.provider_id = provider_id or scraper_id
        self._extraction_map = extraction_map

    def fetch(self, params: dict) -> Any | None:
        if params.get("mode") != "fixture":
            raise LiveFetchNotAllowedError(
                f"mode={params.get('mode')!r} nu e permis — doar 'fixture'."
            )
        return Path(params["fixture_path"]).read_text(encoding="utf-8")

    def normalize(self, raw_payload: Any) -> list[dict]:
        if not raw_payload:
            return []
        payload = json.loads(raw_payload)
        return [extract(payload, self._extraction_map, JSON_RESOLVER)]
