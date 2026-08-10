"""
================================================================================
POC IZOLAT, TEMPORAR — structura reală eloratings.net, randată (2026-08-10)
================================================================================
Etapa 2 a investigației: confirmat deja (rulare anterioară, requests +
BeautifulSoup) că HTML-ul brut are 1815 bytes, zero <table>, zero nume de
echipe — pagina folosește SlickGrid (slick.grid.js/slick.core.js) + jQuery,
un grid randat 100% client-side, fără date deloc în răspunsul HTTP inițial.

Acest script randază pagina real, într-un Chromium headless (Playwright —
deja dependință activă a proiectului, folosită pentru Flashscore), așteaptă
conținutul, și raportează structura DOM finală — pentru ca extragerea reală
(EloRatingsAdapter) să fie scrisă pe baza structurii verificate, nu ghicite.

Nu importă oracle_api.py/key_manager.py, nu scrie nicăieri. Se șterge din
cod după închiderea investigației.
================================================================================
"""
from __future__ import annotations

import sys

ELO_URL = "https://www.eloratings.net"


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            print(f"[POC] goto {ELO_URL}")
            resp = page.goto(ELO_URL, wait_until="networkidle", timeout=30000)
            print(f"[POC] HTTP status: {resp.status if resp else 'N/A'}")

            page.wait_for_timeout(2000)

            html = page.content()
            print(f"[POC] Lungime HTML randat: {len(html)}")

            body_text = page.inner_text("body")
            print(f"[POC] Lungime text vizibil (body): {len(body_text)}")
            for needle in ["Argentina", "Brazil", "France", "Spain"]:
                idx = body_text.find(needle)
                print(f"[POC] '{needle}' găsit la offset {idx}" if idx >= 0
                      else f"[POC] '{needle}' NU apare în textul randat")

            # SlickGrid markup real — clase standard ale librăriei.
            grid_containers = page.query_selector_all("[class*='slick']")
            print(f"[POC] Elemente cu clasă conținând 'slick': {len(grid_containers)}")

            rows = page.query_selector_all(".slick-row")
            print(f"[POC] Elemente .slick-row găsite: {len(rows)}")
            for i, row in enumerate(rows[:8]):
                cells = row.query_selector_all(".slick-cell")
                cell_texts = [c.inner_text().strip() for c in cells]
                print(f"[POC]   rând {i}: {cell_texts}")

            # Fallback generic: dacă .slick-row nu există, căutăm orice
            # element ale cărui text conține un nume de echipă cunoscut,
            # ca să găsim containerul real.
            if not rows:
                print("[POC] .slick-row absent — caut containerul real prin text cunoscut")
                el = page.query_selector("text=Argentina")
                if el:
                    print(f"[POC] Element găsit pentru 'Argentina': "
                          f"tag={el.evaluate('e => e.tagName')} class={el.evaluate('e => e.className')}")
                    parent_html = el.evaluate("e => e.parentElement ? e.parentElement.outerHTML : null")
                    print(f"[POC] outerHTML părinte (primele 2000 caractere):\n{(parent_html or '')[:2000]}")
                else:
                    print("[POC] Niciun element nu conține textul 'Argentina' nici după randare completă.")
                    print(f"[POC] Primele 2000 caractere din body_text:\n{body_text[:2000]}")

        finally:
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
