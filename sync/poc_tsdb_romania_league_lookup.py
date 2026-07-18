"""
================================================================================
FOOTBALL ORACLE — Diagnostic: ID-ul real TheSportsDB pentru Romania SuperLiga
================================================================================
Module: sync/poc_tsdb_romania_league_lookup.py

Discovery, NU o schimbare de productie. Verifica live, cu dovada:
  1. Ce liga este de fapt id=4652 (valoarea actuala, gresita, din mappings.py)
     — lookupleague.php?id=4652.
  2. Toate ligile de fotbal din Romania cunoscute de TheSportsDB
     — search_all_leagues.php?c=Romania&s=Soccer.
  3. Pentru fiecare candidat gasit: eventsnextleague.php?id=... — contine
     meciurile reale de azi (Otelul Galati - CFR Cluj, U Craiova - UTA Arad)?

TheSportsDB free tier (cheia publica "3") — zero cost de cota, fara secrete.

Rulare:
    python sync/poc_tsdb_romania_league_lookup.py
================================================================================
"""
from __future__ import annotations

import json

import requests

BASE = "https://www.thesportsdb.com/api/v1/json/3"


def get(path: str, params: dict) -> dict | None:
    try:
        r = requests.get(f"{BASE}/{path}", params=params, timeout=20)
        print(f"  HTTP {r.status_code}  {r.url}")
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as exc:
        print(f"  EROARE: {exc}")
        return None


def main() -> None:
    print("=" * 78)
    print("1. Ce liga este id=4652 (valoarea actuala din mappings.py)?")
    print("=" * 78)
    data = get("lookupleague.php", {"id": "4652"})
    for lg in (data or {}).get("leagues") or []:
        print(f"  id={lg.get('idLeague')}  name={lg.get('strLeague')!r}  "
              f"country={lg.get('strCountry')!r}  sport={lg.get('strSport')!r}")

    print()
    print("=" * 78)
    print("2. Ligile de fotbal din Romania cunoscute de TheSportsDB")
    print("=" * 78)
    data = get("search_all_leagues.php", {"c": "Romania", "s": "Soccer"})
    candidates: list[tuple[str, str]] = []
    for lg in (data or {}).get("countries") or (data or {}).get("countrys") or []:
        lid = lg.get("idLeague")
        name = lg.get("strLeague")
        print(f"  id={lid}  name={name!r}")
        candidates.append((lid, name))

    print()
    print("=" * 78)
    print("3. eventsnextleague.php pentru fiecare candidat — meciurile reale?")
    print("=" * 78)
    for lid, name in candidates:
        print(f"\n[{lid}] {name!r}:")
        data = get("eventsnextleague.php", {"id": lid})
        events = (data or {}).get("events") or []
        if not events:
            print("  (niciun meci viitor returnat)")
        for ev in events[:10]:
            print(f"    {ev.get('strHomeTeam')!r} vs {ev.get('strAwayTeam')!r}  "
                  f"date={ev.get('dateEvent')}  time={ev.get('strTime')}")

    print()
    print("=" * 78)
    print("4. eventsday.php — TOATE meciurile Ligii I de azi (U Craiova-UTA exista?)")
    print("=" * 78)
    from datetime import date as _date
    today = _date.today().isoformat()
    data = get("eventsday.php", {"d": today, "l": "Romanian Liga I"})
    events = (data or {}).get("events") or []
    if not events:
        print(f"  (niciun meci returnat pentru {today})")
    for ev in events:
        print(f"    {ev.get('strHomeTeam')!r} vs {ev.get('strAwayTeam')!r}  "
              f"date={ev.get('dateEvent')}  time={ev.get('strTime')}  "
              f"league={ev.get('strLeague')!r}")


if __name__ == "__main__":
    main()
