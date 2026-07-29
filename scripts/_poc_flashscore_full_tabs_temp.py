"""
================================================================================
POC izolat, temporar — TOATE tab-urile Flashscore, UN SINGUR meci real.
================================================================================
Aprobat explicit: "TASK APROBAT - POC LIVE (1 singur meci)". Meciul e cel
din captura trimisa de utilizator: Dinamo Bucuresti 5-1 Univ. Craiova,
25.07.2026 (SuperLiga, deja identificat in POC-ul cu 10 meciuri).

URL-urile reale ale celor 7 tab-uri au fost extrase DIRECT din HTML-ul deja
salvat (docs/06_UDAL/poc_evidence/flashscore_10matches/superliga_5_..._
summary.html) - nicio descoperire noua, nicio presupunere de URL.

Playwright STANDARD, headless, fara patchright/stealth/proxy/spoofing -
profilul confirmat in gustavofariaa/FlashscoreScraping, folosit consecvent
in tot acest sesiune. Oprire imediata daca apare orice semn de protectie.

Nu importa niciun cod de productie UDAL, nu trece prin
scraper_registry.py/tos_reviewed (izolat, exact ca fiecare POC anterior
din aceasta sesiune). Nu scrie in tabelele de productie (match_history/
player_match_stats/match_events/odds_fallback_flashscore) - doar salveaza
evidenta bruta local, pentru analiza ulterioara si persistare intr-o
tabela de TEST separata (pas separat, dupa acest POC).
================================================================================
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_full_tabs_poc"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

MATCH_BASE = "https://www.flashscore.com/match/football/dinamo-bucuresti-rBgMi3MH/univ-craiova-bsd9fGaK"
MID = "AJtcK933"

# Extrase direct din summary.html deja salvat - nicio presupunere de URL.
TABS: dict[str, str] = {
    "summary": f"{MATCH_BASE}/?mid={MID}",
    "stats": f"{MATCH_BASE}/summary/stats/?mid={MID}",
    "lineups": f"{MATCH_BASE}/summary/lineups/?mid={MID}",
    "player_stats": f"{MATCH_BASE}/summary/player-stats/?mid={MID}",
    "odds": f"{MATCH_BASE}/odds/?mid={MID}",
    "h2h": f"{MATCH_BASE}/h2h/?mid={MID}",
    "standings": f"{MATCH_BASE}/standings/?mid={MID}",
}

NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500

PROTECTION_MARKERS = (
    "checking your browser", "cf-browser-verification", "attention required",
    "captcha-delivery", "access denied", "ray id",
    "sorry, you have been blocked", "just a moment...",
    "verify you are human", "unusual traffic from your computer",
    "please verify you are a human", "detected unusual activity",
)


class ProtectionDetected(Exception):
    pass


def _check_protection(page, http_status, tag, log):
    if http_status is not None and http_status in (403, 429, 503):
        raise ProtectionDetected(f"{tag}: HTTP {http_status}")
    lower = page.content().lower()
    hit = next((m for m in PROTECTION_MARKERS if m in lower), None)
    if hit:
        raise ProtectionDetected(f"{tag}: marker gasit -> '{hit}'")
    log.append({"tag": tag, "http_status": http_status, "protection_check": "clean"})


def _dismiss_gdpr_if_present(page):
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
                return True
        except Exception:
            continue
    return False


def _testid_inventory(html: str) -> dict:
    """Inventar structural rapid - toate data-testid distincte gasite in
    tab, pentru documentarea structurii DOM ceruta explicit."""
    import re
    testids = sorted(set(re.findall(r'data-testid="([a-zA-Z0-9_-]+)"', html)))
    return {"distinct_testid_count": len(testids), "testids": testids}


def main() -> dict:
    from playwright.sync_api import sync_playwright

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "match": "Dinamo Bucuresti 5-1 Univ. Craiova, 25.07.2026 (SuperLiga)",
        "log": [],
        "tabs": {},
        "stopped_due_to_protection": None,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            for tab_name, url in TABS.items():
                t0 = time.perf_counter()
                resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                http_status = resp.status if resp else None
                load_ms = round((time.perf_counter() - t0) * 1000, 1)
                _check_protection(page, http_status, f"tab-{tab_name}", result["log"])
                page.wait_for_timeout(POST_LOAD_WAIT_MS)
                gdpr = _dismiss_gdpr_if_present(page)

                html = page.content()
                (EVIDENCE_DIR / f"{tab_name}.html").write_text(html, encoding="utf-8")
                try:
                    page.screenshot(path=str(EVIDENCE_DIR / f"{tab_name}.png"), full_page=True)
                    screenshot_saved = True
                except Exception:
                    screenshot_saved = False

                result["tabs"][tab_name] = {
                    "url": url,
                    "http_status": http_status,
                    "load_time_ms": load_ms,
                    "content_length": len(html),
                    "gdpr_banner_seen": gdpr,
                    "page_title": page.title(),
                    "screenshot_saved": screenshot_saved,
                    **_testid_inventory(html),
                }
                time.sleep(2.0)

        except ProtectionDetected as exc:
            result["stopped_due_to_protection"] = str(exc)

        browser.close()

    return result


if __name__ == "__main__":
    output = main()
    report_path = EVIDENCE_DIR / "poc_full_tabs_result.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {k: v for k, v in output.items() if k != "log"}
    for tab in summary.get("tabs", {}).values():
        tab.pop("testids", None)  # lista completa ramane in fisierul JSON, nu in stdout
    print(json.dumps(summary, indent=2, ensure_ascii=False))
