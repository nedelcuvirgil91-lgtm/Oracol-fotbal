"""
================================================================================
FOOTBALL ORACLE — CLI: un singur apel poate acoperi tot sezonul SportAPI?
================================================================================
Module: sync/poc_sportapi_season_call_check.py

Discovery, NU integrare. Rezolva intrebarea ramasa deschisa din research-ul
anterior: endpoint-ul gasit de utilizator (path exact necunoscut - prima
incercare "uniquetournament" fara cratima a picat cu 404) foloseste
"unique-tournament" (CU cratima), la fel ca endpoint-ul de standings deja
confirmat functional. Testeaza:
  1. calea corecta, FARA parametrul date -> intoarce tot sezonul?
  2. aceeasi cale, CU parametrul date -> raspuns diferit (o singura runda)?
Raspunsul determina direct modelul de consum: 1 apel/sezon vs 1 apel/zi.

Rulare:
  python sync/poc_sportapi_season_call_check.py
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
UNIQUE_TOURNAMENT_ID = 152  # SuperLiga Romaniei, confirmat

_call_count = 0


def _call(km, label: str, path: str, params: dict | None = None) -> None:
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
        return
    events = data.get("events") if isinstance(data, dict) else None
    if isinstance(events, list):
        print(f"    numar meciuri in raspuns: {len(events)}")
        if events:
            rounds = sorted({(e.get("roundInfo") or {}).get("round") for e in events if isinstance(e, dict)})
            dates = sorted({e.get("startTimestamp") for e in events if isinstance(e, dict)})
            print(f"    runde distincte vazute: {rounds[:20]}")
            print(f"    numar timestamp-uri distincte: {len(dates)}")
    else:
        print(f"    body (truncat): {str(data)[:800]}")


def main() -> None:
    km = get_key_manager()
    if not km.is_available("sportapi"):
        print("Nicio cheie SportAPI activa - abandonat.")
        return

    path = f"api/v1/unique-tournament/{UNIQUE_TOURNAMENT_ID}/eventsbyuniquetournamentanddate"

    # 1. FARA parametrul date - intoarce tot sezonul?
    _call(km, "unique-tournament/152/eventsbyuniquetournamentanddate FARA date", path)

    # 2. CU parametrul date - o singura runda/zi?
    _call(km, "unique-tournament/152/eventsbyuniquetournamentanddate CU date=2026-07-17",
          path, params={"date": "2026-07-17"})

    print(f"\n=== TOTAL apeluri reale folosite in aceasta rulare: {_call_count} ===")


if __name__ == "__main__":
    main()
