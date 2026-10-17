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
    """Toate cele 7 taburi, cu BAZA REALA a productiei (sloguri de echipa).

    🔴 CORECTIE MAJORA fata de rularile anterioare. Testasem
    `/match/football/<mid>/summary/stats/` — o forma pe care productia NU o
    foloseste NICIODATA. `match_base_url` nu e construit de noi: vine din
    Discovery, care citeste `a[href*='/match/football/']` de pe hub, iar acele
    linkuri contin DEJA slogurile de echipa. Verificat pe dovada salvata in
    repo (docs/06_UDAL/poc_evidence/.../superliga_results_hub_raw.html):

        href=".../match/football/fc-botosani-GjY1JjUS/rapid-bucuresti-YFCpigVG/?mid=EeqI7WJc"

    Deci productia cere deja forma cu sloguri. Concluzia mea precedenta —
    „mid-ul singur nu merge, deci reparatie mare" — se sprijinea pe o
    comparatie intre doua forme pe care productia nu le foloseste.

    Intrebarea REALA, netestata pana acum: cu baza corecta, mai raspunde
    sufixul `summary/stats/` al productiei, sau cere `overall/`?
    """
    from playwright.sync_api import sync_playwright

    mid = "2wo3m634"
    # Baza REALA, citita din href-ul descoperit pe pagina (nu construita).
    BAZA = "https://www.flashscore.com/match/football/chelsea-4fGZN2oK/everton-KluSTr9s"

    TABURI = {
        "summary":      ("",                      "Referee"),
        "stats":        ("summary/stats/",         "Expected goals"),
        "lineups":      ("summary/lineups/",       "Formation"),
        "player_stats": ("summary/player-stats/",  "Minutes played"),
        "odds":         ("odds/",                  "1X2"),
        "h2h":          ("h2h/",                   "Head-to-head"),
        "standings":    ("standings/",             "Rank"),
    }
    # Variante de verificat DOAR daca sufixul productiei cade.
    ALTERNATIVE = {
        "stats":        "summary/stats/overall/",
        "player_stats": "summary/player-stats/overall/",
    }

    rezultate = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(f"{BAZA}/?mid={mid}", timeout=NAV_TIMEOUT_MS,
                      wait_until="domcontentloaded")
            if _respinge_gdpr(page):
                print("  banner GDPR respins")
            page.wait_for_timeout(POST_LOAD_WAIT_MS)

            def _masoara(sufix: str, marcaj: str) -> dict:
                page.goto(f"{BAZA}/{sufix}?mid={mid}", timeout=NAV_TIMEOUT_MS,
                          wait_until="domcontentloaded")
                page.wait_for_timeout(POST_LOAD_WAIT_MS)
                html = page.content()
                n = page.evaluate(
                    "document.querySelectorAll(\"[data-testid='wcl-statistics']\").length")
                return {"octeti": len(html), "marcaj": marcaj.lower() in html.lower(),
                        "statistici": n,
                        "viu": len(html) > 50000 and marcaj.lower() in html.lower()}

            print(f"\n{'#' * 78}")
            print("  CELE 7 TABURI, cu BAZA REALA a productiei (sloguri de echipa)")
            print(f"{'#' * 78}")
            print(f"  {'tab':<14}{'sufix productie':<28}{'octeti':>9}{'marcaj':>8}  verdict")
            print(f"  {'-' * 76}")

            for nume, (sufix, marcaj) in TABURI.items():
                try:
                    m = _masoara(sufix, marcaj)
                    print(f"  {nume:<14}{sufix or '(radacina)':<28}{m['octeti']:>9}"
                          f"{('DA' if m['marcaj'] else 'NU'):>8}  "
                          f"{'VIU' if m['viu'] else '*** MORT ***'}")
                    m.update({"tab": nume, "sufix": sufix})
                    rezultate.append(m)
                except Exception as exc:
                    print(f"  {nume:<14}{sufix:<28}{'EROARE':>9}  {exc}")
                    rezultate.append({"tab": nume, "eroare": str(exc)})

            morti = [r for r in rezultate if r.get("viu") is False]
            if morti:
                print(f"\n  --- pentru taburile moarte, incerc varianta cu perioada ---")
                for r in morti:
                    alt = ALTERNATIVE.get(r["tab"])
                    if not alt:
                        print(f"  {r['tab']:<14}(nu am alternativa de incercat)")
                        continue
                    marcaj = TABURI[r["tab"]][1]
                    try:
                        m = _masoara(alt, marcaj)
                        print(f"  {r['tab']:<14}{alt:<28}{m['octeti']:>9}"
                              f"{('DA' if m['marcaj'] else 'NU'):>8}  "
                              f"{'VIU' if m['viu'] else 'tot mort'}")
                        r["alternativa"] = {"sufix": alt, **m}
                    except Exception as exc:
                        print(f"  {r['tab']:<14}{alt:<28}EROARE  {exc}")

        finally:
            page.close()
            browser.close()

    print(f"\n{'=' * 78}\n  VERDICT\n{'=' * 78}")
    morti = [r for r in rezultate if r.get("viu") is False]
    reparabile = [r for r in morti if r.get("alternativa", {}).get("viu")]

    if not morti:
        print("  TOATE taburile raspund cu forma ACTUALA a productiei.")
        print("  -> URL-ul NU e defect. Ruptura e DOAR in selectori.")
        print("     REPARATIE MICA: _extract_labeled_stat_pairs + lineups.")
    elif reparabile and len(reparabile) == len(morti):
        print(f"  Taburile moarte ({[r['tab'] for r in morti]}) revin cu sufixul")
        print("  de perioada (`overall/`).")
        print("  -> REPARATIE MEDIE: sufixele din _MATCH_TAB_SUFFIXES + selectorii.")
        print("     NU e nevoie de descoperirea URL-ului per meci — baza e deja buna.")
    else:
        print(f"  Moarte: {[r['tab'] for r in morti]}; recuperate: "
              f"{[r['tab'] for r in reparabile]}")
        print("  -> reparatia difera pe taburi; ADR-ul le trateaza separat.")

    print("\nJSON:", json.dumps(rezultate, ensure_ascii=False)[:1400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
