"""
================================================================================
POC IZOLAT, TEMPORAR — coloana FORMĂ din pagina de clasament Flashscore
(2026-08-10)
================================================================================
Context: ADR-045, Owner Standings (#3) — `flashscore_standings_snapshot`
persistă azi doar rank/played/won/drawn/lost/goals_for/goals_against/
goal_diff/points (vezi `database.queries.get_standings_snapshot()`), FĂRĂ
nicio secvență de formă recentă. Captură de ecran a proprietarului
produsului (flashscore.ro, ROMÂNIA: SUPERLIGA, tab CLASAMENT) arată o
coloană "FORMĂ" cu 4-5 badge-uri colorate (V/E/Î) per echipă — exact
secvența cronologică de care are nevoie `feature_engine.compute_form_score()`
(cere explicit ordine cronologică, cel mai recent ULTIM).

Acest script randază pagina de clasament reală (Playwright, Chromium
headless — tipar identic POC-ului eloratings.net) și raportează structura
DOM exactă a coloanei FORMĂ — ordine, text, culoare/clasă, orice atribut
title/tooltip cu detalii de meci — înainte ca extragerea reală să fie
scrisă pe baza structurii verificate, nu ghicite.

Nu importă oracle_api.py/key_manager.py/discovery.py, nu scrie nicăieri.
Se șterge din cod după închiderea investigației.
================================================================================
"""
from __future__ import annotations

import sys

STANDINGS_URL = "https://www.flashscore.com/football/romania/superliga/standings/"

_PROTECTION_MARKERS = (
    "checking your browser", "cf-browser-verification", "attention required",
    "captcha-delivery", "access denied", "ray id",
    "sorry, you have been blocked", "just a moment...",
    "verify you are human", "unusual traffic from your computer",
    "please verify you are a human", "detected unusual activity",
)


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            print(f"[POC] goto {STANDINGS_URL}")
            resp = page.goto(STANDINGS_URL, wait_until="networkidle", timeout=30000)
            print(f"[POC] HTTP status: {resp.status if resp else 'N/A'}")

            page.wait_for_timeout(2000)

            html = page.content()
            print(f"[POC] Lungime HTML randat: {len(html)}")

            body_text = page.inner_text("body")
            lower = body_text.lower()
            hit = next((m for m in _PROTECTION_MARKERS if m in lower), None)
            if hit:
                print(f"[POC] SEMN DE PROTECȚIE detectat: '{hit}' — opresc, nu continui.")
                print(f"[POC] Primele 1500 caractere din body_text:\n{body_text[:1500]}")
                return 1

            for needle in ["FC Arges", "FORM", "last 5 matches"]:
                idx = body_text.find(needle)
                print(f"[POC] '{needle}' găsit la offset {idx}" if idx >= 0
                      else f"[POC] '{needle}' NU apare în textul randat")

            # Rândurile de clasament — echipa reala pe site-ul .com (englez,
            # fara diacritice): "FC Arges", nu "FC Argeș" (.ro).
            row_el = page.query_selector("text=FC Arges")
            if row_el is None:
                print("[POC] Niciun element nu conține 'FC Arges' — pagina nu s-a randat cum era așteptat.")
                print(f"[POC] Primele 3000 caractere din body_text:\n{body_text[:3000]}")
                return 0

            print(f"[POC] Element găsit pentru 'FC Arges': "
                  f"tag={row_el.evaluate('e => e.tagName')} class={row_el.evaluate('e => e.className')}")

            # Căutare generică: orice element ale cărui text e EXACT "W", "D",
            # "L" sau "?" (badge-uri de formă, site .com englez) — raportăm
            # clasă + title/aria + outerHTML complet (primele 6 găsite per
            # literă), ca să confirmăm ordinea reală (index DOM = ordine
            # cronologică?) și eventuale atribute cu data meciului.
            for letter in ["W", "D", "L", "?"]:
                els = page.query_selector_all(f"xpath=//*[text()='{letter}']")
                print(f"[POC] Elemente cu text exact '{letter}': {len(els)}")
                for el in els[:6]:
                    cls = el.evaluate("e => e.className")
                    title = el.evaluate("e => e.getAttribute('title')")
                    aria = el.evaluate("e => e.getAttribute('aria-label')")
                    tag = el.evaluate("e => e.tagName")
                    outer = el.evaluate("e => e.outerHTML")
                    print(f"[POC]   tag={tag} class={cls!r} title={title!r} aria-label={aria!r} outerHTML={outer!r}")

            # Container complet al rândului FC Arges — pentru context de
            # structură (câte niveluri până la celula FORM, ce clasă are
            # celula-container a formei).
            row_container = row_el.evaluate_handle(
                "e => { let n = e; for (let i = 0; i < 6 && n; i++) { n = n.parentElement; } return n; }"
            )
            row_html = row_container.evaluate("e => e ? e.outerHTML : null")
            print(f"[POC] outerHTML container FC Arges (6 nivele sus, primele 5000 caractere):\n{(row_html or '')[:5000]}")

        finally:
            browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
