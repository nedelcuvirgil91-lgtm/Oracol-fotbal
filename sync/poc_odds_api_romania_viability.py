"""
================================================================================
FOOTBALL ORACLE — Viabilitate Odds API ca sursa PRIMARA pentru Romania SuperLiga
================================================================================
Module: sync/poc_odds_api_romania_viability.py

Discovery, NU o schimbare de productie. Raspunde exact la intrebarea ceruta
inainte de orice decizie de arhitectura: poate Odds API (deja integrat, deja
folosit pentru cote) sa devina sursa principala pentru SuperLiga - atat lista
de meciuri cat si cotele - fara reconciliere TSDB?

Verifica, cu apeluri reale, LIVE, fara sa presupuna nimic din codul existent:
  1. Raspunsul BRUT /sports?all=true - campurile reale (active, has_outrights)
     pentru orice sport_key care contine "romania", comparat cu logica de
     validare din oracle_api.py (_validate_api_keys, linia 270-280).
  2. Daca /sports?all=true nu lista niciun sport romanesc: cauta orice sport
     key posibil (variante de denumire) - nu presupune ca singura varianta
     testata pana acum (soccer_romania_1_liga) e singura posibila.
  3. Apel DIRECT /sports/soccer_romania_1_liga/events (fixtures, fara cote) -
     bypass complet al gate-ului _dead_keys din productie - raspunde REAL,
     nu din perspectiva codului care il marcheaza mort.
  4. Apel DIRECT /sports/soccer_romania_1_liga/odds (cote reale) - acelasi
     bypass, aceeasi intrebare: are Odds API cote pentru Etapa 1, indiferent
     de ce zice validarea din productie?
  5. Comparatie cu cele 8 meciuri oficiale LPF Etapa 1 (deja confirmate in
     investigatia anterioara) - completitudine exacta, nu presupusa.
  6. Verificare quota ramasa (headere x-requests-remaining/used din raspunsul
     Odds API) - relevanta pentru orice decizie de crestere a apelurilor.

Rulare:
    python sync/poc_odds_api_romania_viability.py
================================================================================
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

ODDS_API_URL = "https://api.the-odds-api.com/v4"
ODDS_API_KEY = "b0e2ab9bcda1d9f4c5ddfe1063c81cd7"

OFFICIAL_ETAPA_1 = [
    ("FC Voluntari", "FC Botoșani"),
    ("FCSB", "FC Argeș"),
    ("Oțelul Galați", "CFR 1907 Cluj"),
    ("Universitatea Craiova", "UTA Arad"),
    ("Universitatea Cluj", "Farul Constanța"),
    ("Petrolul Ploiești", "Dinamo"),
    ("Corvinul Hunedoara", "FK Csíkszereda Miercurea Ciuc"),
    ("FC Rapid", "Sepsi OSK Sf. Gheorghe"),
]


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def report_quota(headers: dict) -> None:
    remaining = headers.get("x-requests-remaining")
    used = headers.get("x-requests-used")
    if remaining is not None or used is not None:
        print(f"  Quota Odds API: used={used}  remaining={remaining}")


def main() -> None:
    section("1. /sports?all=true — raspuns BRUT, campuri reale, orice cheie 'romania'")
    r = requests.get(f"{ODDS_API_URL}/sports", params={"apiKey": ODDS_API_KEY, "all": "true"}, timeout=20)
    print(f"  HTTP {r.status_code}")
    report_quota(r.headers)
    all_sports = r.json() if r.status_code == 200 else []
    print(f"  Total sporturi/ligi returnate (all=true): {len(all_sports)}")
    romania_related = [s for s in all_sports if "romania" in (s.get("key") or "").lower()
                        or "romania" in (s.get("title") or "").lower()
                        or "romania" in (s.get("group") or "").lower()]
    if not romania_related:
        print("  NICIUN sport/liga cu 'romania' in key/title/group, in TOT raspunsul all=true.")
    for s in romania_related:
        print(f"  key={s.get('key')!r}  title={s.get('title')!r}  group={s.get('group')!r}  "
              f"active={s.get('active')}  has_outrights={s.get('has_outrights')}")

    section("2. Validare logica din productie (_validate_api_keys) vs. campul real 'active'")
    active_per_prod_logic = {s["key"] for s in all_sports if not s.get("has_outrights", False)}
    for s in romania_related:
        key = s.get("key")
        in_prod_active_set = key in active_per_prod_logic
        real_active_field = s.get("active")
        print(f"  {key!r}: marcat 'activ' de logica productiei (has_outrights=False)? {in_prod_active_set}  "
              f"| campul real 'active' din API: {real_active_field}")
        if in_prod_active_set != bool(real_active_field):
            print(f"    >>> DISCREPANTA: logica din oracle_api.py NU foloseste campul 'active' real, "
                  f"doar 'has_outrights' — pot diverge.")

    section("2b. /sports (fara all=true) — doar ce Odds API considera activ implicit")
    r2 = requests.get(f"{ODDS_API_URL}/sports", params={"apiKey": ODDS_API_KEY}, timeout=20)
    print(f"  HTTP {r2.status_code}")
    default_sports = r2.json() if r2.status_code == 200 else []
    print(f"  Total sporturi in raspunsul IMPLICIT (fara all=true): {len(default_sports)}")
    default_romania = [s for s in default_sports if "romania" in (s.get("key") or "").lower()]
    print(f"  Chei 'romania' in raspunsul implicit: {[s.get('key') for s in default_romania] or '(niciuna)'}")

    section("3. Apel DIRECT /sports/soccer_romania_1_liga/events — bypass total al _dead_keys")
    now = datetime.now(timezone.utc)
    r3 = requests.get(
        f"{ODDS_API_URL}/sports/soccer_romania_1_liga/events",
        params={"apiKey": ODDS_API_KEY,
                "commenceTimeFrom": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "commenceTimeTo": (now + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")},
        timeout=20,
    )
    print(f"  HTTP {r3.status_code}  {r3.url}")
    report_quota(r3.headers)
    events = r3.json() if r3.status_code == 200 and isinstance(r3.json(), list) else []
    print(f"  Total evenimente brute: {len(events)}")
    for ev in events:
        print(f"    {ev.get('home_team')} vs {ev.get('away_team')}  commence_time={ev.get('commence_time')}  id={ev.get('id')}")
    if r3.status_code != 200:
        print(f"  Body raspuns (primele 500 caractere): {r3.text[:500]}")

    section("4. Apel DIRECT /sports/soccer_romania_1_liga/odds — cote reale, bypass total")
    r4 = requests.get(
        f"{ODDS_API_URL}/sports/soccer_romania_1_liga/odds",
        params={"apiKey": ODDS_API_KEY, "regions": "eu", "markets": "h2h", "oddsFormat": "decimal"},
        timeout=20,
    )
    print(f"  HTTP {r4.status_code}  {r4.url}")
    report_quota(r4.headers)
    odds_events = r4.json() if r4.status_code == 200 and isinstance(r4.json(), list) else []
    print(f"  Total evenimente cu cote: {len(odds_events)}")
    for ev in odds_events:
        bookmakers = ev.get("bookmakers") or []
        print(f"    {ev.get('home_team')} vs {ev.get('away_team')}  commence_time={ev.get('commence_time')}  "
              f"bookmakers={len(bookmakers)}")
    if r4.status_code != 200:
        print(f"  Body raspuns (primele 500 caractere): {r4.text[:500]}")

    section("5. Completitudine fata de calendarul oficial LPF Etapa 1 (8 meciuri)")
    all_found_names = [(ev.get("home_team", ""), ev.get("away_team", "")) for ev in events]
    found_count = 0
    for home, away in OFFICIAL_ETAPA_1:
        home_key = home.split()[0]
        away_key = away.split()[0]
        found = any(
            (home_key in h and away_key in a) or (home_key in a and away_key in h)
            for h, a in all_found_names
        )
        found_count += int(found)
        print(f"  {home} vs {away}: {'GASIT' if found else 'LIPSA'} in /events (fixtures Odds API)")
    print(f"\n  Completitudine Odds API /events pentru Etapa 1: {found_count}/8")

    section("6. Verificare cheie de sport alternativa (in caz ca 'soccer_romania_1_liga' nu e singura variantă posibilă)")
    candidate_keys = ["soccer_romania_liga_1", "soccer_romania_superliga", "soccer_romania_super_liga"]
    for ck in candidate_keys:
        rc = requests.get(f"{ODDS_API_URL}/sports/{ck}/events", params={"apiKey": ODDS_API_KEY}, timeout=20)
        print(f"  {ck}: HTTP {rc.status_code}")

    section("REZUMAT")
    print("Sectiunile 1-2 raspund daca liga e cu adevarat inactiva la Odds API sau daca")
    print("logica de validare din productie e prea stricta / gresita.")
    print("Sectiunile 3-4 raspund DIRECT la intrebarea: are Odds API meciuri/cote pentru")
    print("SuperLiga acum, indiferent de gate-ul din cod.")
    print("Sectiunea 5 da completitudinea exacta fata de calendarul oficial, aceeasi")
    print("metoda folosita si pentru TSDB, pentru comparatie corecta intre provideri.")


if __name__ == "__main__":
    main()
