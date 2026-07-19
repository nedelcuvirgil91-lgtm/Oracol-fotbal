"""
================================================================================
FOOTBALL ORACLE — Verificare completitudine ESPN pe toata Etapa 1 SuperLiga
================================================================================
Module: sync/poc_espn_full_round_check.py

Discovery, NU o schimbare de productie. Ultimul test agreat inainte de a
inchide definitiv cautarea unui provider unic si a trece la arhitectura
multi-provider (API-Football > ESPN > TheSportsDB > alt provider, deduplicat
prin match_key()).

ESPN nu are NICIODATA cote (home_odds/draw_odds/away_odds = None in
_fetch_matches_espn, oracle_api.py linia 764) — deci chiar daca iese 8/8 pe
meciuri, tot ar fi nevoie de un provider separat pentru cote (Odds API,
exclus deja pentru Romania). Testul de aici raspunde STRICT la intrebarea:
"ESPN are lista COMPLETA de meciuri pentru Etapa 1?" - nu la intrebarea de
cote, care e deja tranșată.

Testeaza toate cele 4 zile ale rundei oficiale LPF (17-20 iulie 2026),
folosind exact endpoint-ul si slug-ul din productie (rou.1, scoreboard,
parametrul `dates`), comparat cu cele 8 meciuri oficiale confirmate anterior.

Rulare:
    python sync/poc_espn_full_round_check.py
================================================================================
"""
from __future__ import annotations

import requests

ESPN_API_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer"
SLUG = "rou.1"

MATCHDAYS = ["2026-07-17", "2026-07-18", "2026-07-19", "2026-07-20"]

OFFICIAL_ETAPA_1 = [
    ("FC Voluntari", "FC Botoșani", "2026-07-17"),
    ("FCSB", "FC Argeș", "2026-07-17"),
    ("Oțelul Galați", "CFR 1907 Cluj", "2026-07-18"),
    ("Universitatea Craiova", "UTA Arad", "2026-07-18"),
    ("Universitatea Cluj", "Farul Constanța", "2026-07-19"),
    ("Petrolul Ploiești", "Dinamo", "2026-07-19"),
    ("Corvinul Hunedoara", "FK Csíkszereda Miercurea Ciuc", "2026-07-20"),
    ("FC Rapid", "Sepsi OSK Sf. Gheorghe", "2026-07-20"),
]


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    section("ESPN scoreboard (rou.1) — toate cele 4 zile ale Etapei 1, apeluri reale")
    all_events: list[dict] = []
    for d in MATCHDAYS:
        r = requests.get(
            f"{ESPN_API_URL}/{SLUG}/scoreboard",
            headers={"User-Agent": "Mozilla/5.0"},
            params={"dates": d.replace("-", "")},
            timeout=20,
        )
        print(f"\n[dates={d}]  HTTP {r.status_code}  {r.url}")
        if r.status_code != 200:
            print(f"  Body (primele 300 caractere): {r.text[:300]}")
            continue
        data = r.json()
        events = data.get("events", [])
        print(f"  Total evenimente brute: {len(events)}")
        for ev in events:
            comps = (ev.get("competitions") or [{}])[0]
            competitors = comps.get("competitors", [])
            names = [((c.get("team") or {}).get("displayName")) for c in competitors]
            state = ((ev.get("status") or {}).get("type") or {}).get("state")
            print(f"    {names}  date={ev.get('date')}  status={state}")
            all_events.append({"raw": ev, "date": d, "names": names})

    section("Completitudine fata de calendarul oficial LPF Etapa 1 (8 meciuri)")
    found_count = 0
    for home, away, expected_date in OFFICIAL_ETAPA_1:
        home_key = home.split()[0]
        away_key = away.split()[0]
        matches = [
            e for e in all_events
            if len(e["names"]) == 2
            and ((home_key in (e["names"][0] or "") and away_key in (e["names"][1] or ""))
                 or (home_key in (e["names"][1] or "") and away_key in (e["names"][0] or "")))
        ]
        found = len(matches) > 0
        found_count += int(found)
        print(f"\n  {home} vs {away} (asteptat {expected_date}): {'GASIT' if found else 'LIPSA'}")
        for m in matches:
            print(f"    -> {m['names']}  ceruta pentru ziua={m['date']}  "
                  f"date_eveniment={m['raw'].get('date')}")

    print(f"\n  Completitudine ESPN pentru Etapa 1: {found_count}/8")

    section("REZUMAT")
    print("Raspuns direct la intrebarea agreata: ESPN e 100% pentru Etapa 1 sau nu.")
    print("Reamintire: ESPN nu are NICIODATA cote (vezi oracle_api.py linia 764) —")
    print("chiar daca meciurile sunt complete, cotele tot vin din alt provider.")


if __name__ == "__main__":
    main()
