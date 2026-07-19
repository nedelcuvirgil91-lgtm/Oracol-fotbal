"""
================================================================================
FOOTBALL ORACLE — Verificare eventsseason/eventsround + lookup_all_teams +
rate limit real TheSportsDB, pentru Romania SuperLiga (id=4691)
================================================================================
Module: sync/poc_tsdb_season_round_ratelimit_check.py

Discovery, NU o schimbare de productie. Raspunde exact intrebarilor cerute
la review inainte de orice decizie A/B/C:
  1. eventsseason.php si eventsround.php - complete sau nu (comparativ cu
     eventsnextleague.php si eventsnext.php, deja verificate anterior)?
  2. lookup_all_teams.php - poate popula automat TSDB_TEAM_IDS fara
     mentenanta manuala?
  3. Rate limit real - test de burst (15 apeluri rapide), raporteaza orice
     429/eroare si orice header de rate-limit prezent in raspuns.

Rulare:
    python sync/poc_tsdb_season_round_ratelimit_check.py
================================================================================
"""
from __future__ import annotations

import time

import requests

BASE = "https://www.thesportsdb.com/api/v1/json/3"
LEAGUE_ID = "4691"

KNOWN_MATCHES = [
    ("Universitatea Cluj", "Farul Constanța"),
    ("Petrolul Ploiești", "Dinamo București"),
]


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def get(path: str, params: dict) -> tuple[int, dict | None, dict]:
    r = requests.get(f"{BASE}/{path}", params=params, timeout=20)
    print(f"  HTTP {r.status_code}  {r.url}")
    headers_of_interest = {k: v for k, v in r.headers.items() if "rate" in k.lower() or "limit" in k.lower() or "retry" in k.lower()}
    if headers_of_interest:
        print(f"  Headere relevante: {headers_of_interest}")
    try:
        return r.status_code, (r.json() if r.status_code == 200 else None), dict(r.headers)
    except Exception as exc:
        print(f"  EROARE parsare JSON: {exc}")
        return r.status_code, None, dict(r.headers)


def check_known_matches(events: list[dict], label: str) -> None:
    print(f"\n  Verificare meciuri cunoscute in raspunsul '{label}' ({len(events)} evenimente totale):")
    for home, away in KNOWN_MATCHES:
        found = any(
            (ev.get("strHomeTeam") == home and ev.get("strAwayTeam") == away)
            for ev in events
        )
        print(f"    {home} vs {away}: {'GASIT' if found else 'LIPSA'}")
    print(f"  Toate evenimentele din '{label}':")
    for ev in events:
        print(f"    {ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}  date={ev.get('dateEvent')}  round={ev.get('intRound')}")


def main() -> None:
    section("1. eventsseason.php — sezon complet (incearca cateva formate de sezon)")
    season_events: list[dict] = []
    for season in ("2026-2027", "2026", "2025-2026"):
        print(f"\n[season={season}]")
        status, data, _ = get("eventsseason.php", {"id": LEAGUE_ID, "s": season})
        events = (data or {}).get("events") or []
        print(f"  Total evenimente: {len(events)}")
        if events:
            season_events = events
            check_known_matches(events, f"eventsseason.php (s={season})")
            break

    section("2. eventsround.php — testare per runda (round 1-5, sezon detectat sau implicit)")
    for rnd in range(1, 6):
        print(f"\n[round={rnd}]")
        status, data, _ = get("eventsround.php", {"id": LEAGUE_ID, "r": str(rnd), "s": "2026-2027"})
        events = (data or {}).get("events") or []
        print(f"  Total evenimente: {len(events)}")
        for ev in events:
            print(f"    {ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}  date={ev.get('dateEvent')}")
        if any(ev.get("dateEvent") == "2026-07-19" for ev in events):
            print("  >>> Aceasta runda contine data 2026-07-19 - verificare directa meciuri cunoscute:")
            check_known_matches(events, f"eventsround.php (r={rnd})")

    section("3. lookup_all_teams.php — populare automata TSDB_TEAM_IDS?")
    status, data, _ = get("lookup_all_teams.php", {"id": LEAGUE_ID})
    teams = (data or {}).get("teams") or []
    print(f"  Total echipe returnate: {len(teams)}")
    for t in teams:
        print(f"    id={t.get('idTeam')}  name={t.get('strTeam')!r}")
    names_found = {t.get("strTeam") for t in teams}
    for home, away in KNOWN_MATCHES:
        print(f"  '{home}' in lista de echipe? {home in names_found or any(home in n for n in names_found)}")
        print(f"  '{away}' in lista de echipe? {away in names_found or any(away in n for n in names_found)}")

    section("4. Rate limit real — test de burst (15 apeluri rapide consecutive)")
    t0 = time.perf_counter()
    statuses = []
    for i in range(15):
        r = requests.get(f"{BASE}/lookupleague.php", params={"id": LEAGUE_ID}, timeout=20)
        statuses.append(r.status_code)
        rl_headers = {k: v for k, v in r.headers.items() if "rate" in k.lower() or "limit" in k.lower()}
        if rl_headers:
            print(f"  apel {i+1}: HTTP {r.status_code}  headere: {rl_headers}")
        else:
            print(f"  apel {i+1}: HTTP {r.status_code}")
    elapsed = time.perf_counter() - t0
    print(f"\n  15 apeluri in {elapsed:.2f}s ({15/elapsed:.1f} req/s)")
    print(f"  Coduri de status: {statuses}")
    non_200 = [s for s in statuses if s != 200]
    print(f"  Apeluri esuate (non-200): {len(non_200)} — {non_200}")

    section("REZUMAT")
    print("Sectiunile 1-2 raspund direct la intrebarea A vs B (endpoint complet vs fallback).")
    print("Sectiunile 3-4 raspund la intrebarile de fezabilitate pentru varianta B, daca e necesara.")


if __name__ == "__main__":
    main()
