"""
================================================================================
FOOTBALL ORACLE — CLI: verificare practica FreeLF pentru Romania SuperLiga
================================================================================
Module: sync/poc_freelf_romania_check.py

Discovery, NU integrare. Free Live Football (RapidAPI) nu are un endpoint de
cautare ligi dupa tara — "football-get-matches-by-date" intoarce TOATE
meciurile globale pentru o data, filtrate local dupa parentLeagueId (asa
functioneaza deja oracle_api._fetch_freelf_matches()). Ca sa gasim
parentLeagueId-ul real pentru Romania SuperLiga, scanam raspunsul brut,
pentru cateva date din jurul inceputului de sezon (2026-07-18, confirmat
separat prin API-Football /leagues), dupa nume de echipe romanesti cunoscute
— fara sa presupunem niciun ID.

Rulare:
  python sync/poc_freelf_romania_check.py --dates 2026-07-17 2026-07-18 2026-07-19 2026-07-20
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

# Aceeasi cheie/URL deja folosite in productie de oracle_api.py — nu introduc
# nimic nou, doar reutilizez ce exista deja (RAPIDAPI_KEY e cunoscut hardcodat
# in oracle_api.py, documentat in CLAUDE.md ca gol cunoscut, neurgent).
from oracle_api import FREE_LF_URL, FREE_LF_HOST, RAPIDAPI_KEY

# Nume de cluburi din Romania SuperLiga 2026-27 (sezon confirmat separat prin
# API-Football /leagues, league_id=283) — folosite DOAR ca filtru text peste
# date reale, nu ca sursa de identificare a ligii.
ROMANIAN_CLUB_HINTS = [
    "FCSB", "CFR Cluj", "Craiova", "Rapid", "Farul", "Petrolul", "Dinamo",
    "UTA Arad", "Sepsi", "Botosani", "Botoșani", "Hermannstadt", "Slobozia",
    "Otelul", "Oțelul", "Csikszereda", "Poli Iasi", "Poli Iași", "Unirea",
]


def _matches_romanian_hint(name: str) -> bool:
    low = name.lower()
    return any(hint.lower() in low for hint in ROMANIAN_CLUB_HINTS)


def check_date(date_str: str) -> None:
    date_fmt = date_str.replace("-", "")
    r = requests.get(
        f"{FREE_LF_URL}/football-get-matches-by-date",
        headers={"x-rapidapi-key": RAPIDAPI_KEY, "x-rapidapi-host": FREE_LF_HOST},
        params={"date": date_fmt},
        timeout=15,
    )
    print(f"\n=== {date_str} — HTTP {r.status_code} ===")
    if not r.ok:
        print(f"Body: {r.text[:500]}")
        return
    data = r.json()
    resp = data.get("response")
    raw_list = []
    if isinstance(resp, list):
        raw_list = resp
    elif isinstance(resp, dict):
        for inner_key in ("matches", "events", "data", "fixtures", "results"):
            if isinstance(resp.get(inner_key), list):
                raw_list = resp[inner_key]
                break
    print(f"Total meciuri in raspuns: {len(raw_list)}")

    found = []
    all_league_ids = set()
    for ev in raw_list:
        if not isinstance(ev, dict):
            continue
        home = (ev.get("homeTeam") or {}).get("name", "") or ""
        away = (ev.get("awayTeam") or {}).get("name", "") or ""
        parent_lid = ev.get("parentLeagueId") or ev.get("leagueId")
        all_league_ids.add(parent_lid)
        if _matches_romanian_hint(home) or _matches_romanian_hint(away):
            found.append((home, away, parent_lid, ev.get("leagueId"), ev.get("status")))

    if found:
        print(f"Meciuri romanesti gasite ({len(found)}):")
        for home, away, parent_lid, lid, status in found:
            print(f"  {home} vs {away}  parentLeagueId={parent_lid}  leagueId={lid}  status={status}")
    else:
        print("Niciun meci cu echipe romanesti gasit in acest raspuns.")
        print(f"(distinct parentLeagueId/leagueId vazute in total: {len(all_league_ids)})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verificare practica FreeLF pentru Romania SuperLiga")
    parser.add_argument("--dates", nargs="+", required=True)
    args = parser.parse_args()
    for d in args.dates:
        check_date(d)


if __name__ == "__main__":
    main()
