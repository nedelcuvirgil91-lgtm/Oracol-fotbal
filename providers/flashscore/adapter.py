"""
================================================================================
FOOTBALL ORACLE — Flashscore Adapter (Foundation Data Layer, ADR-044)
================================================================================
Module: providers/flashscore/adapter.py

Rescris complet (2026-07-29, "Începem implementarea live"). Versiunea
anterioară (R-Sync-FLASH-01, design-only) moștenea din
`generic_rich_match_scraper_adapter.py` (`_CssExtractionNormalizeMixin`/
`_IdentityValidateMixin`) — infrastructură Fazei 1.5, proiectată STRICT
pentru fixture-uri locale ("fetch() citește STRICT un fixture local... Nu
implementa scraping live rămâne respectat identic Fazei 1"). Contract
incompatibil cu un adaptor care trebuie să suporte `fetch()` live odată
activat — înlocuit cu `normalizer.py` (parsare pură, label-as-key) +
`persistence.py` (Data Trust Layer, RAW→VALIDATED→CANONICAL, testat
idempotent 1/2/10 rulări) — arhitectura REALĂ a Foundation Data Layer,
nu un schelet.

**Gate ToS — DESCHIS din 2026-07-29**: `preflight()` (moștenit din
`ScraperAdapterBase`) verifică `scraper_registry.is_runnable(self.
scraper_id)`. `tos_reviewed=True` (`scraper_registry.py`) — aprobare
explicită, separată, a proprietarului produsului ("DA. Activează acum."),
pentru primul test live controlat (ADR-044). Mecanismul `preflight()` NU
s-a schimbat — doar valoarea `tos_reviewed` — orice orchestrator tot
trebuie să apeleze explicit `preflight()` înainte de `fetch()`, nu implicit.
Activarea reală rămâne condiționată de disciplina de politețe/rată — vezi
`providers/flashscore/discovery.py` pentru mecanismul de pacing.

**Discovery (M1) — în construcție** — `fetch()` cere `match_base_url`
+ `mid` deja rezolvate (identitatea meciului pe Flashscore); transformarea
"competiție urmărită" → listă de meciuri e responsabilitatea
`providers/flashscore/discovery.py` (structura reală a paginii de
rezultate/fixtures verificată direct, live, înainte de orice selector —
niciun selector ghicit).

FLASH_PROVIDER_CAPABILITIES: declarație pură — fiecare `True` corespunde
unui ✅ verificat direct în rapoartele POC, fiecare `False` unui ❌/⚠️.
================================================================================
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from acquisition_tier import AcquisitionTier
from scraper_adapter_base import ScraperAdapterBase
from udal_validation import validate_flat_identity

from .normalizer import normalize_match_statistics
from .persistence import persist_match_with_data_trust_layer

logger = logging.getLogger("FootballOracle.Flashscore.Adapter")

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
    # [ADR-043] Fallback temporar DOAR - the-odds-api ramane sursa
    # principala, neschimbata. Scrierea RAW e mapata (flashscore_raw_
    # extraction); scrierea CANONICA in odds_fallback_flashscore ramane
    # blocata de rezolutia fixture_id cross-provider (vezi FLASHSCORE_
    # FIELD_MAPPING_MATRIX.md).
    "odds_snapshot": True,
    "xg": False,
    "weather": False,
    "h2h_history_rows": False,
    "coach_name": False,
    "bench_full_list": False,
}

# Sufixele reale ale celor 7 tab-uri (verificate direct in HTML capturat,
# data-analytics-alias) - identice cu cele folosite in POC-urile aprobate.
_MATCH_TAB_SUFFIXES: dict[str, str] = {
    "summary": "",
    "stats": "summary/stats/",
    "lineups": "summary/lineups/",
    "player_stats": "summary/player-stats/",
    "odds": "odds/",
    "h2h": "h2h/",
    "standings": "standings/",
}

NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500

# Optional - unele medii (containere cu Chromium pre-instalat la o cale
# fixa, non-standard pentru Playwright) au nevoie de un executable_path
# explicit in loc de auto-detectia default a Playwright. Implicit None ->
# comportament identic celui de dinainte (auto-detect).
_CHROMIUM_EXECUTABLE_PATH = os.environ.get("FLASHSCORE_CHROMIUM_EXECUTABLE") or None

# Identic cu markerii verificati in toate POC-urile acestei sesiuni -
# oprire imediata la orice semn de protectie, nu ghicit.
_PROTECTION_MARKERS = (
    "checking your browser", "cf-browser-verification", "attention required",
    "captcha-delivery", "access denied", "ray id",
    "sorry, you have been blocked", "just a moment...",
    "verify you are human", "unusual traffic from your computer",
    "please verify you are a human", "detected unusual activity",
)


class FlashscoreProtectionDetected(Exception):
    """Ridicata daca apare orice semn de protectie in timpul fetch() -
    oprire imediata, consecvent cu toate POC-urile din aceasta sesiune
    (niciodata proxy/stealth/patchright/spoofing pentru a ocoli)."""


def _dismiss_gdpr_if_present(page) -> None:
    for selector in (
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept & continue')",
        "button:has-text('Accept all')",
        "button:has-text('I Accept')",
    ):
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _check_protection(page, http_status: int | None, tag: str) -> None:
    if http_status is not None and http_status in (403, 429, 503):
        raise FlashscoreProtectionDetected(f"{tag}: HTTP {http_status}")
    lower = page.content().lower()
    hit = next((m for m in _PROTECTION_MARKERS if m in lower), None)
    if hit:
        raise FlashscoreProtectionDetected(f"{tag}: marker gasit -> '{hit}'")


class FlashscoreAdapter(ScraperAdapterBase):
    """Foundation Data Layer (ADR-044). `preflight()` verifică
    `tos_reviewed` (True din 2026-07-29, aprobare explicită a
    proprietarului produsului) — orice orchestrator tot trebuie să îl
    apeleze explicit înainte de `fetch()`, gate-ul rămâne activ ca
    mecanism, doar starea s-a schimbat."""

    scraper_id = "flashscore_match_enrichment"
    provider_id = "flashscore"
    tier = AcquisitionTier.PLAYWRIGHT

    def fetch(self, params: dict) -> dict[str, str] | None:
        """`params`: `{"match_base_url": str, "mid": str, "competition":
        str | None}`. `match_base_url`/`mid` = identitatea meciului pe
        Flashscore, DEJA rezolvată (discovery, M1, nu se rezolvă aici).
        Playwright standard, headless, fără stealth/proxy/spoofing -
        pattern identic celui verificat direct in POC-urile aprobate
        (`scripts/_poc_flashscore_full_tabs_temp.py`). Opreste imediat la
        orice semn de protectie (`FlashscoreProtectionDetected`), nu
        incearca sa ocoleasca."""
        match_base_url = params.get("match_base_url")
        mid = params.get("mid")
        if not match_base_url or not mid:
            raise ValueError(
                "FlashscoreAdapter.fetch(): 'match_base_url' si 'mid' obligatorii "
                "(identitatea meciului trebuie rezolvata inainte, discovery separat)."
            )

        from playwright.sync_api import sync_playwright

        pages: dict[str, str] = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=_CHROMIUM_EXECUTABLE_PATH)
            page = browser.new_page()
            try:
                for tab_name, suffix in _MATCH_TAB_SUFFIXES.items():
                    url = f"{match_base_url}/{suffix}?mid={mid}"
                    resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                    http_status = resp.status if resp else None
                    if tab_name == "summary":
                        _dismiss_gdpr_if_present(page)
                    page.wait_for_timeout(POST_LOAD_WAIT_MS)
                    _check_protection(page, http_status, tag=tab_name)
                    pages[tab_name] = page.content()
            finally:
                browser.close()
        return pages

    def normalize(self, raw_payload: dict[str, str] | None) -> list[dict[str, Any]]:
        """`raw_payload` = `pages` (dict tab->html) intors de `fetch()`.
        UN singur "record" (intregul bundle de pagini al unui meci) -
        normalize_*() individuale ruleaza in `persist()`, prin
        `persist_match_with_data_trust_layer()` (Data Trust Layer complet,
        nu doar normalizare izolata)."""
        if not raw_payload:
            return []
        return [raw_payload]

    def validate(self, records: list[dict[str, str]]) -> list[dict[str, Any]]:
        """Filtru rapid pe cheia naturala (home_team/away_team/
        kickoff_date), inainte de orice scriere - NU duplica validarea
        completa (Data Trust Layer), care ruleaza din nou, per meci, in
        `persist()` (`persist_match_with_data_trust_layer` apeleaza intern
        `validate_flat_identity`). Randurile respinse aici nu ajung deloc
        la persist() - dar un rand care trece de acest filtru tot poate
        fi respins ulterior (RAW tot se scrie, per Data Trust Layer)."""
        candidates = [{**normalize_match_statistics(pages), "_pages": pages} for pages in records]
        result = validate_flat_identity(candidates, source_tier="playwright", source_id=self.scraper_id)
        return result.valid

    def persist(self, records: list[dict[str, Any]]) -> bool:
        """`records` = rezultatul `validate()` - fiecare rand contine
        `_pages` (bundle-ul original de HTML). `match_ref` (identitate
        STABILA pre-canonica, pentru `flashscore_raw_extraction`) derivat
        din cheia naturala - nu un identificator Flashscore separat, ca sa
        ramana stabil indiferent de cand se ruleaza.

        [Notă — audit Canonical Integration, Faza 2] Metoda de contract
        `SyncAdapter` de aici NU trece `league` (match_history.league e
        NOT NULL) - nefolosită azi în pipeline-ul real (Discovery apelează
        direct `persist_match_with_data_trust_layer(..., league=match.league)`,
        vezi `discovery.run_foundation_data_layer_for_discovered_matches()`,
        deliberat, exact ca să poată furniza liga). Dacă această metodă
        devine vreodată apelată dintr-un orchestrator generic (iterare
        uniformă peste toți adaptorii `SyncAdapter`), INSERT-ul ar eșua
        curat (`league` NOT NULL) - eșec vizibil, nu scriere silențioasă
        greșită, dar tot ar trebui extinsă să primească/transmită liga
        înainte de o asemenea utilizare."""
        if not records:
            return True
        ok = True
        for record in records:
            pages = record.get("_pages")
            if not pages:
                ok = False
                continue
            match_ref = _build_match_ref(record.get("home_team"), record.get("away_team"), record.get("kickoff_date"))
            report = persist_match_with_data_trust_layer(pages, match_ref=match_ref)
            ok = ok and bool(report.get("ok"))
        return ok


def _build_match_ref(home_team: str | None, away_team: str | None, kickoff_date: str | None) -> str:
    """Identitate STABILA, lizibila, pentru `flashscore_raw_extraction`
    (`match_ref`) - derivata din cheia naturala (home/away/kickoff),
    NICIODATA din id-ul intern Flashscore (mid), care nu are semnificatie
    stabila in afara Flashscore."""
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", (s or "unknown").lower()).strip("-")
    date_part = (kickoff_date or "unknown")[:10]
    return f"{slug(home_team)}__{slug(away_team)}__{date_part}"
