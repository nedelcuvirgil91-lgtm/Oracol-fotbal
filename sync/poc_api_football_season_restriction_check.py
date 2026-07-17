"""
================================================================================
FOOTBALL ORACLE — CLI: verificare practica a restrictiei de sezon (plan Free)
================================================================================
Module: sync/poc_api_football_season_restriction_check.py

Discovery, NU integrare — nu foloseste ApiFootballProvider (nu scrie in
cache-ul de productie, nu polueaza provider_metrics). Testeaza direct, cu
apeluri HTTP reale minime, daca parametri alternativi documentati oficial
(`next=`, `date=`, `live=`) ocolesc restrictia de sezon observata pe
`/fixtures?league=283&season=2026` (eroare: "Free plans do not have access
to this season, try from 2022 to 2024.").

Rulare:
  python sync/poc_api_football_season_restriction_check.py --league-id 283
================================================================================
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import requests

from key_manager import get_key_manager

BASE_URL = "https://v3.football.api-sports.io"


def _call(km, path: str, params: dict) -> None:
    headers = km.get_headers("apifootball")
    r = requests.get(f"{BASE_URL}/{path}", headers=headers, params=params, timeout=15)
    km.record_request("apifootball")
    print(f"\nGET {path}?{'&'.join(f'{k}={v}' for k, v in params.items())}")
    print(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        print(f"Non-JSON body: {r.text[:500]}")
        return
    print(f"errors={data.get('errors')}  results={data.get('results')}  "
          f"response_len={len(data.get('response') or [])}")
    if data.get("response"):
        print(f"first_response_item={data['response'][0]}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verificare practica: next=/date=/live= ocolesc restrictia de sezon?")
    parser.add_argument("--league-id", type=int, required=True)
    args = parser.parse_args()

    km = get_key_manager()
    if not km.is_available("apifootball"):
        print("Nicio cheie API-Football activa — abandonat.")
        return

    # 1. /fixtures?league=&next= — fara parametrul season explicit
    _call(km, "fixtures", {"league": args.league_id, "next": 5})

    # 2. /fixtures?league=&date= — fara parametrul season explicit
    from datetime import date, timedelta
    target = (date.today() + timedelta(days=1)).isoformat()
    _call(km, "fixtures", {"league": args.league_id, "date": target})

    # 3. /fixtures?live=all — global, fara league/season deloc
    _call(km, "fixtures", {"live": "all"})


if __name__ == "__main__":
    main()
