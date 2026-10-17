"""POC izolat, TEMPORAR — de ce s-a oprit extragerea statisticilor pe 8 sep.

NU importă NIMIC din codul de producție. Playwright direct, zero scriere,
zero credențiale de bază de date. Se șterge după închiderea investigației;
dovada rămâne în istoricul rulărilor GitHub Actions (tiparul deja aplicat de
5 ori în proiect).

### Ce s-a stabilit deja (rulările 1-5, toate în istoricul Actions)

`match_statistics_extended`, `player_match_stats` și
`player_match_stats_extended` au ZERO rânduri scrise după **2026-09-08**. În
aceeași perioadă `flashscore_match_context` (H2H) și `match_events` scriu
normal, deci NU e rețea, NU e autentificare, NU e scriere în bază.

Ultima rulare (job 117432697950), prima cu BAZA REALĂ a producției (sloguri
de echipă citite din dovada salvată în repo, nu construite de mine), a
răspuns la întrebarea de structură: **toate cele 7 taburi răspund cu sufixele
actuale ale producției**, iar `summary/stats/` întoarce 45 de rânduri
`wcl-statistics`. Deci URL-ul NU e defect — ruptura e strict în selectorii
COPII.

### Ce măsoară rularea ASTA, și de ce e ultima necesară

Două lucruri pe care încă NU le am măsurate, și fără care reparația ar fi
ghicită:

**(1) Un recensământ complet al selectorilor de producție**, pe tabul unde
fiecare e folosit efectiv. Până acum am verificat trei (`wcl-statistics*`).
Dar `normalizer.py` se sprijină pe treisprezece. Dacă Flashscore a făcut o
redenumire de familie (ipoteza mea: a căzut segmentul `scores` din
`wcl-scores-simple-text-01` -> `wcl-simple-text-01`), atunci aliniamentele
s-au rupt din ACEEAȘI cauză, iar scorul la pauză (`wcl-scores-overline-02`)
e rupt și el, tăcut, fără ca nimeni să fi observat. Recensământul spune care
dintre cei treisprezece trăiesc și care nu — nu deduc, număr.

**(2) Validarea algoritmului de reparație, ÎNAINTE de a-l scrie în
producție.** POC-ul implementează candidatul exact cum intenționez să-l scriu
în `normalizer.py` și tipărește ce extrage. Dacă tipărește 45 de etichete cu
valori corecte pentru Everton-Chelsea (meciul din captura proprietarului
produsului), reparația e dovedită pe date reale înainte de prima linie de
cod de producție. Dacă nu, aflu aici, nu după un merge.

Capcana de evitat, consemnată explicit: numele de clase CSS conțin hash-uri
de build (`wcl-value_Ywp3J`). A lega selectorul de hash ar reproduce exact
același defect la următorul deploy Flashscore. Candidatul se sprijină pe
`data-testid` unde există, și pe **prefix** de clasă unde nu — niciodată pe
hash-ul întreg.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter

# Reproduse din adapter.py ca VALORI, nu prin import (garda de izolare a
# POC-urilor interzice importul modulelor de producție).
SELECTOARE_GDPR = (
    "#onetrust-accept-btn-handler",
    "button:has-text('Accept & continue')",
    "button:has-text('Accept all')",
    "button:has-text('I Accept')",
)
NAV_TIMEOUT_MS = 30000
POST_LOAD_WAIT_MS = 3500

MID = "2wo3m634"
# Baza REALA, citita din href-ul descoperit pe hub (nu construita de mine):
# docs/06_UDAL/poc_evidence/flashscore_10matches/superliga_results_hub_raw.html
BAZA = "https://www.flashscore.com/match/football/chelsea-4fGZN2oK/everton-KluSTr9s"

# ---------------------------------------------------------------------------
# (1) RECENSAMANT — toti selectorii pe care `normalizer.py` se sprijina azi,
#     grupati dupa tabul pe care sunt folositi efectiv. Citite din cod, nu
#     din memorie (grep pe `data-testid` + clasele din docstring-uri).
# ---------------------------------------------------------------------------
SELECTORI_PRODUCTIE: dict[str, tuple[tuple[str, str], ...]] = {
    "summary": (
        ("[data-testid='wcl-summaryMatchInformation']", "arbitru/stadion — SCRIE normal azi"),
        ("[data-testid='wcl-scores-overline-02']", "scor la pauza — NEVERIFICAT"),
        (".wclHeaderSection--summary", "container scor la pauza"),
        (".detailScore__wrapper", "scor final — SCRIE normal azi"),
        (".duelParticipant__home", "orientare gazda (identitate)"),
        (".duelParticipant__away", "orientare oaspete"),
        (".smv__participantRow", "timeline evenimente — SCRIE normal azi"),
        ("[data-testid='wcl-icon-incidents-goal-soccer']", "incident gol"),
        ("[data-testid='wcl-statistics']", "widget restrans (5 categorii, fallback)"),
    ),
    "stats": (
        ("[data-testid='wcl-statistics']", "rand de statistica — VIU (45)"),
        ("[data-testid='wcl-statistics-category']", "eticheta — SUSPECT PRINCIPAL"),
        ("[data-testid='wcl-statistics-value']", "valoare — SUSPECT PRINCIPAL"),
    ),
    "lineups": (
        ("[data-testid='wcl-lineupsParticipantGeneral-left']", "rand jucator gazda"),
        ("[data-testid='wcl-lineupsParticipantGeneral-right']", "rand jucator oaspete"),
        ("[data-testid='wcl-scores-simple-text-01']", "numar+nume jucator — SUSPECT"),
        ("[data-testid='wcl-simple-text-01']", "ipoteza: acelasi, fara 'scores'"),
    ),
    "h2h": (
        ("[data-testid='wcl-headerSection-text']", "categorie H2H — SCRIE normal azi"),
        ("[data-testid='wcl-stageTime']", "data meciului H2H"),
        ("[data-testid='wcl-matchRow-participant']", "echipele din randul H2H"),
        ("[data-testid='wcl-tableScore']", "scorul din randul H2H"),
    ),
    "standings": (
        ("[data-testid='wcl-tableBodyRow']", "rand clasament"),
        ("[data-testid='wcl-tableBodyCell']", "celula clasament"),
        ("[data-testid^='wcl-badgeForm-']", "forma (W/D/L)"),
        (".tableCellParticipant__name", "nume echipa in clasament"),
    ),
    "player_stats": (
        ("[data-testid='wcl-tableBodyRow']", "rand jucator"),
        ("[data-testid='wcl-tableBodyCell']", "celula"),
    ),
    "odds": (),
}

TABURI: dict[str, tuple[str, str]] = {
    "summary":      ("",                      "Referee"),
    "stats":        ("summary/stats/",         "Expected goals"),
    "lineups":      ("summary/lineups/",       "Formation"),
    "player_stats": ("summary/player-stats/",  "Minutes played"),
    "odds":         ("odds/",                  "1X2"),
    "h2h":          ("h2h/",                   "Head-to-head"),
    "standings":    ("standings/",             "Rank"),
}


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


# ---------------------------------------------------------------------------
# (2) CANDIDATUL DE REPARATIE — scris aici exact cum intentionez sa-l scriu
#     in `normalizer.py`. Daca tipareste statistici corecte, reparatia e
#     dovedita pe date reale INAINTE de prima linie de cod de productie.
# ---------------------------------------------------------------------------
def _are_clasa_cu_prefix(tag, prefix: str) -> bool:
    return any(c.startswith(prefix) for c in (tag.get("class") or []))


def _descendenti_cu_prefix(nod, prefix: str) -> list:
    """Toti descendentii cu o clasa care INCEPE cu `prefix`, in ordinea DOM.

    Prefix, niciodata clasa intreaga: `wcl-value_Ywp3J` are hash de build,
    deci s-ar rupe la urmatorul deploy Flashscore — exact defectul de reparat,
    reintrodus intr-o forma noua."""
    return [t for t in nod.find_all(True) if _are_clasa_cu_prefix(t, prefix)]


def _are_stramos_cu_prefix(nod, prefix: str) -> bool:
    p = nod.parent
    while p is not None:
        if _are_clasa_cu_prefix(p, prefix):
            return True
        p = p.parent
    return False


def _candidat_statistici(soup) -> tuple[dict, list[str]]:
    """{eticheta: (home, away)} cu structura de AZI. Intoarce si o lista de
    observatii — lucruri pe care le-am presupus si care s-au verificat sau
    nu, ca sa nu ramana nescrise."""
    rezultat: dict[str, tuple[str | None, str | None]] = {}
    obs: list[str] = []
    randuri = soup.select("[data-testid='wcl-statistics']")
    for idx, row in enumerate(randuri):
        # Eticheta: `data-testid` vechi daca mai exista, altfel prefix de
        # clasa `wcl-label`.
        et_el = row.select_one("[data-testid='wcl-statistics-category']")
        sursa_et = "testid-vechi"
        if et_el is None:
            cand = _descendenti_cu_prefix(row, "wcl-label")
            et_el = cand[0] if cand else None
            sursa_et = "clasa wcl-label*"
        if et_el is None:
            if idx == 0:
                obs.append("NICIO eticheta: nici testid vechi, nici clasa wcl-label*")
            continue
        eticheta = et_el.get_text(strip=True)

        # Valori: `data-testid` vechi daca mai exista, altfel prefix de
        # clasa `wcl-value`.
        valori = row.select("[data-testid='wcl-statistics-value']")
        sursa_val = "testid-vechi"
        if not valori:
            valori = _descendenti_cu_prefix(row, "wcl-value")
            sursa_val = "clasa wcl-value*"

        home = valori[0].get_text(strip=True) if len(valori) > 0 else None
        away = valori[1].get_text(strip=True) if len(valori) > 1 else None

        # Contrapondere: ordinea DOM spune ca a doua valoare e a oaspetelui.
        # O verific independent, prin stramosul `wcl-awayValue*`, in loc s-o
        # presupun. Daca cele doua semnale se contrazic, vreau sa se vada.
        if idx == 0:
            obs.append(f"eticheta via {sursa_et}; valori via {sursa_val} "
                       f"({len(valori)} gasite in primul rand)")
            if len(valori) >= 2:
                a0 = _are_stramos_cu_prefix(valori[0], "wcl-awayValue")
                a1 = _are_stramos_cu_prefix(valori[1], "wcl-awayValue")
                verdict = "CONCORDANT cu ordinea DOM" if (not a0 and a1) else "DISCORDANT — de investigat"
                obs.append(f"stramos wcl-awayValue*: valoare[0]={a0}, valoare[1]={a1} -> {verdict}")
            if len(valori) > 2:
                obs.append(f"ATENTIE: {len(valori)} valori in primul rand, nu 2 — "
                           "selectorul prinde si ceva ce nu e valoare")
        rezultat[eticheta] = (home, away)
    obs.insert(0, f"{len(randuri)} randuri wcl-statistics -> {len(rezultat)} etichete extrase")
    return rezultat, obs


def _candidat_aliniamente(soup) -> tuple[dict[str, list], list[str]]:
    """Jucatori per parte. Aceeasi logica de productie (numar = primul span,
    nume = primul span ulterior care nu incepe cu paranteza), dar cu lista de
    testid-uri de text incercate in cascada."""
    obs: list[str] = []
    out: dict[str, list] = {"home": [], "away": []}
    TESTIDE_TEXT = (
        "[data-testid='wcl-scores-simple-text-01']",   # productia de azi
        "[data-testid='wcl-simple-text-01']",           # ipoteza de redenumire
    )
    for side, team in (("left", "home"), ("right", "away")):
        randuri = soup.select(f"[data-testid='wcl-lineupsParticipantGeneral-{side}']")
        if side == "left":
            obs.append(f"randuri wcl-lineupsParticipantGeneral-left: {len(randuri)}")
        for row in randuri:
            spans, sursa = [], None
            for sel in TESTIDE_TEXT:
                spans = row.select(sel)
                if spans:
                    sursa = sel
                    break
            if not spans:
                continue
            if side == "left" and not out["home"]:
                obs.append(f"text de jucator via {sursa} ({len(spans)} span-uri in primul rand)")
            numar = spans[0].get_text(strip=True)
            nume = next((s.get_text(strip=True) for s in spans[1:]
                         if s.get_text(strip=True) and not s.get_text(strip=True).startswith("(")), None)
            if not nume:
                continue
            out[team].append({"nume": nume, "numar": int(numar) if numar.isdigit() else None})
    return out, obs


def _inventar_wcl(html: str) -> Counter:
    return Counter(t for t in re.findall(r'data-testid="([^"]+)"', html))


def _inventar_clase_wcl(html: str) -> Counter:
    """Prefixele de clasa `wcl-xxx_HASH` -> numara `wcl-xxx`. Asta arata
    familia de clase pe care se poate sprijini reparatia, fara hash."""
    prefixe = []
    for bloc in re.findall(r'class="([^"]+)"', html):
        for c in bloc.split():
            m = re.match(r"^(wcl-[A-Za-z0-9]+)_", c)
            if m:
                prefixe.append(m.group(1))
    return Counter(prefixe)


def _fragment(html: str, marcaj: str, context: int = 900) -> None:
    poz = html.find(marcaj)
    if poz < 0:
        print(f"    (marcajul {marcaj!r} nu e in HTML)")
        return
    start = max(0, poz - context)
    print(f"    --- HTML in jurul {marcaj!r} (poz {poz}) ---")
    print("    " + html[start:poz + context].replace("\n", " ")[:1800])
    print("    --- sfarsit fragment ---")


def main() -> int:
    from bs4 import BeautifulSoup
    from playwright.sync_api import sync_playwright

    pagini: dict[str, str] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(f"{BAZA}/?mid={MID}", timeout=NAV_TIMEOUT_MS,
                      wait_until="domcontentloaded")
            if _respinge_gdpr(page):
                print("banner GDPR respins")
            page.wait_for_timeout(POST_LOAD_WAIT_MS)
            for nume, (sufix, _marcaj) in TABURI.items():
                page.goto(f"{BAZA}/{sufix}?mid={MID}", timeout=NAV_TIMEOUT_MS,
                          wait_until="domcontentloaded")
                page.wait_for_timeout(POST_LOAD_WAIT_MS)
                pagini[nume] = page.content()
        finally:
            page.close()
            browser.close()

    # --- (1) RECENSAMANT ---------------------------------------------------
    print(f"\n{'#' * 78}")
    print("  (1) RECENSAMANT: fiecare selector de productie, pe tabul lui")
    print(f"{'#' * 78}")
    morti: list[tuple[str, str, str]] = []
    for tab, selectori in SELECTORI_PRODUCTIE.items():
        html = pagini.get(tab, "")
        marcaj = TABURI[tab][1]
        randat = marcaj.lower() in html.lower()
        print(f"\n  [{tab}]  {len(html)} octeti, marcaj {marcaj!r}: "
              f"{'DA' if randat else 'NU  <-- cifrele de mai jos nu spun nimic'}")
        if not selectori:
            print("     (niciun selector de productie pe acest tab)")
            continue
        soup = BeautifulSoup(html, "html.parser")
        for sel, rol in selectori:
            n = len(soup.select(sel))
            print(f"     {'OK ' if n else 'MORT'}  {n:5}x  {sel:58} {rol}")
            if n == 0 and randat:
                morti.append((tab, sel, rol))

    print(f"\n{'=' * 78}")
    print(f"  SELECTORI MORTI: {len(morti)}")
    for tab, sel, rol in morti:
        print(f"     [{tab}] {sel}  ({rol})")

    # --- inventar, ca redenumirea sa apara prin nume, nu prin ghicit -------
    for tab in ("stats", "lineups"):
        html = pagini.get(tab, "")
        print(f"\n  --- [{tab}] top 20 data-testid care contin 'wcl' ---")
        for k, v in sorted(((k, v) for k, v in _inventar_wcl(html).items()
                            if "wcl" in k.lower()), key=lambda x: -x[1])[:20]:
            print(f"     {v:5}x  {k}")
        print(f"  --- [{tab}] top 20 prefixe de clasa wcl-*_HASH ---")
        for k, v in _inventar_clase_wcl(html).most_common(20):
            print(f"     {v:5}x  {k}_*")

    # --- (2) CANDIDATUL DE REPARATIE --------------------------------------
    print(f"\n{'#' * 78}")
    print("  (2) CANDIDATUL DE REPARATIE, rulat pe pagina reala de azi")
    print(f"{'#' * 78}")

    stats_soup = BeautifulSoup(pagini.get("stats", ""), "html.parser")
    stats, obs = _candidat_statistici(stats_soup)
    print("\n  [statistici] observatii:")
    for o in obs:
        print(f"     - {o}")
    print(f"  [statistici] {len(stats)} etichete extrase. Primele 20:")
    for k, (h, a) in list(stats.items())[:20]:
        print(f"     {k:38} home={h!r:>12}  away={a!r:>12}")
    # Cele care conteaza pentru schema noastra, numite explicit:
    for cheie in ("Expected goals (xG)", "Ball possession", "Goal attempts",
                  "Shots on goal", "Corner kicks", "Fouls"):
        if cheie in stats:
            print(f"     >>> {cheie:28} -> {stats[cheie]}")
        else:
            print(f"     >>> {cheie:28} -> ABSENT din extragere")

    lin_soup = BeautifulSoup(pagini.get("lineups", ""), "html.parser")
    aliniamente, obs_a = _candidat_aliniamente(lin_soup)
    print("\n  [aliniamente] observatii:")
    for o in obs_a:
        print(f"     - {o}")
    print(f"  [aliniamente] home={len(aliniamente['home'])} jucatori, "
          f"away={len(aliniamente['away'])} jucatori")
    for j in aliniamente["home"][:5]:
        print(f"     home {j['numar']!r:>5}  {j['nume']}")
    for j in aliniamente["away"][:5]:
        print(f"     away {j['numar']!r:>5}  {j['nume']}")

    # --- fragmente, pentru orice ramane de citit cu ochiul ----------------
    print(f"\n{'#' * 78}")
    print("  (3) FRAGMENTE DE HTML — structura reala, nu una ghicita")
    print(f"{'#' * 78}")
    _fragment(pagini.get("stats", ""), "Expected goals")
    _fragment(pagini.get("lineups", ""), "Formation")

    rezultate = {
        "morti": [{"tab": t, "selector": s} for t, s, _ in morti],
        "statistici_extrase": len(stats),
        "aliniamente": {k: len(v) for k, v in aliniamente.items()},
        "xg": stats.get("Expected goals (xG)"),
    }
    print("\nJSON:", json.dumps(rezultate, ensure_ascii=False)[:1200])

    print(f"\n{'=' * 78}\n  VERDICT\n{'=' * 78}")
    if len(stats) >= 20 and aliniamente["home"] and aliniamente["away"]:
        print("  Candidatul extrage statistici SI aliniamente pe pagina de azi.")
        print("  -> reparatia e dovedita pe date reale inainte de a fi scrisa.")
    elif len(stats) >= 20:
        print("  Statisticile se repara cu acest candidat; ALINIAMENTELE NU.")
        print("  -> ADR-ul le trateaza separat; aliniamentele cer alta masuratoare.")
    else:
        print("  Candidatul NU extrage statistici. Citeste fragmentele de mai sus;")
        print("  structura e alta decat cea presupusa. NU se scrie nimic in productie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
