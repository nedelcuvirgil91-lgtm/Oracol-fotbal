"""
================================================================================
FOOTBALL ORACLE — POC: verificare header-e reale de rate-limit
================================================================================
Module: sync/poc_rate_limit_headers_check.py

Discovery, NU integrare — Phase 4 Functional Completion, punctul 1
(eliminarea fail-open din RateLimitManager pentru cei 5 provideri
neconectati). Fiecare provider primeste UN SINGUR apel HTTP REAL, prin
exact acelasi punct de intrare pe care il foloseste azi codul de productie
(`FootballOracleAPI._get()`), cu `return_headers=True` — loghează TOATE
header-ele de raspuns, brute, fara nicio presupunere despre ce nume ar
trebui sa aiba.

football-data.org NU e inclus aici — are deja propriul throttling static
documentat (`sync/sources/football_data.py`, REQUEST_INTERVAL=6.1s),
confirmat separat prin citire de cod, nu necesita verificare live.

Rulare:
  python sync/poc_rate_limit_headers_check.py
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from oracle_api import FootballOracleAPI, THESPORTSDB_URL, WEATHER_URL, ODDS_API_URL, ELO_URL
from key_manager import get_key_manager
from mappings import ODDS_SPORT_KEYS, TSDB_TEAM_IDS


def _print_headers(label: str, headers) -> None:
    print(f"\n=== {label} ===")
    if headers is None:
        print("  (fara raspuns / eroare — vezi log-ul de mai sus)")
        return
    if not headers:
        print("  (raspuns primit, ZERO header-e in obiectul returnat)")
        return
    rate_relevant = []
    for k, v in headers.items():
        marker = ""
        if "rate" in k.lower() or "limit" in k.lower() or "remaining" in k.lower() or "quota" in k.lower():
            marker = "  <-- POSIBIL RELEVANT"
            rate_relevant.append((k, v))
        print(f"  {k}: {v}{marker}")
    if not rate_relevant:
        print("  >>> NICIUN header cu 'rate'/'limit'/'remaining'/'quota' in nume.")


def main() -> None:
    api = FootballOracleAPI()
    km = get_key_manager()

    # 1. TheSportsDB — cheie publica "3" in URL, fara autentificare per-cont.
    tid = TSDB_TEAM_IDS["Romania SuperLiga"]["Petrolul Ploiești"]
    data, headers = api._get(f"{THESPORTSDB_URL}/eventslast.php", params={"id": tid}, return_headers=True)
    print(f"TheSportsDB: raspuns primit={data is not None}")
    _print_headers("TheSportsDB (eventslast.php)", headers)

    # 2. WeatherAPI — [FIX] get_api_key_param(), NU acces direct la
    #    PROVIDERS[...]["keys"][0] (acela e un dict {"key","limit","label"},
    #    nu string-ul cheii — trimis gresit ca param, a produs 401 fals).
    api_key = km.get_api_key_param("weatherapi")
    if api_key:
        data, headers = api._get(
            f"{WEATHER_URL}/current.json",
            params={"key": api_key, "q": "London", "aqi": "no"},
            return_headers=True,
        )
        print(f"\nWeatherAPI: raspuns primit={data is not None}")
        _print_headers("WeatherAPI (current.json)", headers)
    else:
        print("\nWeatherAPI: NICIO cheie configurata (WEATHER_API_KEY lipseste) — sarit.")

    # 3. The Odds API — acelasi fix, get_api_key_param()
    sport_key = ODDS_SPORT_KEYS.get("Premier League")
    odds_key = km.get_api_key_param("oddsapi")
    if sport_key and odds_key:
        data, headers = api._get(
            f"{ODDS_API_URL}/sports/{sport_key}/scores",
            params={"apiKey": odds_key, "daysFrom": 3},
            return_headers=True,
        )
        print(f"\nThe Odds API: raspuns primit={data is not None}")
        _print_headers("The Odds API (scores)", headers)
    else:
        print("\nThe Odds API: sport_key sau cheie lipsa — sarit.")

    # 4. eloratings.net — scraping HTML direct, fara _get() (bypass istoric,
    #    confirmat in oracle_api.py:_fetch_elo_ratings). Verificam totusi
    #    header-ele reale primite, ca sa nu presupunem nimic.
    try:
        r = api._s.get(ELO_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        print(f"\neloratings.net: HTTP {r.status_code}, content-type={r.headers.get('content-type')}")
        _print_headers("eloratings.net (root HTML)", r.headers)
    except Exception as exc:
        print(f"\neloratings.net: eroare — {exc}")


if __name__ == "__main__":
    main()
