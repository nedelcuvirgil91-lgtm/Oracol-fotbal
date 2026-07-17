"""
================================================================================
FOOTBALL ORACLE — CLI: sondaj API-Football /leagues (căutare league_id)
================================================================================
Module: sync/poc_api_football_league_lookup.py

Discovery, NU integrare. Interoghează /leagues?country=<țară> pe API-Football
și afișează, brut, toate competițiile găsite (id, nume, tip, sezoane
acoperite) — singura sursă de adevăr pentru un league_id real, nicio valoare
nu e presupusă sau inventată în cod.

Nu scrie în match_history, nu atinge mappings.py, nu e importat de
oracle_engine.py. Un singur apel HTTP per rulare (endpoint-ul /leagues nu are
echivalent per-fixture, deci nu există cache de reutilizat aici — costul e
minim și intenționat, o rulare manuală, nu automată).

Rulare:
  python sync/poc_api_football_league_lookup.py --country "Romania"

Rulat de obicei prin GitHub Actions (workflow_dispatch — vezi
.github/workflows/poc_api_football_league_lookup.yml), unde există acces real
la Internet, spre deosebire de mediul de dezvoltare curent.
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


def lookup_leagues(country: str) -> None:
    km = get_key_manager()
    if not km.is_available("apifootball"):
        print("Nicio cheie API-Football activă în key_manager — verificare abandonată.")
        return

    headers = km.get_headers("apifootball")
    url = "https://v3.football.api-sports.io/leagues"
    resp = requests.get(url, headers=headers, params={"country": country}, timeout=15)
    km.record_request("apifootball")

    print(f"HTTP {resp.status_code} — {url}?country={country}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:1000]}")
        return

    data = resp.json()
    errors = data.get("errors")
    if errors:
        print(f"Errors: {errors}")

    results = data.get("response", [])
    print(f"{len(results)} competiții găsite pentru country={country!r}:\n")
    for entry in results:
        league = entry.get("league", {})
        country_block = entry.get("country", {})
        seasons = entry.get("seasons", [])
        current_seasons = [s for s in seasons if s.get("current")]
        print(f"  league_id={league.get('id')}  name={league.get('name')!r}  "
              f"type={league.get('type')}  country={country_block.get('name')}")
        if current_seasons:
            for s in current_seasons:
                print(f"      sezon curent: {s.get('year')}  "
                      f"({s.get('start')} → {s.get('end')})  coverage_fixtures={s.get('coverage', {}).get('fixtures')}")
        else:
            print("      (niciun sezon marcat 'current')")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sondaj API-Football /leagues (căutare league_id real, discovery)")
    parser.add_argument("--country", required=True, help='Ex: "Romania"')
    args = parser.parse_args()
    lookup_leagues(args.country)


if __name__ == "__main__":
    main()
