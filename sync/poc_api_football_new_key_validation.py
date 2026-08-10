"""
================================================================================
FOOTBALL ORACLE — POC izolat: validare cheie NOUĂ API-Football
================================================================================
Module: sync/poc_api_football_new_key_validation.py

POC temporar, per Regula 1 din CLAUDE.md ("Regulile pentru chei API și
provideri externi") — contul API-Football activ e SUSPENDAT ("Your account
is suspended"), utilizatorul a furnizat o cheie nouă, de pe alt cont.

NU importă `key_manager.py`, NU citește variabila cheii vechi (API_FOOTBALL_
KEY), NU e importat de niciun cod de producție, rulează DOAR prin
workflow_dispatch manual. Citește STRICT `API_FOOTBALL_KEY_NEW`.

Pași (Regula 1, pas 2-4):
  1. Autentificare — GET /status (endpoint dedicat API-Football pentru cont:
     plan, cotă rămasă, requests folosite).
  2. Endpoint-uri reale, aceleași folosite deja de football_providers.py:
     - /leagues?country=<țară> — pentru Belgia/Polonia/Scoția (închide și
       verificarea LEAGUE_PROVIDERS lăsată "necunoscut" azi din cauza
       suspendării).
     - /teams?search=<echipă cunoscută> — structura așteptată de
       ApiFootballProvider.resolve_team_id() (response[0].team.id).
     - /injuries?team=<id>&season=<an> — structura așteptată de
       get_injuries()/_normalize_injury() (response[].player/team/fixture).
     - /coachs?team=<id> — structura așteptată de get_coaches()/
       _normalize_coach() (response[].name/team/career).
  3. Comparație explicită, per câmp, cu ce așteaptă parserul existent —
     afișată brut, nu presupusă.

Rulare:
    python sync/poc_api_football_new_key_validation.py
================================================================================
"""
from __future__ import annotations

import os

import requests

BASE_URL = "https://v3.football.api-sports.io"
COUNTRIES = ["Belgium", "Poland", "Scotland"]
KNOWN_TEAM = "Real Madrid"


def _print_header(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def _headers() -> dict[str, str] | None:
    key = os.environ.get("API_FOOTBALL_KEY_NEW")
    if not key:
        print("API_FOOTBALL_KEY_NEW lipsește din mediu — verificare abandonată.")
        return None
    return {"x-apisports-key": key}


def check_status(headers: dict[str, str]) -> None:
    _print_header("1. GET /status — autentificare + stare cont")
    resp = requests.get(f"{BASE_URL}/status", headers=headers, timeout=15)
    print(f"HTTP {resp.status_code}")
    print(resp.text[:2000])


def check_leagues(headers: dict[str, str]) -> None:
    _print_header("2. GET /leagues?country=<țară> — Belgia/Polonia/Scoția")
    for country in COUNTRIES:
        resp = requests.get(f"{BASE_URL}/leagues", headers=headers,
                             params={"country": country}, timeout=15)
        print(f"\n  --- {country} --- HTTP {resp.status_code}")
        if resp.status_code != 200:
            print(f"  Body: {resp.text[:500]}")
            continue
        data = resp.json()
        if data.get("errors"):
            print(f"  Errors: {data['errors']}")
        results = data.get("response", [])
        print(f"  {len(results)} competiții găsite:")
        for entry in results:
            league = entry.get("league", {})
            seasons = entry.get("seasons", [])
            current = [s for s in seasons if s.get("current")]
            print(f"    league_id={league.get('id')}  name={league.get('name')!r}  "
                  f"type={league.get('type')}  sezon_curent={bool(current)}")


def check_team_search_and_downstream(headers: dict[str, str]) -> int | None:
    _print_header(f"3. GET /teams?search={KNOWN_TEAM!r} — structură vs. resolve_team_id()")
    resp = requests.get(f"{BASE_URL}/teams", headers=headers,
                         params={"search": KNOWN_TEAM}, timeout=15)
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:1000]}")
        return None
    data = resp.json()
    if data.get("errors"):
        print(f"Errors: {data['errors']}")
    results = data.get("response", [])
    print(f"{len(results)} echipe găsite pentru {KNOWN_TEAM!r}.")
    if not results:
        return None
    first = results[0]
    print(f"  Element brut [0]: {first}")
    team_obj = first.get("team") if isinstance(first, dict) else None
    team_id = team_obj.get("id") if isinstance(team_obj, dict) else None
    print(f"  Verificare structură așteptată de resolve_team_id(): "
          f"response[0]['team']['id'] = {team_id!r} "
          f"({'GĂSIT — parserul existent funcționează' if team_id is not None else 'LIPSĂ — parserul existent ar EȘUA'})")
    return int(team_id) if team_id is not None else None


def check_injuries(headers: dict[str, str], team_id: int) -> None:
    from datetime import date
    season = date.today().year
    _print_header(f"4. GET /injuries?team={team_id}&season={season} — structură vs. _normalize_injury()")
    resp = requests.get(f"{BASE_URL}/injuries", headers=headers,
                         params={"team": team_id, "season": season}, timeout=15)
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:1000]}")
        return
    data = resp.json()
    if data.get("errors"):
        print(f"Errors: {data['errors']}")
    results = data.get("response", [])
    print(f"{len(results)} rânduri /injuries găsite.")
    if results:
        item = results[0]
        print(f"  Element brut [0]: {item}")
        player = item.get("player") or {}
        injury_type = item.get("type") or player.get("type")
        reason = item.get("reason") or player.get("reason")
        print(f"  Verificare structură așteptată de _normalize_injury(): "
              f"type={injury_type!r}  reason={reason!r}  "
              f"({'GĂSIT' if (injury_type or reason) else 'LIPSĂ — structura reală diferă de presupunere'})")
    else:
        print("  (0 accidentări curente pentru această echipă — posibil normal, nu neapărat o eroare de structură)")


def check_coaches(headers: dict[str, str], team_id: int) -> None:
    _print_header(f"5. GET /coachs?team={team_id} — structură vs. _normalize_coach()")
    resp = requests.get(f"{BASE_URL}/coachs", headers=headers,
                         params={"team": team_id}, timeout=15)
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:1000]}")
        return
    data = resp.json()
    if data.get("errors"):
        print(f"Errors: {data['errors']}")
    results = data.get("response", [])
    print(f"{len(results)} rânduri /coachs găsite.")
    if results:
        item = results[0]
        print(f"  Element brut [0] (trunchiat): "
              f"id={item.get('id')}  name={item.get('name')!r}  "
              f"nationality={item.get('nationality')!r}  career_len={len(item.get('career') or [])}")


def main() -> None:
    headers = _headers()
    if headers is None:
        return
    check_status(headers)
    check_leagues(headers)
    team_id = check_team_search_and_downstream(headers)
    if team_id is not None:
        check_injuries(headers, team_id)
        check_coaches(headers, team_id)
    else:
        print("\nTeam ID nerezolvat — /injuries și /coachs sărite (necesită un team_id real).")


if __name__ == "__main__":
    main()
