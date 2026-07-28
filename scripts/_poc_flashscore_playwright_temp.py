"""
================================================================================
POC izolat, temporar — verificare LIVE minimă: mai funcționează Flashscore
cu Playwright standard (fără patch-uri de evaziune)?
================================================================================
Scop STRICT informativ: decidem dacă Flashscore rămâne un candidat
"Premium" (Faza 4, viitor) discutabil, sau îl scoatem din discuție.

UN SINGUR request de navigare (nu bulk, nu multiple meciuri) — Playwright
Chromium STANDARD, headless, fără `patchright`, fără plugin stealth, fără
proxy — exact profilul confirmat în `gustavofariaa/FlashscoreScraping`
(citit direct din cod, sesiunea anterioară).

Nu importă niciun cod de producție UDAL, nu trece prin
scraper_registry.py/tos_reviewed. Nu scrie nicăieri în Supabase.
================================================================================
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

TARGET_URL = "https://www.flashscore.com/football/romania/liga-i/"


def main() -> dict:
    from playwright.sync_api import sync_playwright

    result: dict = {"run_at": datetime.now(timezone.utc).isoformat(), "target_url": TARGET_URL}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        t0 = time.perf_counter()
        try:
            response = page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
            result["http_status"] = response.status if response else None
        except Exception as exc:
            result["navigation_error"] = str(exc)
            result["http_status"] = None
        result["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)

        # Lasam timp pentru randare JS (Flashscore e SPA) inainte de a
        # verifica ce s-a incarcat de fapt.
        page.wait_for_timeout(4000)

        result["page_title"] = page.title()

        # Indicatori de blocare/challenge cunoscuti (Cloudflare/CAPTCHA),
        # cautati generic in continutul paginii - nu presupunem succes.
        content = page.content()
        lower_content = content.lower()
        result["content_length_chars"] = len(content)
        result["looks_like_cloudflare_challenge"] = any(
            marker in lower_content for marker in (
                "checking your browser", "cf-browser-verification",
                "cloudflare", "captcha", "attention required",
            )
        )

        # Cautam un selector real de continut de meciuri (data-testid
        # folosit de site, per structura confirmata in codul scraper-ului
        # citit anterior) - daca exista, pagina chiar s-a incarcat cu date.
        try:
            match_rows = page.locator("[data-testid='wcl-matchRow']").count()
        except Exception:
            match_rows = None
        result["match_rows_found"] = match_rows

        screenshot_path = EVIDENCE_DIR / "flashscore_poc_screenshot.png"
        try:
            page.screenshot(path=str(screenshot_path), full_page=False)
            result["screenshot_saved"] = True
        except Exception as exc:
            result["screenshot_saved"] = False
            result["screenshot_error"] = str(exc)

        (EVIDENCE_DIR / "flashscore_poc_raw.html").write_text(content, encoding="utf-8")

        browser.close()

    return result


if __name__ == "__main__":
    output = main()
    report_path = EVIDENCE_DIR / "poc_flashscore_playwright_result.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False))
