"""
================================================================================
FOOTBALL ORACLE — Investigatie: de ce Petrolul Ploiesti - Dinamo Bucuresti
nu ajunge in all_matches (2026-07-19, 19:30)
================================================================================
Module: sync/poc_petrolul_dinamo_investigation.py

Discovery, NU o schimbare de productie. Verifica EXCLUSIV daca meciul
Petrolul-Dinamo exista in raspunsul brut al fiecarui provider, si daca da,
la ce pas se pierde. Nu propune nimic - doar raporteaza dovada.

Rulare:
    python sync/poc_petrolul_dinamo_investigation.py
================================================================================
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import requests

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

TSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"
TARGET_DATE = "2026-07-19"


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def tsdb_get(path: str, params: dict) -> dict | None:
    try:
        r = requests.get(f"{TSDB_BASE}/{path}", params=params, timeout=20)
        print(f"  HTTP {r.status_code}  {r.url}")
        if r.status_code != 200:
            return None
        return r.json()
    except Exception as exc:
        print(f"  EROARE: {exc}")
        return None


def main() -> None:
    section("1. ODDS API — stare sport_key (referinta, deja confirmata anterior)")
    from mappings import ODDS_SPORT_KEYS
    sk = ODDS_SPORT_KEYS.get("Romania SuperLiga")
    print(f"sport_key='{sk}' — validat la fiecare pornire FootballOracleAPI() prin GET /sports (all=true).")
    print("Daca sport_key nu apare in lista de sporturi ACTIVE intoarsa de Odds API,")
    print("e marcat 'Dead' si NICIUN fixture, pentru NICIO liga inclusiv Petrolul-Dinamo,")
    print("nu poate fi obtinut de la acest provider — blocaj la nivel de COMPETITIE, nu de meci individual.")

    section("2. ESPN — raspuns brut, complet, pentru 2026-07-19 (rou.1)")
    r = requests.get(
        "https://site.api.espn.com/apis/site/v2/sports/soccer/rou.1/scoreboard",
        headers={"User-Agent": "Mozilla/5.0"},
        params={"dates": TARGET_DATE.replace("-", "")},
        timeout=20,
    )
    print(f"  HTTP {r.status_code}  {r.url}")
    if r.status_code == 200:
        data = r.json()
        events = data.get("events", [])
        print(f"  Total evenimente brute in raspuns: {len(events)}")
        for ev in events:
            comps = (ev.get("competitions") or [{}])[0]
            competitors = comps.get("competitors", [])
            names = [((c.get("team") or {}).get("displayName")) for c in competitors]
            print(f"    {names}  status={((ev.get('status') or {}).get('type') or {}).get('state')}")
        if not events:
            print("  ZERO evenimente in raspunsul brut — Petrolul-Dinamo NU exista deloc in ESPN pentru aceasta data/liga.")
    else:
        print(f"  Raspuns non-200, body: {r.text[:300]}")

    section("3. TheSportsDB — eventsnextleague.php?id=4691 (fresh, live)")
    data = tsdb_get("eventsnextleague.php", {"id": "4691"})
    events = (data or {}).get("events") or []
    print(f"  Total evenimente: {len(events)}")
    for ev in events:
        print(f"    {ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}  date={ev.get('dateEvent')} time={ev.get('strTime')} id={ev.get('idEvent')}")
    petrolul_in_next = any("Petrolul" in (ev.get("strHomeTeam") or "") or "Petrolul" in (ev.get("strAwayTeam") or "") for ev in events)
    print(f"  Petrolul apare in eventsnextleague? {petrolul_in_next}")

    section("4. TheSportsDB — eventsday.php?d=2026-07-19 (toate sporturile, fara filtru de liga)")
    data = tsdb_get("eventsday.php", {"d": TARGET_DATE})
    events = (data or {}).get("events") or []
    print(f"  Total evenimente (toate sporturile/ligile) pentru {TARGET_DATE}: {len(events)}")
    romania_related = [ev for ev in events if "Petrolul" in (ev.get("strHomeTeam") or "") + (ev.get("strAwayTeam") or "")
                        or "Dinamo" in (ev.get("strHomeTeam") or "") + (ev.get("strAwayTeam") or "")]
    for ev in romania_related:
        print(f"    GASIT: {ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}  league={ev.get('strLeague')!r} date={ev.get('dateEvent')}")
    if not romania_related:
        print("  NIMIC gasit cu 'Petrolul' sau 'Dinamo' in numele echipelor, in TOATE evenimentele zilei (orice sport/liga).")

    section("5. TheSportsDB — cautare echipe direct (searchteams.php)")
    for team_query in ("Petrolul Ploiesti", "Dinamo Bucuresti"):
        print(f"\n[searchteams.php?t={team_query}]")
        data = tsdb_get("searchteams.php", {"t": team_query})
        teams = (data or {}).get("teams") or []
        if not teams:
            print("  Niciun rezultat.")
            continue
        for t in teams:
            if (t.get("strSport") or "").lower() != "soccer":
                continue
            print(f"  id={t.get('idTeam')}  name={t.get('strTeam')!r}  league={t.get('strLeague')!r}")
            # verifica urmatoarele evenimente ale acestei echipe direct
            team_id = t.get("idTeam")
            next_data = tsdb_get("eventsnext.php", {"id": team_id})
            next_events = (next_data or {}).get("events") or []
            print(f"    eventsnext.php pentru id={team_id}: {len(next_events)} evenimente")
            for ev in next_events[:5]:
                print(f"      {ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}  date={ev.get('dateEvent')} league={ev.get('strLeague')!r}")

    section("6. API-Football — referinta (plan_restricted, cunoscut)")
    print("  Blocat la nivel de plan pentru sezonul curent — 0 fixtures, indiferent de meci, confirmat in sesiuni anterioare.")

    section("REZUMAT")
    print("Tabelul cerut se construieste din sectiunile 1-6 de mai sus, cu dovada exacta")
    print("(gasit / nu gasit / la ce pas) pentru fiecare provider.")


if __name__ == "__main__":
    main()
