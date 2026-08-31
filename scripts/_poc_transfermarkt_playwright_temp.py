"""
================================================================================
UDAL — POC_TRANSFERMARKT_PLAYWRIGHT (izolat, temporar, GitHub Actions)
================================================================================
Continuare directă a `_poc_transfermarkt_injuries_temp.py` (2 rulări,
2026-08-31): cereri HTTP oneste (requests, header-e complete, domeniu
.com ȘI .us) au primit uniform `x-amzn-waf-action: challenge` (AWS WAF) —
o poartă activă de verificare anti-bot, nu o lipsă de header.

Acest POC testează dacă un Playwright STANDARD — exact tiparul deja
folosit în producție pentru Flashscore (`providers/flashscore/`,
headless, fără patchright/stealth/proxy/fingerprint spoofing/TLS
spoofing) — trece de acea verificare prin simpla randare normală a
paginii (executare JS reală, ca efect secundar al încărcării, nu o
rezolvare deliberată de captcha).

REGULĂ CRITICĂ, respectată strict: dacă provocarea AWS WAF se dovedește
a fi un CAPTCHA INTERACTIV (widget cu imagini de selectat, puzzle, etc.)
— NU se încearcă nicio interacțiune cu el. Testul se oprește imediat,
raportează exact ce a găsit, și cazul rămâne închis. Se testează DOAR
dacă randarea pasivă (navigare + așteptare, fără click-uri, fără
rezolvare) permite accesul — nu se ocolește nimic activ.

Nu importă `key_manager.py`/`scraper_registry.py`/orice modul de
producție. NU scrie nicăieri în Supabase. Rulează DOAR pe
`workflow_dispatch` manual. Se șterge din cod după închiderea
investigației — dovada rămâne în istoricul rulării GitHub Actions +
CLAUDE.md.
================================================================================
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

EVIDENCE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "transfermarkt_playwright"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 5000  # marjă mai mare — provocările WAF au nevoie de timp să se rezolve singure
POLITENESS_DELAY_S = 3.0

_PREMIER_LEAGUE_URL = "https://www.transfermarkt.com/premier-league/startseite/wettbewerb/GB1"

# Marcaje de PROVOCARE INTERACTIVĂ — dacă apar, ne oprim, NU interacționăm.
_INTERACTIVE_CAPTCHA_MARKERS = (
    "select all images", "i'm not a robot", "hcaptcha", "recaptcha",
    "click each image", "verify you are human by",
    "prove you are human", "solve the puzzle",
)
# Marcaje de blocare/provocare generice (informativ, nu opresc testul —
# doar un JS-challenge tranzitoriu, nu neaparat interactiv).
_SOFT_CHALLENGE_MARKERS = (
    "awswaf", "checking your browser", "just a moment", "please wait",
)


class InteractiveCaptchaDetected(Exception):
    pass


def _save(label: str, content: str) -> None:
    safe = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:120]
    (EVIDENCE_DIR / f"{safe}.html").write_text(content, encoding="utf-8")


def _check_for_interactive_captcha(html_lower: str, tag: str) -> None:
    hit = next((m for m in _INTERACTIVE_CAPTCHA_MARKERS if m in html_lower), None)
    if hit:
        raise InteractiveCaptchaDetected(f"{tag}: marcaj de captcha interactiv găsit -> '{hit}'")


def _inspect(page, url: str, tag: str) -> dict:
    entry: dict = {"tag": tag, "url": url}
    resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    entry["http_status"] = resp.status if resp else None
    page.wait_for_timeout(POST_LOAD_WAIT_MS)

    html = page.content()
    html_lower = html.lower()
    _check_for_interactive_captcha(html_lower, tag)  # oprește execuția dacă găsește

    entry["page_title"] = page.title()
    entry["content_length"] = len(html)
    entry["soft_challenge_markers_found"] = [m for m in _SOFT_CHALLENGE_MARKERS if m in html_lower]

    _save(tag, html)

    # Semnal ca am trecut de provocare: link-uri reale de club Transfermarkt.
    club_links = sorted(set(re.findall(r'href="(/[a-z0-9-]+/startseite/verein/\d+)"', html)))
    entry["real_club_links_found"] = club_links[:10]
    entry["real_club_links_count"] = len(club_links)

    return entry


def main() -> dict:
    from playwright.sync_api import sync_playwright

    result: dict = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "checks": [], "stopped_due_to_interactive_captcha": None,
    }

    with sync_playwright() as p:
        # Playwright STANDARD — identic tiparului de productie Flashscore:
        # headless=True, fara executable_path custom, fara argumente de
        # stealth, fara proxy.
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            entry = _inspect(page, _PREMIER_LEAGUE_URL, "premier_league_hub")
            result["checks"].append(entry)

            # Daca am gasit link-uri reale de club, mergem un pas mai departe
            # - pagina unui club real, cautam link spre accidentari.
            if entry.get("real_club_links_count"):
                club_path = entry["real_club_links_found"][0]
                club_url = f"https://www.transfermarkt.com{club_path}"
                time.sleep(POLITENESS_DELAY_S)
                club_entry = _inspect(page, club_url, "club_profile")
                result["checks"].append(club_entry)
        except InteractiveCaptchaDetected as exc:
            result["stopped_due_to_interactive_captcha"] = str(exc)
        finally:
            browser.close()

    any_real_content = any(c.get("real_club_links_count", 0) > 0 for c in result["checks"])
    result["summary"] = {
        "any_real_club_links_found": any_real_content,
        "conclusion": (
            "Playwright standard a trecut de provocarea AWS WAF prin randare normala."
            if any_real_content else
            "Playwright standard NU a trecut de provocare — nici randarea pasiva nu e suficienta."
        ),
    }
    return result


if __name__ == "__main__":
    output = main()
    report_path = EVIDENCE_DIR / "poc_transfermarkt_playwright_result.json"
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(output, indent=2, ensure_ascii=False))
