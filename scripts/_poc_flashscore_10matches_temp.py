"""
================================================================================
POC izolat, temporar — Flashscore, 10 meciuri reale (5 SuperLiga + 5 UEFA
Champions League), test LIMITAT de extractibilitate (nu adaptor UDAL).
================================================================================
Cerut explicit: "Architecture Validation - Flashscore POC (Phase 0)".

Reguli stricte respectate:
- Playwright STANDARD, headless, fara patchright/stealth/proxy/fingerprint
  spoofing/TLS spoofing/browser nedetectabil/bypass Cloudflare/CAPTCHA solver.
- Daca apare orice semn de protectie (Cloudflare/CAPTCHA/403/429/503/rate
  limit), testul se opreste IMEDIAT (ProtectionDetected) si raporteaza ce a
  gasit pana in acel punct.
- Nu importa niciun cod de productie UDAL, nu trece prin
  scraper_registry.py/tos_reviewed, nu scrie nicaieri in Supabase.
- Nu implementeaza adaptorul UDAL — doar masoara ce se poate extrage.
================================================================================
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_10matches"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

SUPERLIGA_HUB = "https://www.flashscore.com/football/romania/superliga/"
UCL_HUB = "https://www.flashscore.com/football/europe/champions-league/"

MATCHES_PER_COMPETITION = 5
NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500
TAB_CLICK_WAIT_MS = 1800
POLITENESS_DELAY_S = 2.0

PROTECTION_MARKERS = (
    "checking your browser", "cf-browser-verification", "attention required",
    "captcha-delivery", "hcaptcha.com", "recaptcha/api", "access denied",
    "ray id", "sorry, you have been blocked", "just a moment...",
)

# Etichete text vizibile pe pagina de meci, folosite pentru navigare intre
# taburi (nu presupunem selectori CSS ficsi - descoperim structura live).
TABS = ["Statistics", "Lineups", "H2H", "Odds", "Standings"]

# Detectoare pe baza de text vizibil (heuristic - verificare manuala ulterioara
# pe evidenta bruta salvata, acelasi tipar folosit la testul cu 1 pagina).
FIELD_DETECTORS = {
    "possession": [r"ball possession", r"possession\s*%"],
    "shots_total": [r"goal attempts", r"total shots"],
    "shots_on_target": [r"shots on (goal|target)"],
    "corners": [r"corner kicks"],
    "fouls": [r"\bfouls\b"],
    "yellow_cards": [r"yellow cards"],
    "red_cards": [r"red cards"],
    "offsides": [r"\boffsides\b"],
    "saves": [r"goalkeeper saves"],
    "lineups_starting_xi": [r"starting (lineups|xi)", r"formation"],
    "lineups_bench": [r"\bsubstitutes\b", r"\bbench\b"],
    "lineups_coach": [r"\bcoach\b"],
    "referee": [r"\breferee\b"],
    "stadium": [r"\bvenue\b", r"\bstadium\b"],
    "attendance": [r"\battendance\b"],
    "weather": [r"\bweather\b"],
    "xg": [r"\bxg\b", r"expected goals"],
    "h2h": [r"head-to-head", r"\bh2h\b"],
    "odds": [r"\bodds\b"],
    "player_rating": [r"\brating\b"],
}


class ProtectionDetected(Exception):
    pass


def _content_lower(page) -> str:
    return page.content().lower()


def _check_protection(page, http_status, tag, log):
    if http_status is not None and http_status in (403, 429, 503):
        raise ProtectionDetected(f"{tag}: HTTP {http_status}")
    lower = _content_lower(page)
    hit = next((m for m in PROTECTION_MARKERS if m in lower), None)
    if hit:
        raise ProtectionDetected(f"{tag}: marker gasit in continut -> '{hit}'")
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


def discover_match_links(page, hub_url, tag, limit, log):
    """Navigheaza pe hub-ul unei competitii si extrage link-uri reale de meci.

    Incearca intai /results/ (meciuri finalizate - au statistici/aliniamente
    reale). Daca sezonul curent nu are inca rezultate, cade pe /fixtures/
    (meciuri programate - doar campurile de nivel MATCH sunt aplicabile,
    statisticile/aliniamentele nu exista inca, marcat explicit in raport).
    """
    attempts = [("results", hub_url.rstrip("/") + "/results/"),
                ("fixtures", hub_url.rstrip("/") + "/fixtures/")]
    discovery = {"hub_url": hub_url, "attempts": [], "matches": [], "source_used": None}

    for source_label, url in attempts:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        http_status = resp.status if resp else None
        _check_protection(page, http_status, f"{tag}-{source_label}-hub", log)
        page.wait_for_timeout(POST_LOAD_WAIT_MS)
        _dismiss_gdpr_if_present(page)

        hrefs = page.eval_on_selector_all(
            "a[href*='/match/football/']",
            "els => els.map(e => e.getAttribute('href'))",
        )
        seen = []
        for h in hrefs or []:
            if not h:
                continue
            full = h if h.startswith("http") else f"https://www.flashscore.com{h}"
            full = full.split("#")[0]
            if full not in seen:
                seen.append(full)
        (EVIDENCE_DIR / f"{tag}_{source_label}_hub_raw.html").write_text(page.content(), encoding="utf-8")
        try:
            page.screenshot(path=str(EVIDENCE_DIR / f"{tag}_{source_label}_hub_screenshot.png"))
        except Exception:
            pass

        discovery["attempts"].append({
            "source": source_label, "url": url, "http_status": http_status,
            "links_found": len(seen),
        })

        if seen:
            discovery["matches"] = seen[:limit]
            discovery["source_used"] = source_label
            break

    return discovery


def detect_fields(html_lower: str) -> dict:
    found = {}
    for field, patterns in FIELD_DETECTORS.items():
        hit = next((p for p in patterns if re.search(p, html_lower)), None)
        found[field] = {"heuristic_found": hit is not None, "pattern": hit}
    return found


def inspect_match(page, match_url, tag, index, log):
    record = {
        "match_url": match_url, "tag": tag, "index": index,
        "tabs_visited": {}, "field_detection": {}, "stability": {},
    }
    t0 = time.perf_counter()
    try:
        resp = page.goto(match_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        http_status = resp.status if resp else None
    except Exception as exc:
        record["navigation_error"] = str(exc)
        record["stability"]["playwright_issue"] = True
        return record
    record["stability"]["load_time_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    record["stability"]["http_status"] = http_status
    _check_protection(page, http_status, f"{tag}-{index}-summary", log)
    page.wait_for_timeout(POST_LOAD_WAIT_MS)
    gdpr = _dismiss_gdpr_if_present(page)
    record["stability"]["gdpr_banner_seen"] = gdpr
    record["stability"]["page_fully_loaded"] = True

    slug = match_url.rstrip("/").split("/")[-2:]
    file_prefix = f"{tag}_{index}_{'_'.join(slug)}"[:120]

    combined_lower_chunks = []

    summary_html = page.content()
    combined_lower_chunks.append(summary_html.lower())
    (EVIDENCE_DIR / f"{file_prefix}__summary.html").write_text(summary_html, encoding="utf-8")
    try:
        page.screenshot(path=str(EVIDENCE_DIR / f"{file_prefix}__summary.png"))
    except Exception:
        pass
    record["tabs_visited"]["summary"] = {"found": True, "content_length": len(summary_html)}
    record["page_title"] = page.title()

    for tab_name in TABS:
        try:
            locator = page.get_by_text(tab_name, exact=True).first
            if not locator.is_visible(timeout=2500):
                record["tabs_visited"][tab_name.lower()] = {"found": False, "reason": "not_visible"}
                continue
            locator.click(timeout=3000)
            page.wait_for_timeout(TAB_CLICK_WAIT_MS)
            _check_protection(page, None, f"{tag}-{index}-{tab_name}", log)
            tab_html = page.content()
            combined_lower_chunks.append(tab_html.lower())
            (EVIDENCE_DIR / f"{file_prefix}__{tab_name.lower()}.html").write_text(tab_html, encoding="utf-8")
            record["tabs_visited"][tab_name.lower()] = {"found": True, "content_length": len(tab_html)}
        except ProtectionDetected:
            raise
        except Exception as exc:
            record["tabs_visited"][tab_name.lower()] = {"found": False, "reason": str(exc)[:200]}

    record["field_detection"] = detect_fields("\n".join(combined_lower_chunks))
    return record


def main() -> dict:
    from playwright.sync_api import sync_playwright

    result = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "log": [],
        "discovery": {},
        "matches": [],
        "stopped_due_to_protection": None,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            superliga_discovery = discover_match_links(page, SUPERLIGA_HUB, "superliga", MATCHES_PER_COMPETITION, result["log"])
            result["discovery"]["superliga"] = superliga_discovery

            ucl_discovery = discover_match_links(page, UCL_HUB, "ucl", MATCHES_PER_COMPETITION, result["log"])
            result["discovery"]["ucl"] = ucl_discovery

            all_targets = (
                [("superliga", url) for url in superliga_discovery["matches"]]
                + [("ucl", url) for url in ucl_discovery["matches"]]
            )

            for i, (tag, url) in enumerate(all_targets, start=1):
                record = inspect_match(page, url, tag, i, result["log"])
                result["matches"].append(record)
                time.sleep(POLITENESS_DELAY_S)

        except ProtectionDetected as exc:
            result["stopped_due_to_protection"] = str(exc)

        browser.close()

    result["total_matches_tested"] = len(result["matches"])
    return result


if __name__ == "__main__":
    output = main()
    report_path = EVIDENCE_DIR / "poc_flashscore_10matches_result.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in output.items() if k != "log"}, indent=2, ensure_ascii=False))
