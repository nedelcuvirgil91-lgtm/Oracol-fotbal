"""POC izolat, TEMPORAR — de ce s-a oprit extragerea statisticilor pe 8 sep.

NU importă NIMIC din codul de producție. Playwright direct, zero scriere,
zero credențiale de bază de date. Se șterge după închiderea investigației;
dovada rămâne în istoricul rulărilor GitHub Actions (tiparul deja aplicat de
5 ori în proiect).

### Ce s-a măsurat deja, și de ce POC-ul arată exact ce arată

`match_statistics_extended`, `player_match_stats` și
`player_match_stats_extended` au ZERO rânduri scrise după **2026-09-08** — 39
de zile. În aceeași perioadă `flashscore_match_context` (H2H) și
`match_events` scriu normal, deci NU e rețea, NU e autentificare, NU e
scriere în bază.

Comparația extragerilor BRUTE o localizează și mai fin. Aceeași structură,
același provider:
  7 sep : home_shots=22, away_shots=12, home_fouls=13, lineup=[11 jucători]
  azi   : home_shots=null, away_shots=null, home_fouls=null, lineup=[]
Iar în ambele: arbitru, stadion, capacitate, scor — corecte.

Deci se rup DOUĂ lucruri, împreună: tabelul de statistici și aliniamentele.

### Ipoteza testată aici

`normalizer._extract_labeled_stat_pairs()` se sprijină pe trei atribute:
    [data-testid='wcl-statistics']
    [data-testid='wcl-statistics-category']
    [data-testid='wcl-statistics-value']
Dacă Flashscore le-a redenumit, `soup.select(...)` întoarce listă goală,
funcția întoarce `{}`, și fiecare statistică devine `null` — fără excepție,
fără log, fără niciun semnal. Exact tăcerea observată.

POC-ul NU presupune că asta e cauza. Numără ce există pe pagina de AZI și
tipărește inventarul real de `data-testid`, ca să se vadă dacă atributele au
dispărut, s-au redenumit, sau sunt acolo și problema e alta.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

# Două meciuri REALE, deja în istoricul nostru, ambele terminate:
#   - unul dinainte de ruptură (7 sep), ca referință;
#   - unul de după (9 oct), cazul de reparat.
# Alese astfel ca diferența dintre ele să nu poată fi pusă pe seama ligii:
# ambele din competiții urmărite, ambele cu `has_stats = true` în
# `flashscore_data_completeness`.
MECIURI = [
    # Un singur meci pentru rularea decisiva: Everton-Chelsea, 17.10.2026,
    # cel din captura proprietarului produsului — terminat 0-2, tab STATS
    # plin pe ecran, iar la noi `actual_result` si xG NULL.
    ("DEFECT 17 oct (Everton-Chelsea)", "https://www.flashscore.com/match/football/2wo3m634"),
]

# 🔴 [CORECTAT A DOUA OARA] A doua rulare a dat pagini de ~10.9 KB cu ZERO
# `data-testid` pe toate trei — adica zidul de consimtamant, nu continutul.
# Garda de randare a prins-o si a spus corect INCONCLUZIV, dar cauza erau
# iar DOUA diferente fata de productie, ambele ale mele:
#
#   `providers/flashscore/adapter.py:185-190`
#       url = f"{match_base_url}/{suffix}?mid={mid}"   <- `?mid=` lipsea
#       if tab_name == "summary": _dismiss_gdpr_if_present(page)
#
# Productia viziteaza INTAI `summary`, respinge bannerul GDPR, si refoloseste
# ACEEASI pagina pentru restul tab-urilor — deci consimtamantul se da o data
# si tine pentru toate. POC-ul mergea direct pe `stats`, pe o pagina noua,
# fara `?mid=`.
#
# Lectia, a treia oara in aceeasi investigatie: un POC care nu reproduce
# EXACT calea productiei nu masoara defectul, masoara propria lui diferenta.
MID_DIN_URL = re.compile(r"/match/football/([A-Za-z0-9]+)")

# Reproduse din adapter.py ca VALORI, nu prin import (garda de izolare a
# POC-urilor interzice importul modulelor de productie).
SELECTOARE_GDPR = (
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept & continue')",
    "button:has-text('Accept all')",
    "button:has-text('I Accept')",
)
NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500


def _respinge_gdpr(page) -> bool:
    for selector in SELECTOARE_GDPR:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=2000)
                page.wait_for_timeout(500)
                return True
        except Exception:
            continue
    return False

# 🔴 [CORECTAT dupa prima rulare — eroarea era in POC, nu in diagnostic]
# Prima versiune folosea navigarea prin HASH (`#/match-summary/match-
# statistics/0`). Rezultatul: `wcl-statistics` -> 5 potriviri si
# `-category`/`-value` -> 0, IDENTIC pe ambele pagini, inclusiv pe cea din
# 7 septembrie despre care stim sigur ca a functionat in productie
# (`home_shots=22` e in baza noastra). Deci POC-ul nu incarcase tab-ul real:
# cele 5 potriviri erau widget-ul RESTRANS din sumar — exact „5 categorii"
# pe care docstring-ul lui `normalize_match_statistics()` le descrie ca
# fallback.
#
# Productia foloseste o CALE, nu un hash: `_MATCH_TAB_SUFFIXES` din
# `providers/flashscore/adapter.py` da `"stats": "summary/stats/"`.
# Reprodus acum identic, altfel POC-ul masoara altceva decat codul reparat.
SUFIX_TAB_STATS = "summary/stats/"

# Semnal de randare: daca textul asta nu e in HTML, pagina nu s-a terminat de
# incarcat si orice numaratoare de selectori e lipsita de sens. Verificat pe
# captura live a proprietarului produsului (Everton-Chelsea, 17.10.2026):
# sectiunea „Expected goals (xG)" apare pe tab-ul de statistici.
MARCAJ_RANDARE = "Expected goals"

SELECTORI_ASTEPTATI = (
    "[data-testid='wcl-statistics']",
    "[data-testid='wcl-statistics-category']",
    "[data-testid='wcl-statistics-value']",
)


def _inventar_testid(html: str) -> Counter:
    """Toate valorile `data-testid` de pe pagină, numărate. Dacă familia
    `wcl-statistics*` a fost redenumită, numele NOU apare aici — fără să
    trebuiască ghicit."""
    return Counter(re.findall(r'data-testid="([^"]+)"', html))


def _dump_zona_statistici(html: str, context: int = 1100) -> None:
    """Tipareste HTML-ul din jurul primei aparitii a marcajului. Asta e ce
    trebuie sa citeasca reparatia: structura REALA de azi, nu una ghicita.

    Fara el, as sti doar CA selectorul nu merge, nu si CU CE sa-l inlocuiesc —
    adica exact situatia care a produs trei rulari irosite."""
    poz = html.find(MARCAJ_RANDARE)
    if poz < 0:
        print("  (marcajul nu e în HTML — nimic de arătat)")
        return
    start = max(0, poz - context)
    fragment = html[start:poz + context]
    print(f"\n  --- HTML în jurul '{MARCAJ_RANDARE}' (poziția {poz}) ---")
    print("  " + fragment.replace("\n", " ")[:2200])
    print("  --- sfârșit fragment ---")


def _raport(eticheta: str, html: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    gasite = {s: len(soup.select(s)) for s in SELECTORI_ASTEPTATI}
    inventar = _inventar_testid(html)

    # Orice `data-testid` care seamănă a statistică, indiferent de nume —
    # asta descoperă redenumirea, în loc s-o presupună.
    candidati = {k: v for k, v in inventar.items()
                 if "stat" in k.lower() or "wcl" in k.lower()}

    randat = MARCAJ_RANDARE in html

    print(f"\n{'=' * 78}\n  {eticheta}\n{'=' * 78}")
    print(f"  lungime HTML                 : {len(html)} octeți")
    print(f"  conține '{MARCAJ_RANDARE}'    : {'DA' if randat else 'NU'}"
          f"{'' if randat else '   <-- pagina NU s-a randat; cifrele de mai jos nu spun nimic'}")
    print(f"  total atribute data-testid   : {sum(inventar.values())} "
          f"({len(inventar)} distincte)")
    print("  SELECTORII FOLOSIȚI AZI ÎN PRODUCȚIE:")
    for s, n in gasite.items():
        print(f"     {'✅' if n else '❌'} {s:48} -> {n} potriviri")
    print(f"  candidați ('stat' sau 'wcl' în nume): {len(candidati)}")
    for k, v in sorted(candidati.items(), key=lambda x: -x[1])[:25]:
        print(f"     {v:5}x  {k}")
    if not candidati:
        print("     (niciunul — pagina nu mai conține nimic de forma asta)")
        print("  TOP 25 data-testid de pe pagină, ca punct de plecare:")
        for k, v in inventar.most_common(25):
            print(f"     {v:5}x  {k}")
    return {"eticheta": eticheta, "octeti": len(html), "randat": randat,
            "selectori": gasite, "candidati": dict(candidati),
            "total_testid": sum(inventar.values())}


def main() -> int:
    from playwright.sync_api import sync_playwright

    rezultate = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            eticheta, base = MECIURI[0]
            mid = MID_DIN_URL.search(base).group(1)

            page.goto(f"{base}/?mid={mid}", timeout=NAV_TIMEOUT_MS,
                      wait_until="domcontentloaded")
            if _respinge_gdpr(page):
                print("  banner GDPR respins")
            page.wait_for_timeout(POST_LOAD_WAIT_MS)

            def _nr_statistici() -> int:
                return page.evaluate(
                    "document.querySelectorAll(\"[data-testid='wcl-statistics']\").length")

            print(f"\n{'#' * 78}\n  {eticheta}\n{'#' * 78}")
            print(f"  [1] pe SUMMARY: {_nr_statistici()} rânduri wcl-statistics "
                  "(widgetul restrâns, ~5)")

            # ÎNTREBAREA 1 — care e URL-ul REAL al tabului de statistici?
            # Il citesc de pe pagina, din href-ul linkului, in loc sa-l ghicesc.
            print("\n  [2] LINKURI DE TAB găsite pe pagină (href REAL, nu ghicit):")
            linkuri = page.evaluate("""
                Array.from(document.querySelectorAll('a[href], button[data-analytics-alias]'))
                  .map(e => ({
                      text: (e.innerText || '').trim().slice(0, 28),
                      href: e.getAttribute('href') || '',
                      alias: e.getAttribute('data-analytics-alias') || ''
                  }))
                  .filter(o => /stat/i.test(o.text) || /stat/i.test(o.href) || /stat/i.test(o.alias))
                  .slice(0, 12)
            """)
            for l in linkuri:
                print(f"      text={l['text']!r:32} alias={l['alias']!r:20} href={l['href']!r}")
            if not linkuri:
                print("      (niciunul — tabul nu e un link, probabil buton SPA)")

            # ÎNTREBAREA 2 — ajunge tabul COMPLET (~36 categorii)?
            # Se face ca un UTILIZATOR: click, nu navigare construita de mine.
            print("\n  [3] CLICK pe tabul de statistici (ca un utilizator):")
            apasat = False
            for sel in ("a[href*='match-statistics']",
                        "button:has-text('Stats')", "a:has-text('Stats')",
                        "[data-analytics-alias*='statistics']"):
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2500):
                        el.click(timeout=3000)
                        print(f"      apăsat: {sel}")
                        apasat = True
                        break
                except Exception:
                    continue
            if not apasat:
                print("      n-am găsit niciun element de apăsat")

            page.wait_for_timeout(POST_LOAD_WAIT_MS)
            try:
                page.wait_for_function(
                    "document.querySelectorAll(\"[data-testid='wcl-statistics']\").length > 10",
                    timeout=15000)
            except Exception:
                print("      rândurile n-au trecut de 10 în 15 s")

            n_dupa = _nr_statistici()
            print(f"      URL după click : {page.url}")
            print(f"      rânduri ACUM   : {n_dupa}")
            html = page.content()
            r = _raport(f"{eticheta} / după click", html)
            r["randuri_dupa_click"] = n_dupa
            _dump_zona_statistici(html)
            rezultate.append(r)

            print(f"\n{'=' * 78}\n  VERDICT\n{'=' * 78}")
            if n_dupa > 10:
                print(f"  TABUL COMPLET SE ÎNCARCĂ ({n_dupa} rânduri).")
                print(f"  URL-ul care îl produce: {page.url}")
                print("  -> reparația are DOUĂ părți: URL-ul din _MATCH_TAB_SUFFIXES")
                print("     ȘI selectorii copiilor din _extract_labeled_stat_pairs.")
            else:
                print(f"  DOAR {n_dupa} rânduri — tabul complet NU s-a încărcat.")
                print("  -> nu scriu reparația pe o structură pe care n-am văzut-o.")
        finally:
            page.close()
            browser.close()

    print("\nJSON:", json.dumps(rezultate, ensure_ascii=False)[:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
