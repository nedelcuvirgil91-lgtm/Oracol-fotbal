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
    ("REFERINTA  7 sep", "https://www.flashscore.com/match/football/MN1IRPIG/"),
    ("DEFECT     9 oct", "https://www.flashscore.com/match/football/YiWPvQZg/"),
]

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


def _raport(eticheta: str, html: str) -> dict:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    gasite = {s: len(soup.select(s)) for s in SELECTORI_ASTEPTATI}
    inventar = _inventar_testid(html)

    # Orice `data-testid` care seamănă a statistică, indiferent de nume —
    # asta descoperă redenumirea, în loc s-o presupună.
    candidati = {k: v for k, v in inventar.items()
                 if "stat" in k.lower() or "wcl" in k.lower()}

    print(f"\n{'=' * 78}\n  {eticheta}\n{'=' * 78}")
    print(f"  lungime HTML                 : {len(html)} octeți")
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
    return {"eticheta": eticheta, "octeti": len(html),
            "selectori": gasite, "candidati": dict(candidati),
            "total_testid": sum(inventar.values())}


def main() -> int:
    from playwright.sync_api import sync_playwright

    rezultate = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            for eticheta, base in MECIURI:
                url = f"{base}#/match-summary/match-statistics/0"
                page = browser.new_page()
                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    page.wait_for_timeout(6000)  # randarea e pe JS
                    rezultate.append(_raport(eticheta, page.content()))
                except Exception as exc:
                    print(f"\n[{eticheta}] EȘUAT: {exc}")
                    rezultate.append({"eticheta": eticheta, "eroare": str(exc)})
                finally:
                    page.close()
        finally:
            browser.close()

    print(f"\n{'=' * 78}\n  VERDICT\n{'=' * 78}")
    ok = [r for r in rezultate if "selectori" in r]
    if len(ok) == 2:
        vechi, nou = ok[0]["selectori"], ok[1]["selectori"]
        principal = SELECTORI_ASTEPTATI[0]
        if vechi[principal] > 0 and nou[principal] == 0:
            print("  CONFIRMAT: selectorul merge pe pagina veche și NU pe cea nouă")
            print("  -> Flashscore a schimbat structura. Numele nou e în lista de")
            print("     candidați de mai sus; reparația e un selector, nu un proiect.")
        elif vechi[principal] == 0 and nou[principal] == 0:
            print("  NECONFIRMAT: selectorul nu merge pe NICIUNA dintre pagini.")
            print("  -> Cauza NU e o schimbare recentă de DOM. Posibil randare")
            print("     incompletă în acest POC (timp de așteptare, consimțământ")
            print("     cookies, geo). De investigat ALTFEL, nu de reparat orbește.")
        else:
            print("  NEAȘTEPTAT: selectorul merge pe pagina nouă.")
            print("  -> Atunci ruptura e în AVAL de extragere (fetch, persistare).")
    else:
        print("  INCONCLUZIV — o pagină n-a putut fi încărcată. Vezi erorile.")

    print("\nJSON:", json.dumps(rezultate, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
