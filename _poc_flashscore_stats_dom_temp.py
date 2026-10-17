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
    # Al treilea caz, cel mai tare: Everton-Chelsea, 17.10.2026, Premier
    # League. Proprietarul produsului a trimis captura paginii — terminat 0-2,
    # tab-ul STATS plin (xG 0.45/1.54, xGOT 0.70/1.79, posesie, șuturi).
    # La noi, ACELAȘI meci (`flashscore_2wo3m634`, id=126842) are
    # `actual_result` NULL și xG NULL. Deci nu e o reconstrucție istorică —
    # e defectul, viu, pe un meci de azi.
    # `mid`-ul e luat din `match_history`, NU ghicit: prima versiune a acestei
    # linii conținea un identificator inventat de mine.
    ("DEFECT    17 oct", "https://www.flashscore.com/match/football/2wo3m634/"),
]

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
        try:
            for eticheta, base in MECIURI:
                url = f"{base.rstrip('/')}/{SUFIX_TAB_STATS}"
                page = browser.new_page()
                try:
                    page.goto(url, timeout=60000, wait_until="domcontentloaded")
                    # Astept SEMNALUL, nu un numar fix de secunde: o pagina
                    # lenta ar fi masurata ca „ruptă" de un timeout orb.
                    try:
                        page.wait_for_function(
                            f"document.body.innerText.includes({MARCAJ_RANDARE!r})",
                            timeout=25000)
                    except Exception:
                        print(f"  [{eticheta}] marcajul de randare n-a apărut în 25 s")
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

    # 🔴 Prima versiune a verdictului se uita DOAR la containerul
    # `wcl-statistics` si a tras o concluzie falsa („ruptura e in aval")
    # cand acela era 5 pe ambele pagini — desi `-category`/`-value` erau 0
    # pe AMBELE, inclusiv pe una despre care stim ca a mers in productie.
    # Semnalul care conteaza e PERECHEA category+value, si numai pe pagini
    # care s-au randat efectiv.
    nerandate = [r["eticheta"] for r in ok if not r.get("randat")]
    if nerandate:
        print(f"  INCONCLUZIV — pagini nerandate: {', '.join(nerandate)}")
        print("  -> Orice numărătoare de selectori pe ele e lipsită de sens.")
        print("     Se repară POC-ul, NU codul de producție.")
        return 0

    cat, val = SELECTORI_ASTEPTATI[1], SELECTORI_ASTEPTATI[2]
    merge = [r for r in ok if r["selectori"][cat] > 0 and r["selectori"][val] > 0]
    nu_merge = [r for r in ok if r not in merge]

    if not merge and nu_merge:
        print("  CONFIRMAT: pe pagini RANDATE, perechea category+value nu mai")
        print("  găsește nimic — pe NICIUNA, inclusiv pe cea de referință.")
        print("  -> Flashscore a redenumit atributele. Numele nou e în lista de")
        print("     candidați de mai sus; reparația e un selector, nu un proiect.")
    elif merge and nu_merge:
        print(f"  PARȚIAL: merge pe {[r['eticheta'] for r in merge]}, nu pe")
        print(f"  {[r['eticheta'] for r in nu_merge]} -> schimbare progresivă.")
    elif merge and not nu_merge:
        print("  NEAȘTEPTAT: selectorii merg pe TOATE paginile randate.")
        print("  -> Ipoteza DOM e INFIRMATĂ. Ruptura e în aval (fetch care nu")
        print("     cere tab-ul, sau persistare). De investigat acolo.")

    print("\nJSON:", json.dumps(rezultate, ensure_ascii=False)[:1500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
