"""
================================================================================
POC izolat, temporar — Flashscore, verificare live „Missing Players"
================================================================================
Cerut explicit (proprietar produs): înainte de a redirecționa lineup_sync.yml
spre Flashscore (ADR-070 precedent: „tot Flashscore, doar verificat mai des"),
verifică DACĂ Flashscore chiar randează, pentru meciurile urmărite, o listă
reală de jucători absenți (accidentați/suspendați) — nu doar dacă string-ul
de traducere `TRANS_MISSING_PLAYERS` există în bundle-ul JS (prezent pe
ORICE pagină, indiferent de conținut — verificat deja, fals pozitiv posibil).

Regulă strictă: Flashscore NU e o sursă nouă (deja scrapuită în producție,
`providers/flashscore/`, fără blocaj anti-bot documentat) — deci nu se aplică
regula POC-urilor izolate pentru surse noi (fără ocolire anti-bot n-are
sens aici, pentru că nu există nicio protecție de ocolit). Rămâne totuși
izolat: Playwright STANDARD, fără import de cod de producție UDAL, fără
scraper_registry/tos_reviewed, ZERO scriere în Supabase — doar citește și
salvează evidență brută, exact tiparul `_poc_flashscore_10matches_temp.py`.

Testează DOUĂ ipoteze, nu una:
1. Meci LA/DUPĂ fluier (echipa de start confirmată) — dacă vreun widget de
   accidentări există, ar trebui să fie complet populat acum.
2. Meci cu câteva zile înainte — accidentările/suspendările sunt de obicei
   cunoscute cu mult înainte de kickoff (spre deosebire de echipa de start,
   confirmată doar ~1h înainte) — dacă widget-ul există independent de
   fereastra de kickoff, ar trebui să apară și aici.

Detecție STRUCTURALĂ, nu doar text: caută heading-ul vizibil „Missing
Players" (Playwright get_by_text), apoi inspectează conținutul REAL din
jurul lui (nume de jucători, nu doar string-ul de traducere din JS bundle).
================================================================================
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_missing_players"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500
POLITENESS_DELAY_S = 2.0

PROTECTION_MARKERS = (
    "checking your browser", "cf-browser-verification", "attention required",
    "captcha-delivery", "access denied", "ray id",
    "sorry, you have been blocked", "just a moment...",
    "verify you are human", "unusual traffic from your computer",
    "please verify you are a human", "detected unusual activity",
)

# Hub-uri de meciuri viitoare pentru cateva ligi urmarite - gasim link-uri
# reale de meci, nu inventam URL-uri.
FIXTURE_HUBS = [
    ("romania_superliga", "https://www.flashscore.com/football/romania/superliga/fixtures/"),
    ("premier_league", "https://www.flashscore.com/football/england/premier-league/fixtures/"),
]


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


def discover_match_links(page, hub_url, tag, limit, log):
    resp = page.goto(hub_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    http_status = resp.status if resp else None
    _check_protection(page, http_status, f"{tag}-fixtures-hub", log)
    page.wait_for_timeout(POST_LOAD_WAIT_MS)
    _dismiss_gdpr_if_present(page)

    hrefs = page.eval_on_selector_all(
        "a[href*='/match/football/']",
        "els => els.map(e => e.getAttribute('href'))",
    )
    seen: list[str] = []
    for h in hrefs or []:
        if not h:
            continue
        full = h if h.startswith("http") else f"https://www.flashscore.com{h}"
        full = full.split("#")[0]
        if full not in seen:
            seen.append(full)
    return seen[:limit]


def _find_missing_players_widget(page) -> dict:
    """Detecție STRUCTURALĂ — caută heading-ul vizibil „Missing Players",
    apoi extrage textul din containerul lui (nume reale, nu string de
    traducere). Un heading găsit dar fără nume dedesubt = widget exista dar
    gol pentru acest meci (posibil, nu presupus). Niciun heading găsit =
    widget-ul nu se randeaza deloc aici."""
    result = {"heading_found": False, "container_text": None, "container_html_length": 0}
    try:
        heading = page.get_by_text("Missing Players", exact=False).first
        if heading.is_visible(timeout=2000):
            result["heading_found"] = True
            try:
                container = heading.locator(
                    "xpath=ancestor::div[contains(@class,'wcl-') or contains(@class,'section')][1]",
                )
                text = container.inner_text(timeout=2000)
                result["container_text"] = text[:2000]
                result["container_html_length"] = len(container.inner_html(timeout=2000))
            except Exception as exc:
                result["container_error"] = str(exc)[:200]
    except Exception as exc:
        result["lookup_error"] = str(exc)[:200]
    return result


def inspect_match(page, match_url, tag, index, log) -> dict:
    record: dict = {"match_url": match_url, "tag": tag, "index": index}
    resp = page.goto(match_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    http_status = resp.status if resp else None
    _check_protection(page, http_status, f"{tag}-{index}-summary", log)
    page.wait_for_timeout(POST_LOAD_WAIT_MS)
    _dismiss_gdpr_if_present(page)
    record["page_title"] = page.title()

    slug = match_url.rstrip("/").split("/")[-2:]
    file_prefix = f"{tag}_{index}_{'_'.join(slug)}"[:120]

    # Tab summary — unele site-uri arata "Missing Players" direct pe pagina
    # principala de meci, nu doar pe un tab dedicat.
    summary_html = page.content()
    (EVIDENCE_DIR / f"{file_prefix}__summary.html").write_text(summary_html, encoding="utf-8")
    record["summary_missing_players"] = _find_missing_players_widget(page)

    # Tab Lineups — daca exista, e cel mai probabil loc.
    try:
        locator = page.get_by_text("Lineups", exact=True).first
        if locator.is_visible(timeout=2500):
            locator.click(timeout=3000)
            page.wait_for_timeout(1800)
            _check_protection(page, None, f"{tag}-{index}-lineups", log)
            lineups_html = page.content()
            (EVIDENCE_DIR / f"{file_prefix}__lineups.html").write_text(lineups_html, encoding="utf-8")
            record["lineups_missing_players"] = _find_missing_players_widget(page)
        else:
            record["lineups_missing_players"] = {"tab_not_visible": True}
    except ProtectionDetected:
        raise
    except Exception as exc:
        record["lineups_missing_players"] = {"tab_error": str(exc)[:200]}

    return record


def main() -> dict:
    from playwright.sync_api import sync_playwright

    result: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "log": [], "discovery": {}, "matches": [],
        "stopped_due_to_protection": None,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            all_targets: list[tuple[str, str]] = []
            for tag, hub in FIXTURE_HUBS:
                links = discover_match_links(page, hub, tag, limit=3, log=result["log"])
                result["discovery"][tag] = links
                all_targets.extend((tag, url) for url in links)
                time.sleep(POLITENESS_DELAY_S)

            for i, (tag, url) in enumerate(all_targets, start=1):
                record = inspect_match(page, url, tag, i, result["log"])
                result["matches"].append(record)
                time.sleep(POLITENESS_DELAY_S)
        except ProtectionDetected as exc:
            result["stopped_due_to_protection"] = str(exc)
        finally:
            browser.close()

    result["total_matches_tested"] = len(result["matches"])
    result["summary"] = {
        "any_missing_players_heading_found": any(
            (m.get("summary_missing_players", {}) or {}).get("heading_found")
            or (m.get("lineups_missing_players", {}) or {}).get("heading_found")
            for m in result["matches"]
        ),
        "matches_with_real_names_under_heading": sum(
            1 for m in result["matches"]
            if (m.get("summary_missing_players", {}) or {}).get("container_text")
            or (m.get("lineups_missing_players", {}) or {}).get("container_text")
        ),
    }
    return result


if __name__ == "__main__":
    output = main()
    report_path = EVIDENCE_DIR / "poc_flashscore_missing_players_result.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in output.items() if k != "log"}, indent=2, ensure_ascii=False))
