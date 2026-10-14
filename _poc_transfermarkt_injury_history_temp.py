"""
================================================================================
POC TEMPORAR — Transfermarkt publică ISTORIC de accidentări, parsabil?
================================================================================
Fișier: _poc_transfermarkt_injury_history_temp.py

ACESTA E UN POC. SE ȘTERGE DUPĂ ÎNCHIDEREA INVESTIGAȚIEI.
Dovada rămâne în istoricul rulărilor GitHub Actions + raportul din CHANGELOG,
nu ca infrastructură vie permanentă (regula din CLAUDE.md, §chei API, aplicată
deja de 4 ori: SofaScore, Transfermarkt ×2, API-Football).

STRICT READ-ONLY, ȘI NU PRIN PROMISIUNE — PRIN CONSTRUCȚIE
Nu importă `database/queries.py`, `supabase_client.py`,
`freelf_lineup_adapter.py` sau orice alt modul care știe să scrie. Deci NU are
nici măcar funcția prin care s-ar putea scrie. Workflow-ul nu îi dă niciun
secret de bază de date, deci o scriere ar eșua oricum.

(Numele secretelor NU sunt citate nici în acest docstring — deliberat, ca
verificarea „fișierul nu conține numele vreunui secret" să rămână un `in`
strict, fără excepții de interpretat. O gardă cu nuanțe e o gardă care, la a
doua citire, lasă să treacă exact ce trebuia să prindă.)

Verificat în cod înainte de a scrie POC-ul, ca să nu fie o afirmație de proces:
există EXACT o cale prin care date de accidentări ating o predicție —
`freelf_lineup_snapshot` -> `get_freelf_lineup_snapshot()` (`oracle_engine.py:1810`)
-> `apply_injury_penalty()` -> `home_xg`/`away_xg` -> Poisson. Singurii scriitori
ai tabelei sunt `freelf_lineup_adapter.py:93` și
`database/queries.py:1745`. `team_health_snapshot` NU atinge predicția —
comentariul din `oracle_engine.py:1852` o spune explicit, iar Poisson-ul de la
1869 primește xG neschimbat de acel bloc. Deci un POC care nu scrie în
`freelf_lineup_snapshot` nu poate schimba nicio predicție.

ÎNTREBAREA, UNA SINGURĂ
Pentru un backtest al penalizării de accidentări pe meciuri DEJA JUCATE e nevoie
de „cine lipsea la data D". Transfermarkt publică istoric de accidentări per
jucător, cu intervale de date? Și dacă da, e parsabil structurat?

CE S-A VERIFICAT DEJA (2026-08-31, rulările 33372482351 și 33372940106)
Pagina de accidentări CURENTE a unui club
(`/<club>/sperrenundverletzungen/verein/<id>`) e accesibilă cu Playwright
standard, status 200, cu coloana „Market value" prezentă — exact câmpul pe care
formula de penalizare îl cere și pe care Flashscore nu-l publică.
Cererile HTTP oneste (`requests`) primesc uniform `x-amzn-waf-action: challenge`.
Playwright trece prin randare normală, fără captcha interactiv.

CE NU S-A VERIFICAT NICIODATĂ, și e exact subiectul acestui POC
Istoricul. Pagina curentă spune cine lipsește AZI, nu cine lipsea pe 15 august.

CE SE TESTEAZĂ, în ordinea utilității pentru backtest
  A. `/<player>/verletzungen/spieler/<id>` — istoricul de accidentări al unui
     jucător. Căutăm tabel cu „from"/„to", zile absente, meciuri ratate.
  B. `/<club>/startseite/verein/<id>` — lotul clubului, ca să știm pe cine să
     interogăm. Fără el, A nu e utilizabil la scară.
  C. Dacă istoricul numește COMPETIȚIILE/meciurile ratate — atunci un meci
     anume se poate verifica direct, fără aritmetică pe intervale.

  [EXTINS 2026-10-14, runda 2 — cele două necunoscute care blochează ADR-ul]
  D. VALOAREA DE PIAȚĂ. Formula din producție
     (`injury_manager.build_injury_report_from_raw_lineup`) calculează impactul
     fiecărui absent din `market_value`, cu pragul
     `MARKET_VALUE_KEY_PLAYER = 20M€`. Pagina de istoric NU o conține. Se
     testează profilul (`/profil/spieler/<id>`, valoarea de AZI) și istoricul
     de valoare (`/marktwertverlauf/spieler/<id>`, valoarea de ATUNCI).
     Fără cea din urmă, backtestul folosește valoarea curentă ca aproximare —
     apărabilă pe o fereastră de 2-3 luni, fiindcă formula doar ÎNCADREAZĂ
     jucătorul (peste/sub 20M), iar traversarea pragului în acel interval e
     rară. Dar e aproximare, și se etichetează ca atare.
  E. O LIGĂ MICĂ, nu doar Arsenal și Real Madrid. Runda 1 a testat două
     cluburi uriașe — exact cele pentru care Transfermarkt are cea mai bogată
     acoperire. Dacă structura nu ține pe Romania SuperLiga, acoperirea reală
     a backtestului e mult mai mică decât sugerează runda 1. Se pornește de la
     pagina competiției (`/wettbewerb/RO1`), ca să se verifice și lanțul de
     descoperire, nu doar o pagină ghicită.

CAPCANA DE SCURGERE TEMPORALĂ, semnalată ÎNAINTE de a avea datele
Un istoric citit AZI despre un meci din august spune cine era accidentat atunci
— dar informația în forma asta completă NU era disponibilă înainte de meci, iar
Transfermarkt consemnează retrospectiv, uneori ajustând datele de început.
Asta e scurgere temporală (North Star #7) și invalidează backtestul dacă nu e
tratată. Tratamentul onest, de aplicat DACĂ POC-ul reușește: se folosesc doar
absențele al căror interval începuse STRICT înainte de data meciului, iar
rezultatul se marchează optimist, nu curat. POC-ul de aici raportează dacă
distincția e măcar POSIBILĂ din date.

NICIO OCOLIRE ANTI-BOT: Playwright headless standard, fără stealth, fără proxy,
fără fingerprint spoofing — identic tiparului deja folosit în producție pentru
Flashscore (`providers/flashscore/adapter.py:181`). Un browser real execută JS
ca parte din încărcarea normală a paginii; nu e „ocolirea" unui puzzle.
Dacă apare un captcha interactiv, POC-ul SE OPREȘTE și o raportează.

Rulare: doar `workflow_dispatch`.
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time

BAZA = "https://www.transfermarkt.com"
NAV_TIMEOUT_MS = 45_000
POST_LOAD_WAIT_MS = 2_500
CHROMIUM = os.environ.get("FLASHSCORE_CHROMIUM_EXECUTABLE") or None

# Ținte alese explicit: cluburi din ligi pe care proiectul le urmărește, cu
# jucători reali, verificabili extern. ID-urile Transfermarkt sunt stabile.
CLUBURI = [
    ("arsenal-fc", 11, "Arsenal"),
    ("real-madrid", 418, "Real Madrid"),
]

# Jucatori cu istoric de accidentari cunoscut public — alesi ca sa existe
# CEVA de parsat; daca tabelul e gol pentru toti, e semnal, nu lipsa de noroc.
JUCATORI = [
    ("jurrien-timber", 598252, "Jurrien Timber"),
    ("william-saliba", 495666, "William Saliba"),
    ("eder-militao", 401530, "Eder Militao"),
]

_SEMNE_CAPTCHA = (
    "captcha", "are you a human", "verify you are human",
    "px-captcha", "recaptcha", "hcaptcha",
)


def _delay() -> None:
    """Politete fata de provider — acelasi tipar ca `polite_delay()` din
    fluxul Flashscore. Un POC nu are voie sa fie mai agresiv decat producția."""
    time.sleep(random.uniform(2.0, 4.0))


def _captcha_prezent(html: str) -> bool:
    jos = html.lower()
    return any(s in jos for s in _SEMNE_CAPTCHA)


def _tabel_cu_antete(html: str, cuvinte: tuple[str, ...]) -> dict:
    """Caută un <table> care conține TOATE cuvintele-cheie in antete. Intoarce
    diagnostic structural, nu doar un boolean — ca sa se poata decide dacă
    datele sunt utilizabile, nu doar prezente."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"eroare": "bs4 indisponibil"}

    sup = BeautifulSoup(html, "html.parser")
    for tabel in sup.find_all("table"):
        antete = [th.get_text(" ", strip=True).lower() for th in tabel.find_all("th")]
        text_antete = " | ".join(antete)
        if all(c.lower() in text_antete for c in cuvinte):
            randuri = tabel.find_all("tr")
            exemple = []
            for r in randuri[1:4]:
                celule = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
                if any(celule):
                    exemple.append(celule)
            return {
                "gasit": True,
                "antete": antete,
                "randuri_total": max(len(randuri) - 1, 0),
                "exemple": exemple,
            }
    return {"gasit": False, "antete_vazute": [
        " | ".join(th.get_text(" ", strip=True) for th in t.find_all("th"))
        for t in sup.find_all("table")[:6]
    ]}


def _date_din(exemple: list[list[str]]) -> dict:
    """Cate celule arata ca o DATA? Fara date, reconstructia „cine lipsea la
    data D" e imposibila, oricat de bogat ar fi restul tabelului."""
    tipar = re.compile(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b[A-Z][a-z]{2} \d{1,2}, \d{4}\b")
    gasite = []
    for rand in exemple:
        for celula in rand:
            if tipar.search(celula or ""):
                gasite.append(celula)
    return {"celule_cu_data": gasite[:8], "numar": len(gasite)}


def main() -> int:
    from playwright.sync_api import sync_playwright

    raport: dict = {
        "intrebare": "Transfermarkt publica istoric de accidentari parsabil?",
        "scurgere_temporala_semnalata": True,
        "oprit_de_captcha_interactiv": None,
        "A_istoric_jucatori": [],
        "B_loturi_cluburi": [],
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        page = browser.new_page()
        page.set_default_timeout(NAV_TIMEOUT_MS)
        try:
            # ── A. ISTORICUL DE ACCIDENTARI PER JUCATOR ──────────────────
            for slug, pid, nume in JUCATORI:
                url = f"{BAZA}/{slug}/verletzungen/spieler/{pid}"
                intrare: dict = {"jucator": nume, "url": url}
                try:
                    resp = page.goto(url, wait_until="domcontentloaded",
                                     timeout=NAV_TIMEOUT_MS)
                    intrare["status"] = resp.status if resp else None
                    page.wait_for_timeout(POST_LOAD_WAIT_MS)
                    html = page.content()
                    intrare["titlu"] = (page.title() or "")[:120]

                    if _captcha_prezent(html):
                        intrare["captcha"] = True
                        raport["oprit_de_captcha_interactiv"] = True
                        raport["A_istoric_jucatori"].append(intrare)
                        break

                    # Antetele reale pe pagina EN: Season | Injury | from | until
                    # | Days | Games missed. Caut un subset robust.
                    t = _tabel_cu_antete(html, ("injury", "from", "until"))
                    intrare["tabel"] = t
                    if t.get("gasit"):
                        intrare["date_detectate"] = _date_din(t.get("exemple", []))
                        antete = " | ".join(t.get("antete", []))
                        intrare["are_coloana_zile"] = "days" in antete
                        intrare["are_meciuri_ratate"] = "games missed" in antete
                except Exception as exc:
                    intrare["eroare"] = f"{type(exc).__name__}: {exc}"
                raport["A_istoric_jucatori"].append(intrare)
                _delay()

            # ── D. VALOAREA DE PIATA: profil + istoric de valoare ────────
            raport["D_valoare_piata"] = []
            if not raport["oprit_de_captcha_interactiv"]:
                for slug, pid, nume in JUCATORI[:2]:
                    intrare = {"jucator": nume}
                    for eticheta, cale in (("profil", "profil"),
                                           ("istoric_valoare", "marktwertverlauf")):
                        url = f"{BAZA}/{slug}/{cale}/spieler/{pid}"
                        sub: dict = {"url": url}
                        try:
                            resp = page.goto(url, wait_until="domcontentloaded",
                                             timeout=NAV_TIMEOUT_MS)
                            sub["status"] = resp.status if resp else None
                            page.wait_for_timeout(POST_LOAD_WAIT_MS)
                            html = page.content()
                            if _captcha_prezent(html):
                                sub["captcha"] = True
                                raport["oprit_de_captcha_interactiv"] = True
                            else:
                                # Sume in euro: "€80.00m", "20,00 mil. €", "€500k"
                                sume = re.findall(
                                    r"€\s?\d[\d.,]*\s?(?:m|k|bn)?|\d[\d.,]*\s?(?:mil|Mio)\.?\s?€",
                                    html)
                                sub["sume_euro_gasite"] = len(sume)
                                sub["exemple_sume"] = sume[:6]
                                if eticheta == "istoric_valoare":
                                    # Graficul Highcharts tine punctele datate
                                    # intr-un bloc JS; daca exista, valoarea
                                    # DE ATUNCI e recuperabila.
                                    puncte = re.findall(r"'y':\s*(\d+)", html)
                                    datate = re.findall(r"'datum_mw':\s*'([^']+)'", html)
                                    sub["puncte_grafic"] = len(puncte)
                                    sub["etichete_datate"] = len(datate)
                                    sub["exemple_datate"] = datate[:5]
                        except Exception as exc:
                            sub["eroare"] = f"{type(exc).__name__}: {exc}"
                        intrare[eticheta] = sub
                        _delay()
                    raport["D_valoare_piata"].append(intrare)

            # ── E. O LIGA MICA: Romania SuperLiga, de la competitie la lot ─
            raport["E_liga_mica"] = {}
            if not raport["oprit_de_captcha_interactiv"]:
                url = f"{BAZA}/superliga/startseite/wettbewerb/RO1"
                e: dict = {"url": url}
                try:
                    resp = page.goto(url, wait_until="domcontentloaded",
                                     timeout=NAV_TIMEOUT_MS)
                    e["status"] = resp.status if resp else None
                    page.wait_for_timeout(POST_LOAD_WAIT_MS)
                    html = page.content()
                    e["titlu"] = (page.title() or "")[:120]
                    if _captcha_prezent(html):
                        e["captcha"] = True
                        raport["oprit_de_captcha_interactiv"] = True
                    else:
                        cluburi = re.findall(r"/([a-z0-9-]+)/startseite/verein/(\d+)", html)
                        unice = sorted(set(cluburi))
                        e["cluburi_descoperite"] = len(unice)
                        e["exemple_cluburi"] = unice[:5]
                        # Un club real din liga -> lotul lui -> un jucator.
                        if unice:
                            cslug, cid = unice[0]
                            _delay()
                            u2 = f"{BAZA}/{cslug}/startseite/verein/{cid}"
                            r2 = page.goto(u2, wait_until="domcontentloaded",
                                           timeout=NAV_TIMEOUT_MS)
                            page.wait_for_timeout(POST_LOAD_WAIT_MS)
                            h2 = page.content()
                            ids = sorted(set(re.findall(r"/profil/spieler/(\d+)", h2)))
                            e["club_testat"] = {"slug": cslug, "id": cid,
                                                "status": r2.status if r2 else None,
                                                "jucatori_cu_id": len(ids)}
                            # Si istoricul unui jucator din liga mica.
                            if ids:
                                _delay()
                                u3 = f"{BAZA}/x/verletzungen/spieler/{ids[0]}"
                                r3 = page.goto(u3, wait_until="domcontentloaded",
                                               timeout=NAV_TIMEOUT_MS)
                                page.wait_for_timeout(POST_LOAD_WAIT_MS)
                                h3 = page.content()
                                t3 = _tabel_cu_antete(h3, ("injury", "from", "until"))
                                e["istoric_jucator_liga_mica"] = {
                                    "url": u3,
                                    "status": r3.status if r3 else None,
                                    "titlu": (page.title() or "")[:100],
                                    "tabel_gasit": bool(t3.get("gasit")),
                                    "randuri": t3.get("randuri_total"),
                                    "exemple": t3.get("exemple", [])[:2],
                                }
                except Exception as exc:
                    e["eroare"] = f"{type(exc).__name__}: {exc}"
                raport["E_liga_mica"] = e
                _delay()

            # ── B. LOTUL CLUBULUI ───────────────────────────────────────
            if not raport["oprit_de_captcha_interactiv"]:
                for slug, cid, nume in CLUBURI:
                    url = f"{BAZA}/{slug}/startseite/verein/{cid}"
                    intrare = {"club": nume, "url": url}
                    try:
                        resp = page.goto(url, wait_until="domcontentloaded",
                                         timeout=NAV_TIMEOUT_MS)
                        intrare["status"] = resp.status if resp else None
                        page.wait_for_timeout(POST_LOAD_WAIT_MS)
                        html = page.content()
                        intrare["titlu"] = (page.title() or "")[:120]
                        if _captcha_prezent(html):
                            intrare["captcha"] = True
                            raport["oprit_de_captcha_interactiv"] = True
                            raport["B_loturi_cluburi"].append(intrare)
                            break
                        # Link-urile /profil/spieler/<id> dau direct id-urile
                        # necesare pentru pasul A la scara.
                        ids = set(re.findall(r"/profil/spieler/(\d+)", html))
                        intrare["jucatori_cu_id_gasiti"] = len(ids)
                        intrare["exemple_id"] = sorted(ids)[:5]
                    except Exception as exc:
                        intrare["eroare"] = f"{type(exc).__name__}: {exc}"
                    raport["B_loturi_cluburi"].append(intrare)
                    _delay()
        finally:
            browser.close()

    print("=" * 78)
    print("  POC — istoric accidentari Transfermarkt (READ-ONLY, temporar)")
    print("=" * 78)
    print(json.dumps(raport, indent=2, ensure_ascii=False))

    # ── CONCLUZIE OPERATIONALA ──────────────────────────────────────────
    cu_tabel = [j for j in raport["A_istoric_jucatori"]
                if isinstance(j.get("tabel"), dict) and j["tabel"].get("gasit")]
    cu_date = [j for j in cu_tabel if (j.get("date_detectate") or {}).get("numar", 0) > 0]
    loturi_ok = [c for c in raport["B_loturi_cluburi"]
                 if c.get("jucatori_cu_id_gasiti", 0) >= 15]

    print("\n" + "-" * 78)
    print("  VERDICT")
    print("-" * 78)
    print(f"  Istoric cu tabel parsabil: {len(cu_tabel)}/{len(JUCATORI)} jucatori")
    print(f"  Din care CU date detectate: {len(cu_date)}")
    print(f"  Loturi cu >=15 id-uri de jucator: {len(loturi_ok)}/{len(CLUBURI)}")
    if raport["oprit_de_captcha_interactiv"]:
        print("\n  ⛔ Oprit de captcha interactiv — Calea 2 e INCHISA, nu se forteaza.")
        return 1
    # D + E — cele doua necunoscute care blocau ADR-ul
    d = raport.get("D_valoare_piata") or []
    cu_valoare = [x for x in d
                  if (x.get("profil") or {}).get("sume_euro_gasite", 0) > 0]
    cu_istoric_valoare = [x for x in d
                          if (x.get("istoric_valoare") or {}).get("etichete_datate", 0) > 0]
    e = raport.get("E_liga_mica") or {}
    liga_mica_ok = (e.get("cluburi_descoperite", 0) >= 8
                    and (e.get("club_testat") or {}).get("jucatori_cu_id", 0) >= 10)
    istoric_mic = (e.get("istoric_jucator_liga_mica") or {}).get("tabel_gasit")

    print(f"  Valoare de piata (profil): {len(cu_valoare)}/{len(d)} jucatori")
    print(f"  ISTORIC de valoare, datat: {len(cu_istoric_valoare)}/{len(d)} jucatori")
    print(f"  Liga mica (Romania SuperLiga) — lant complet: "
          f"{'DA' if liga_mica_ok else 'NU'} "
          f"({e.get('cluburi_descoperite', 0)} cluburi, "
          f"{(e.get('club_testat') or {}).get('jucatori_cu_id', 0)} jucatori la clubul testat)")
    print(f"  Istoric accidentari pe liga mica: {'DA' if istoric_mic else 'NU'}")

    if raport["oprit_de_captcha_interactiv"]:
        print("\n  ⛔ Oprit de captcha interactiv — Calea 2 e INCHISA, nu se forteaza.")
        return 1
    if cu_date and loturi_ok:
        print("\n  ✅ Calea 2 e POSIBILA tehnic. NU inseamna ca e valida:")
        print("     scurgerea temporala rămâne de tratat (doar absente al caror")
        print("     interval incepuse STRICT inainte de meci), iar rezultatul")
        print("     oricarui backtest se marcheaza OPTIMIST, nu curat.")
        if cu_istoric_valoare:
            print("     + Valoarea DE ATUNCI e recuperabila -> fara aproximare pe")
            print("       market_value. Un obstacol mai putin in ADR.")
        elif cu_valoare:
            print("     + Doar valoarea de AZI e recuperabila -> backtestul o")
            print("       foloseste ca APROXIMARE, etichetata ca atare. Apararea:")
            print("       formula doar incadreaza (prag 20M€), iar traversarea")
            print("       pragului in 2-3 luni e rara. NU se ascunde.")
        else:
            print("     ⚠ Valoarea de piata NU e recuperabila din paginile testate.")
            print("       Formula de penalizare o CERE — fara ea, Calea 2 nu poate")
            print("       reproduce productia, doar un surogat. Decizie separata.")
        if not liga_mica_ok:
            print("     ⚠ Lantul NU tine pe o liga mica. Acoperirea reala a")
            print("       backtestului e mult sub ce sugereaza Arsenal/Real Madrid.")
    else:
        print("\n  ⛔ Datele nu sunt in forma necesara. Calea 2 pica; rămâne Calea 1")
        print("     (shadow, ~6-8 saptamani), si o stim azi, nu peste o luna.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
