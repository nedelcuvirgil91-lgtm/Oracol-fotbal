"""
================================================================================
FOOTBALL ORACLE — Verificare ultimele 4 echipe (Corvinul, Csikszereda, Rapid,
Sepsi OSK) via searchteams.php + eventsnext.php per echipa
================================================================================
Module: sync/poc_remaining_teams_check.py

Discovery, NU o schimbare de productie. Raspunde la ultima intrebare deschisa
inainte de inchiderea investigatiei TSDB: cele doua meciuri din Etapa 1
oficiala LPF care lipsesc din AMBELE endpointuri deja testate
(eventsnextleague.php si eventsseason.php/eventsround.php) —

    Corvinul Hunedoara vs FK Csikszereda Miercurea Ciuc  (20.07, 18:30)
    FC Rapid vs Sepsi OSK Sfantu Gheorghe                (20.07, 21:30)

— exista undeva in TheSportsDB, la nivel de echipa (eventsnext.php)?

Aceeasi metoda ca la Petrolul-Dinamo (poc_petrolul_dinamo_investigation.py,
sectiunea 5): cauta fiecare echipa prin searchteams.php, apoi verifica
eventsnext.php pentru idTeam gasit.

Rulare:
    python sync/poc_remaining_teams_check.py
================================================================================
"""
from __future__ import annotations

import requests

BASE = "https://www.thesportsdb.com/api/v1/json/3"

# (nume de cautat in searchteams.php, adversarul asteptat in eventsnext.php)
TEAMS_TO_CHECK = [
    ("Corvinul Hunedoara", "FK Csikszereda"),
    ("Csikszereda", "Corvinul"),
    ("Rapid Bucuresti", "Sepsi"),
    ("FC Rapid", "Sepsi"),
    ("Sepsi OSK", "Rapid"),
]

MISSING_MATCHES = [
    ("Corvinul Hunedoara", "FK Csikszereda Miercurea Ciuc"),
    ("FC Rapid", "Sepsi OSK Sfantu Gheorghe"),
]


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def tsdb_get(path: str, params: dict) -> dict | None:
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
    section("Cautare echipe (searchteams.php) + eventsnext.php per echipa gasita")

    found_events_by_team: dict[str, list[dict]] = {}
    resolved_teams: dict[str, str] = {}

    for query, expected_opponent_hint in TEAMS_TO_CHECK:
        print(f"\n[searchteams.php?t={query}]  (adversar asteptat contine: {expected_opponent_hint!r})")
        data = tsdb_get("searchteams.php", {"t": query})
        teams = (data or {}).get("teams") or []
        if not teams:
            print("  Niciun rezultat.")
            continue
        for t in teams:
            if (t.get("strSport") or "").lower() != "soccer":
                continue
            team_id = t.get("idTeam")
            team_name = t.get("strTeam")
            team_league = t.get("strLeague")
            print(f"  id={team_id}  name={team_name!r}  league={team_league!r}  country={t.get('strCountry')!r}")
            resolved_teams[query] = team_name

            next_data = tsdb_get("eventsnext.php", {"id": team_id})
            next_events = (next_data or {}).get("events") or []
            print(f"    eventsnext.php pentru id={team_id}: {len(next_events)} evenimente")
            for ev in next_events[:8]:
                print(f"      {ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}  "
                      f"date={ev.get('dateEvent')} time={ev.get('strTime')} league={ev.get('strLeague')!r}")
            found_events_by_team[f"{team_name} (id={team_id})"] = next_events

    section("VERIFICARE DIRECTA — cele 2 meciuri lipsa apar in vreun raspuns de mai sus?")
    all_events_flat: list[dict] = []
    for events in found_events_by_team.values():
        all_events_flat.extend(events)

    any_missing_found = False
    for home, away in MISSING_MATCHES:
        home_key = home.split()[0]
        away_key = away.split()[0]
        matches = [
            ev for ev in all_events_flat
            if home_key in (ev.get("strHomeTeam") or "") and away_key in (ev.get("strAwayTeam") or "")
            or home_key in (ev.get("strAwayTeam") or "") and away_key in (ev.get("strHomeTeam") or "")
        ]
        found = len(matches) > 0
        any_missing_found = any_missing_found or found
        print(f"\n  {home} vs {away}: {'GASIT' if found else 'LIPSA'}")
        for ev in matches:
            print(f"    -> {ev.get('strHomeTeam')} vs {ev.get('strAwayTeam')}  date={ev.get('dateEvent')} "
                  f"time={ev.get('strTime')} league={ev.get('strLeague')!r} id={ev.get('idEvent')}")

    section("ECHIPE REZOLVATE (dovada ca s-a cautat echipa corecta, nu un fals-negativ de nume)")
    for query, name in resolved_teams.items():
        print(f"  cautare {query!r} -> gasit ca {name!r}")
    for query, _ in TEAMS_TO_CHECK:
        if query not in resolved_teams:
            print(f"  cautare {query!r} -> NICIUN rezultat soccer in TheSportsDB")

    section("VERDICT FINAL")
    if any_missing_found:
        print("Cel putin unul dintre cele 2 meciuri lipsa A FOST gasit la nivel de echipa.")
        print("Concluzia 'baza TSDB e incompleta pentru etapa 1' NU se poate sustine inca —")
        print("reconcilierea trebuie extinsa cu acest rezultat inainte de decizia finala.")
    else:
        print("NICIUNUL dintre cele 2 meciuri lipsa (Corvinul-Csikszereda, Rapid-Sepsi OSK)")
        print("nu apare in eventsnext.php pentru nicio echipa gasita prin searchteams.php.")
        print("Impreuna cu absenta lor din eventsnextleague.php SI din eventsseason.php/")
        print("eventsround.php (verificate anterior), aceasta demonstreaza ca aceste 2")
        print("meciuri NU exista nicaieri in sistemul TheSportsDB pentru Etapa 1 —")
        print("baza de date TSDB este incompleta pentru aceasta runda, nu doar un artefact")
        print("de endpoint. Investigatia TSDB se poate inchide pe aceasta baza.")


if __name__ == "__main__":
    main()
