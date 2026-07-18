"""
================================================================================
FOOTBALL ORACLE — CLI: sondaj de adancime SportAPI (sportapi7, RapidAPI)
================================================================================
Module: sync/poc_sportapi_deep_check.py

Discovery, NU integrare. Continuare a poc_sportapi_check.py — foloseste
event_id=16403828 (FC Voluntari vs FC Botosani, deja confirmat, Romania
SuperLiga) ca sa testeze endpoint-uri suplimentare: statistics, incidents,
lineups (+ ratinguri jucatori), player career-statistics, echipa/squad,
H2H, manageri/antrenori (cai presupuse, testate — nu ghicite in productie),
injuries (cale presupusa), odds pe sport/data. Fiecare rezultat raportat
brut, HTTP status inclus — "NOT VERIFIED" ramane responsabilitatea
raportului final, nu a acestui script (care doar culege dovezi).

Cota Free = 50 cereri/LUNA — acest script continua contorizarea prin
key_manager (record_request), deliberat un numar limitat de apeluri.

Rulare:
  python sync/poc_sportapi_deep_check.py
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import requests

from key_manager import get_key_manager

BASE_URL = "https://sportapi7.p.rapidapi.com"
EVENT_ID = 16403828      # FC Voluntari vs FC Botosani, confirmat
TEAM_ID = 44255           # FC Voluntari, confirmat din raspunsul anterior

_call_count = 0


def _call(km, label: str, path: str, params: dict | None = None) -> dict | None:
    global _call_count
    headers = km.get_headers("sportapi")
    r = requests.get(f"{BASE_URL}/{path}", headers=headers, params=params or {}, timeout=15)
    km.record_request("sportapi")
    _call_count += 1
    print(f"\n[{_call_count}] {label}")
    print(f"    GET {path}  params={params}")
    print(f"    HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        print(f"    Non-JSON body: {r.text[:300]}")
        return None
    print(f"    body (truncat, 2500 caractere): {str(data)[:2500]}")
    return data


def main() -> None:
    km = get_key_manager()
    if not km.is_available("sportapi"):
        print("Nicio cheie SportAPI activa - abandonat.")
        return

    # 1. Statistici echipa per meci — xG/posesie/suturi/cornere/cartonase?
    _call(km, "event/{id}/statistics", f"api/v1/event/{EVENT_ID}/statistics")

    # 2. Incidente — goluri/cartonase/schimbari/VAR
    _call(km, "event/{id}/incidents", f"api/v1/event/{EVENT_ID}/incidents")

    # 3. Lineups — inclusiv ratinguri jucatori?
    lineups = _call(km, "event/{id}/lineups", f"api/v1/event/{EVENT_ID}/lineups")

    # 4. H2H — cale presupusa (nedocumentata public)
    _call(km, "event/{id}/h2h (cale presupusa)", f"api/v1/event/{EVENT_ID}/h2h")

    # 5. Manageri/antrenori — cale presupusa (nedocumentata public)
    _call(km, "event/{id}/managers (cale presupusa)", f"api/v1/event/{EVENT_ID}/managers")

    # 6. Squad echipa
    _call(km, "team/{id}/players (squad)", f"api/v1/team/{TEAM_ID}/players")

    # 7. Injuries — cale presupusa (nedocumentata public)
    _call(km, "team/{id}/injuries (cale presupusa)", f"api/v1/team/{TEAM_ID}/injuries")

    # 8. Player career-statistics — extrage un player_id real din lineups, daca exista
    player_id = None
    if isinstance(lineups, dict):
        home = lineups.get("home") or {}
        players = home.get("players") if isinstance(home, dict) else None
        if isinstance(players, list) and players:
            first = players[0]
            if isinstance(first, dict):
                pl = first.get("player") or {}
                player_id = pl.get("id")
    if player_id:
        _call(km, f"player/{player_id}/career-statistics",
              f"api/v1/player/{player_id}/career-statistics")
    else:
        print("\n[player career-statistics] SARIT - niciun player.id gasit in lineups "
              "(schema reala difera de presupunere, vezi raspunsul brut de mai sus).")

    # 9. Odds pentru tot sportul/o data - un singur apel acopera toate meciurile?
    _call(km, "sport/football/odds/1/{date}", "api/v1/sport/football/odds/1/2026-07-17")

    print(f"\n=== TOTAL apeluri reale folosite in aceasta rulare: {_call_count} ===")


if __name__ == "__main__":
    main()
