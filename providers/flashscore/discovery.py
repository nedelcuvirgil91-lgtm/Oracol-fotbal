"""
================================================================================
FOOTBALL ORACLE — Flashscore Match Discovery (Foundation Data Layer, ADR-044)
================================================================================
Module: providers/flashscore/discovery.py

M1 — transformă "competiție urmărită" în listă de meciuri reale
(`match_base_url` + `mid`), pe baza structurii reale a paginii de
rezultate Flashscore, verificată live (nu presupusă). Structura de mai
jos a fost confirmată direct, printr-o navigare Playwright reală, fără
niciun semn de protecție întâlnit (evidența brută rămâne salvată în
`docs/06_UDAL/poc_evidence/flashscore_10matches/`:
`superliga_results_hub_raw.html`, `ucl_results_hub_raw.html`) — același
tipar de HTML e citit aici, niciun selector nou ghicit.

Structură confirmată (per rând de meci, `.event__match`):
- `a.eventRowLink[href*="/match/football/"]` → URL complet, cu `?mid=...`.
- Rândurile de pe `/results/` sunt DOAR meciuri încheiate — Flashscore
  separă `/results/` de `/fixtures/` la nivel de hub, deci discovery NU
  are nevoie să parseze un status per rând, sursa hub-ului îl garantează
  implicit (fallback pe `/fixtures/` există doar dacă `/results/` nu
  întoarce niciun link, identic tiparului deja verificat în POC-ul
  `scripts/_poc_flashscore_10matches_temp.py`).
- Data/ora afișată per rând (ex. "27.07. 18:30") NU are an — NU se
  folosește aici. Data completă (cu an), autoritativă, se extrage deja
  de `normalizer._extract_kickoff_iso()` direct de pe pagina meciului
  (`.duelParticipant__startTime`, are anul) — discovery nu duplică acea
  responsabilitate.
- "Show more matches" (paginare) există ca mecanism în aplicație
  (confirmat în bundle-ul JS — cheia de traducere
  `TRANS_SHOW_MORE_MATCHES`), dar NU a apărut ca buton vizibil în
  randarea capturată (16 meciuri unice SuperLiga / 28 unice UCL, fără
  element `event__more` în DOM). Paginarea dincolo de randarea inițială
  rămâne NEIMPLEMENTATĂ — documentat explicit, nu ghicită.

FLASHSCORE_TRACKED_COMPETITIONS conține DOAR competiții cu slug
Flashscore verificat live — extinderea la alte ligi (Premier League, La
Liga, Serie A, Bundesliga, Ligue 1 — ordinea de bootstrap) rămâne task
separat, per ligă, fiecare slug verificat live înainte de a fi adăugat,
niciodată presupus din convenția de URL Flashscore.

Pacing: `FLASHSCORE_MIN_DELAY_SECONDS` — unica disciplină de
politețe/rată implementată azi (`politeness_policy_ref` din
`scraper_registry.py` rămâne altfel un string neresolvat, fără mecanism).
================================================================================
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("FootballOracle.Flashscore.Discovery")

NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500

# Vezi adapter.py - acelasi mecanism opțional de executable_path explicit.
_CHROMIUM_EXECUTABLE_PATH = os.environ.get("FLASHSCORE_CHROMIUM_EXECUTABLE") or None

# Unica disciplina de politete/rata implementata azi - delay minim intre
# doua navigari succesive (hub->hub, sau meci->meci in orchestrare).
FLASHSCORE_MIN_DELAY_SECONDS = 2.0

_PROTECTION_MARKERS = (
    "checking your browser", "cf-browser-verification", "attention required",
    "captcha-delivery", "access denied", "ray id",
    "sorry, you have been blocked", "just a moment...",
    "verify you are human", "unusual traffic from your computer",
    "please verify you are a human", "detected unusual activity",
)

# [ADR-044] Doar competitii cu slug Flashscore VERIFICAT LIVE (nu ghicit) -
# vezi docstring modul. (country, competition) - exact segmentele folosite
# de target_url_template din scraper_registry.py.
FLASHSCORE_TRACKED_COMPETITIONS: dict[str, tuple[str, str]] = {
    "Romania SuperLiga": ("romania", "superliga"),
    "UEFA Champions League": ("europe", "champions-league"),
}


class FlashscoreProtectionDetected(Exception):
    """Identic cu adapter.py - oprire imediata la orice semn de protectie,
    niciodata bypass/stealth/proxy."""


@dataclass(frozen=True)
class DiscoveredMatch:
    league: str
    match_base_url: str
    mid: str
    source: str  # "results" sau "fixtures"


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


def parse_match_links(html: str) -> list[tuple[str, str]]:
    """Functie PURA - din HTML brut al hub-ului -> [(match_base_url, mid),
    ...], ordinea paginii, fara duplicate. `match_base_url` fara slash
    final, fara query string (contract identic cu parametrii cerut de
    `FlashscoreAdapter.fetch()`). Testata direct contra evidentei reale
    capturate live (`docs/06_UDAL/poc_evidence/flashscore_10matches/`),
    nu contra unui fixture inventat."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, str] = {}
    for a in soup.select("a[href*='/match/football/']"):
        href = a.get("href")
        if not href:
            continue
        full = href if href.startswith("http") else f"https://www.flashscore.com{href}"
        base, _, query = full.partition("?")
        base = base.rstrip("/")
        mid = None
        for part in query.split("&"):
            if part.startswith("mid="):
                mid = part[len("mid="):]
                break
        if not mid or base in seen:
            continue
        seen[base] = mid
    return list(seen.items())


def _discover_for_hub(page, hub_url: str, league: str, limit: int | None) -> list[DiscoveredMatch]:
    """`hub_url` fara `/results/`/`/fixtures/` - ambele incercate,
    `/results/` intai (identic POC-ului 10-matches, deja verificat live);
    `/fixtures/` folosit doar daca `/results/` nu intoarce niciun link."""
    for source in ("results", "fixtures"):
        url = f"{hub_url.rstrip('/')}/{source}/"
        resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        http_status = resp.status if resp else None
        _dismiss_gdpr_if_present(page)
        page.wait_for_timeout(POST_LOAD_WAIT_MS)
        _check_protection(page, http_status, tag=f"{league}-{source}-hub")
        pairs = parse_match_links(page.content())
        if pairs:
            if limit is not None:
                pairs = pairs[:limit]
            return [
                DiscoveredMatch(league=league, match_base_url=base, mid=mid, source=source)
                for base, mid in pairs
            ]
        time.sleep(FLASHSCORE_MIN_DELAY_SECONDS)
    return []


def discover_matches(
    leagues: list[str] | None = None, limit_per_league: int | None = None,
) -> list[DiscoveredMatch]:
    """Punct de intrare M1 - o singura sesiune Playwright, un singur
    browser, pacing explicit intre hub-uri succesive
    (`FLASHSCORE_MIN_DELAY_SECONDS`). `leagues=None` -> toate din
    `FLASHSCORE_TRACKED_COMPETITIONS`. Ridica `FlashscoreProtectionDetected`
    si se opreste imediat la orice semn de protectie, nu incearca sa
    ocoleasca - identic restul acestui provider."""
    targets = leagues if leagues is not None else list(FLASHSCORE_TRACKED_COMPETITIONS.keys())
    unknown = [lg for lg in targets if lg not in FLASHSCORE_TRACKED_COMPETITIONS]
    if unknown:
        raise ValueError(
            f"discover_matches(): liga(e) fara slug Flashscore verificat live -> {unknown} "
            "(vezi FLASHSCORE_TRACKED_COMPETITIONS, providers/flashscore/discovery.py)."
        )

    from playwright.sync_api import sync_playwright

    results: list[DiscoveredMatch] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=_CHROMIUM_EXECUTABLE_PATH)
        page = browser.new_page()
        try:
            for i, league in enumerate(targets):
                country, competition = FLASHSCORE_TRACKED_COMPETITIONS[league]
                hub_url = f"https://www.flashscore.com/football/{country}/{competition}"
                if i > 0:
                    time.sleep(FLASHSCORE_MIN_DELAY_SECONDS)
                results.extend(_discover_for_hub(page, hub_url, league, limit_per_league))
        finally:
            browser.close()
    return results


def run_foundation_data_layer_for_discovered_matches(
    matches: list[DiscoveredMatch],
) -> list[dict[str, Any]]:
    """Ruleaza fetch()/normalize()/validate() (FlashscoreAdapter,
    adapter.py) + `persist_match_with_data_trust_layer()` direct (nu
    `adapter.persist()`, care intoarce doar bool - contractul
    `SyncAdapter`) pentru fiecare meci descoperit, secvential, cu pacing
    explicit intre meciuri (`FLASHSCORE_MIN_DELAY_SECONDS`) - "Foundation
    Data Layer va rula apoi peste fiecare meci descoperit" (aprobare
    explicita, 2026-07-29). `preflight()` verificat o singura data, inainte
    de bucla - `tos_reviewed` nu se schimba intre meciuri in aceeasi
    rulare. Fiecare rezultat e raportul complet intors de
    `persist_match_with_data_trust_layer()` (niciodata doar True/False -
    esecul partial ramane vizibil, North Star #9)."""
    from .adapter import FlashscoreAdapter, _build_match_ref
    from .persistence import persist_match_with_data_trust_layer

    try:
        from database.queries import is_flashscore_match_already_collected
    except ModuleNotFoundError:
        is_flashscore_match_already_collected = None

    adapter = FlashscoreAdapter()
    adapter.preflight()

    reports: list[dict[str, Any]] = []
    for i, match in enumerate(matches):
        if i > 0:
            time.sleep(FLASHSCORE_MIN_DELAY_SECONDS)
        # [Delta Sync — Faza 2] `mid` e cunoscut ÎNAINTE de fetch (Discovery
        # îl extrage din URL-ul hub-ului) — dacă acest meci a fost deja
        # persistat canonic (fixture_id="flashscore_{mid}" pe match_history),
        # sărim fetch-ul complet (7 tab-uri Playwright), nu doar persist().
        if is_flashscore_match_already_collected is not None and is_flashscore_match_already_collected(match.mid):
            reports.append({
                "match_id": None, "ok": True, "skipped": True,
                "reason": "already_collected", "match": match,
            })
            continue
        try:
            pages = adapter.fetch({"match_base_url": match.match_base_url, "mid": match.mid})
        except Exception as exc:
            logger.error(
                "[Flashscore.Discovery] fetch esuat pentru %s (mid=%s): %s",
                match.match_base_url, match.mid, exc,
            )
            reports.append({"match_id": None, "ok": False, "error": str(exc), "match": match})
            continue
        records = adapter.normalize(pages)
        valid = adapter.validate(records)
        if not valid:
            reports.append({"match_id": None, "ok": False, "error": "validare identitate esuata", "match": match})
            continue
        record = valid[0]
        match_ref = _build_match_ref(record.get("home_team"), record.get("away_team"), record.get("kickoff_date"))
        # [FIX live] match_history.league e NOT NULL - Discovery deja
        # cunoaste liga (a ales-o explicit ca sa construiasca URL-ul hub-ului,
        # FLASHSCORE_TRACKED_COMPETITIONS), o furnizeaza direct in loc sa
        # ceara normalizer-ului sa o extraga din pagina (gol real, documentat
        # in FLASHSCORE_FIELD_MAPPING_MATRIX.md - "Cross-provider dependency").
        report = persist_match_with_data_trust_layer(
            record["_pages"], match_ref=match_ref, league=match.league, competition=match.league,
        )
        reports.append({**report, "match": match})
    return reports
