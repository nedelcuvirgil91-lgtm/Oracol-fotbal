"""
================================================================================
FOOTBALL ORACLE — CLI: verificare practica SportAPI (sportapi7, RapidAPI)
================================================================================
Module: sync/poc_sportapi_check.py

Discovery, NU integrare. Apeluri HTTP REALE cu cheia deja configurata in
key_manager.py (provider "sportapi") - raspunsuri brute, fara nicio
presupunere. Cota planului Free e 50 cereri/LUNA (confirmat din pricing
oficial rapidapi.com/rapidsportapi/api/sportapi7/pricing) - acest script
face un numar MIC, deliberat, de apeluri, nu un crawl al celor 100 de
endpoint-uri.

Rulare:
  python sync/poc_sportapi_check.py
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
        print(f"    Non-JSON body: {r.text[:400]}")
        return None
    print(f"    body (truncat): {str(data)[:1200]}")
    return data


def main() -> None:
    km = get_key_manager()
    if not km.is_available("sportapi"):
        print("Nicio cheie SportAPI activa in key_manager - abandonat.")
        return

    # 1. Endpoint-ul gasit de utilizator, FARA parametrul date (optional) -
    #    intoarce tot sezonul intr-un singur apel, sau cere/limiteaza la o zi?
    _call(km, "uniquetournament/152/eventsbyuniquetournamentanddate FARA date",
          "api/v1/uniquetournament/152/eventsbyuniquetournamentanddate")

    # 2. Ruta documentata oficial, independenta de #1 - meciuri Romania
    #    (categoria=77) pentru o data reala din sezonul confirmat.
    _call(km, "category/77/scheduled-events (Romania, 2026-07-18)",
          "api/v1/category/77/scheduled-events/2026-07-18")

    # 3. Detaliu meci real, ID din raspunsul deja confirmat de utilizator
    #    (FC Voluntari vs FC Botosani) - verifica schema (season, referee...).
    event_detail = _call(km, "event/16403828 (FC Voluntari vs FC Botosani)",
                          "api/v1/event/16403828")

    # 4. Standings - foloseste season.id real extras din #3, daca exista;
    #    altfel raporteaza onest ca nu s-a putut extrage.
    season_id = None
    if isinstance(event_detail, dict):
        ev = event_detail.get("event") or event_detail
        season = ev.get("season") if isinstance(ev, dict) else None
        if isinstance(season, dict):
            season_id = season.get("id")
    if season_id:
        _call(km, f"unique-tournament/152/season/{season_id}/standings/total",
              f"api/v1/unique-tournament/152/season/{season_id}/standings/total")
    else:
        print("\n[standings] SARIT - niciun season.id gasit in raspunsul /event/{id} "
              "(schema reala difera de presupunere, vezi raspunsul brut de mai sus).")

    # 5. Odds pe eveniment real - confirma daca planul Free are acces (sau
    #    e blocat similar cu API-Football).
    _call(km, "event/16403828/odds/1/all",
          "api/v1/event/16403828/odds/1/all")

    print(f"\n=== TOTAL apeluri reale folosite: {_call_count} (din cota 50/luna) ===")


if __name__ == "__main__":
    main()
