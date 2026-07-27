"""
================================================================================
FOOTBALL ORACLE — POC TEMPORAR v5: bogatia campurilor din matches/day/full
================================================================================
Module: sync/poc_soccer_football_info_check_v5.py

Intrebare unica, punctuala: /matches/day/full/ (un singur apel, toate
meciurile globale ale unei zile) contine deja blocul "stats" complet per
meci (possession, shots, cards etc.), sau doar scor+perf, cu statisticile
disponibile DOAR prin /matches/view/full/ (un apel per meci)?

Raspunsul determina bugetul zilnic real de requesturi: daca day/full are
deja stats, Match Statistics pentru o zi intreaga de SuperLiga costa 1
request, nu N+1. Verificare ceruta explicit de Product Owner inainte de
estimarea consumului.

Discovery, NU integrare. POC izolat, temporar — sters dupa test.
================================================================================
"""
from __future__ import annotations

import json
import os
import sys

import requests

HOST = "soccer-football-info.p.rapidapi.com"
BASE = f"https://{HOST}"
LIGA_I_ID = "6250830696ec934"  # "Romania Liga I", confirmat live anterior


def _headers() -> dict:
    key = os.environ.get("RAPIDAPI_KEY_FREELIVEFOOTBALL", "")
    if not key:
        print("EROARE: RAPIDAPI_KEY_FREELIVEFOOTBALL nu e setat in mediu.")
        sys.exit(1)
    return {"x-rapidapi-key": key, "x-rapidapi-host": HOST}


def main() -> None:
    print("=" * 80)
    print("POC v5 — bogatia campurilor in /matches/day/full/")
    print("=" * 80)

    d = "20251101"  # zi cu 2 meciuri Romania Liga I, confirmata anterior
    r = requests.get(f"{BASE}/matches/day/full/", headers=_headers(), params={"d": d}, timeout=25)
    print(f"\nGET /matches/day/full/?d={d} -> HTTP {r.status_code}")
    rate_headers = {k: v for k, v in r.headers.items() if "ratelimit" in k.lower()}
    print(f"Rate-limit headers: {rate_headers}")
    if r.status_code != 200:
        print(f"Body: {r.text[:500]}")
        return

    data = r.json()
    results = data.get("result") or []
    liga_i = [m for m in results if (m.get("championship") or {}).get("id") == LIGA_I_ID]
    print(f"Total meciuri in zi: {len(results)}  |  Romania Liga I: {len(liga_i)}")

    if not liga_i:
        print("Niciun meci Liga I gasit pe aceasta data.")
        return

    sample = liga_i[0]
    print("\n--- Obiect COMPLET al unui meci din day/full (fara alt apel) ---")
    print(json.dumps(sample, indent=2, ensure_ascii=False))

    top_keys = sorted(sample.get("teamA", {}).keys())
    print(f"\nChei prezente in teamA: {top_keys}")
    print(f"'stats' prezent in teamA: {'stats' in sample.get('teamA', {})}")
    print(f"'lineup' prezent in teamA: {'lineup' in sample.get('teamA', {})}")
    print(f"'manager' prezent in teamA: {'manager' in sample.get('teamA', {})}")
    print(f"'referee' prezent la nivel de meci: {'referee' in sample}")
    print(f"'stadium' prezent la nivel de meci: {'stadium' in sample}")


if __name__ == "__main__":
    main()
