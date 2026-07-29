"""
================================================================================
FOOTBALL ORACLE — Generic HTML Stats Scraper Adapter (UDAL Faza 1, ADR-042)
================================================================================
Module: generic_html_stats_scraper_adapter.py

Adaptor GENERIC pentru Tier 1 (HTTP Scraper) — condus integral de harta de
selectori (`scraper_selector_registry`, versionată), nu de cod scris per
site. Decizie explicită a proprietarului produsului: "Nu vreau o sursă
hardcodată... sursele trebuie să fie interschimbabile. Pilotul nu trebuie
proiectat pentru un anumit site." — a schimba sursa înseamnă a schimba
harta de selectori + `target_url_template` din Scraper Registry, NU a
rescrie această clasă.

[UDAL Faza 1] `fetch()` citește STRICT un fixture HTML local — niciun
apel de rețea real nu există în acest adaptor încă ("fără acces live",
constrângere explicită). Trecerea la fetch live (Faza 1+/POC_SCRAPER_SOURCE_01)
e izolată la o singură metodă, per interfața `SyncAdapter` — restul
clasei (normalize/validate/persist) nu se schimbă.

`persist()` e un no-op DELIBERAT în Faza 1 — "fără scriere în tabele
canonice". Metrici de rulare (fetch/validate/rejected) se scriu în
`acquisition_run_log` (tabelă UDAL, NU canonică, creată în Faza 0) prin
apelantul pilotului (`udal_pilot_run.py`), nu direct de acest adaptor —
`persist()` rămâne strict despre scrierea datelor de DOMENIU (statistici
de meci), nu despre observabilitate.
================================================================================
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from acquisition_tier import AcquisitionTier
from scraper_adapter_base import ScraperAdapterBase
from udal_validation import validate_records, ValidationResult


class LiveFetchNotAllowedError(Exception):
    """[UDAL Faza 1] Ridicată dacă cineva cere fetch live — nu există încă,
    intenționat, per constrângerea explicită a acestei faze."""


class GenericHtmlStatsScraperAdapter(ScraperAdapterBase):
    """`params["mode"]` trebuie să fie `"fixture"` în Faza 1 — orice altă
    valoare (inclusiv `"live"`) ridică `LiveFetchNotAllowedError`, ca
    siguranță structurală, nu doar convenție documentată."""

    tier = AcquisitionTier.HTTP_SCRAPER

    def __init__(self, scraper_id: str, selector_map: dict, provider_id: str | None = None):
        self.scraper_id = scraper_id
        self.provider_id = provider_id or scraper_id
        self._selector_map = selector_map

    def fetch(self, params: dict) -> Any | None:
        mode = params.get("mode")
        if mode != "fixture":
            raise LiveFetchNotAllowedError(
                f"mode={mode!r} nu e permis în Faza 1 — doar 'fixture'. "
                "Fetch live rămâne rezervat POC_SCRAPER_SOURCE_01, pas separat, "
                "după aprobare explicită tos_reviewed=True."
            )
        fixture_path = Path(params["fixture_path"])
        return fixture_path.read_text(encoding="utf-8")

    def normalize(self, raw_payload: Any) -> list[dict]:
        if not raw_payload:
            return []
        soup = BeautifulSoup(raw_payload, "html.parser")
        rows = soup.select(self._selector_map["row_selector"])
        fields = self._selector_map["fields"]

        records: list[dict] = []
        for row in rows:
            record: dict = {}
            for field_name, selector in fields.items():
                cell = row.select_one(selector)
                record[field_name] = cell.get_text(strip=True) if cell else None
            records.append(record)
        return records

    def validate(self, records: list[Any]) -> ValidationResult:
        """[NOTĂ] Întoarce `ValidationResult` (nu doar `list[Any]` cum cere
        strict semnătura `SyncAdapter.validate()`) — decizie deliberată
        pentru Faza 1: pilotul are nevoie explicit de rândurile respinse +
        motivele lor (Validation Rate, raportul cerut), nu doar de cele
        valide. Un adaptor de producție (Faza 3+) ar putea alege să
        întoarcă doar `.valid`, per contractul strict — divergență
        documentată, nu ascunsă."""
        return validate_records(records, source_tier=self.tier.value, source_id=self.scraper_id)

    def persist(self, records: list[Any]) -> bool:
        """[UDAL Faza 1] No-op deliberat — "fără scriere în tabele
        canonice". Întoarce True (rulare reușită), dar nu scrie nimic
        nicăieri. Devine o scriere reală abia când gate-ul de migrare
        (ADR-040) confirmă PASS pentru această sursă — nu în Faza 1."""
        return True
