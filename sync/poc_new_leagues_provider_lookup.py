"""
================================================================================
FOOTBALL ORACLE — Discovery: ID-uri reale provider pentru Jupiler Pro League/
Ekstraklasa/Scottish Premiership (extinderea LEAGUE_PROVIDERS)
================================================================================
Module: sync/poc_new_leagues_provider_lookup.py

Discovery, NU integrare — nu scrie în mappings.py, nu e importat de niciun
cod de producție. Verifică live, cu dovadă, ce ID real folosește fiecare
provider pentru Belgia/Polonia/Scoția, înainte ca oricare valoare să fie
scrisă în LEAGUE_PROVIDERS (regula explicită din CLAUDE.md — "Regulile
pentru chei API și provideri externi": nicio valoare presupusă/ghicită).

Verifică, în ordine:
  1. The Odds API — GET /v4/sports?all=true, filtrat pe belgium/poland/
     scotland/jupiler/ekstraklasa/premiership — sport_key real sau lipsă.
  2. football-data.org — GET /v4/competitions — listă completă (plan
     gratuit, ~13 competiții) — confirmă dacă Belgia/Polonia/Scoția sunt
     acoperite sau nu (nu se presupune din memorie).
  3. TheSportsDB — search_all_leagues.php?c=<țară>&s=Soccer — cheia publică
     gratuită "3", fără cost de cotă, fără secrete.
  4. API-Football — reutilizează exact `lookup_leagues()` din
     sync/poc_api_football_league_lookup.py (deja testat, deja folosit
     pentru migrarea cheii API-Football) — /leagues?country=<țară>.

Rulare:
    python sync/poc_new_leagues_provider_lookup.py

Rulat prin GitHub Actions (workflow_dispatch — vezi
.github/workflows/poc_new_leagues_provider_lookup.yml), unde există acces
real la Internet, spre deosebire de mediul de dezvoltare curent.
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
from sync.poc_api_football_league_lookup import lookup_leagues as apifootball_lookup_leagues

COUNTRIES = ["Belgium", "Poland", "Scotland"]
ODDS_KEYWORDS = ["belgium", "poland", "scotland", "jupiler", "ekstraklasa", "premiership"]


def _print_header(title: str) -> None:
    print()
    print("=" * 78)
    print(f"  {title}")
    print("=" * 78)


def check_odds_api() -> None:
    _print_header("1. The Odds API — GET /v4/sports?all=true")
    km = get_key_manager()
    if not km.is_available("oddsapi"):
        print("Nicio cheie Odds API activă — verificare abandonată.")
        return
    resp = requests.get(
        "https://api.the-odds-api.com/v4/sports",
        params={"apiKey": km.get_api_key_param("oddsapi"), "all": "true"},
        timeout=15,
    )
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:500]}")
        return
    data = resp.json()
    print(f"{len(data)} sporturi/competiții returnate în total.")
    matches = [
        s for s in data
        if any(kw in (s.get("key", "") + s.get("title", "") + s.get("description", "")).lower()
               for kw in ODDS_KEYWORDS)
    ]
    if not matches:
        print("Niciun rezultat pentru belgium/poland/scotland/jupiler/ekstraklasa/premiership.")
    for s in matches:
        print(f"  key={s.get('key')!r}  title={s.get('title')!r}  "
              f"active={s.get('active')}  has_outrights={s.get('has_outrights')}")


def check_football_data() -> None:
    _print_header("2. football-data.org — GET /v4/competitions")
    km = get_key_manager()
    if not km.is_available("footballdata"):
        print("Nicio cheie football-data.org activă — verificare abandonată.")
        return
    resp = requests.get(
        "https://api.football-data.org/v4/competitions",
        headers=km.get_headers("footballdata"),
        timeout=15,
    )
    km.record_request("footballdata")
    print(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        print(f"Body: {resp.text[:500]}")
        return
    data = resp.json()
    comps = data.get("competitions", [])
    print(f"{len(comps)} competiții disponibile pe planul curent:")
    for c in comps:
        area = (c.get("area") or {}).get("name")
        print(f"  code={c.get('code')!r}  name={c.get('name')!r}  area={area!r}")
    hit = [c for c in comps if (c.get("area") or {}).get("name") in COUNTRIES]
    print()
    if hit:
        for c in hit:
            print(f"  GĂSIT: {c}")
    else:
        print("Belgia/Polonia/Scoția — NU apar în lista de competiții disponibilă.")


def check_tsdb() -> None:
    _print_header("3. TheSportsDB — search_all_leagues.php (cheie publică '3')")
    base = "https://www.thesportsdb.com/api/v1/json/3"
    for country in COUNTRIES:
        print(f"\n  --- {country} ---")
        try:
            resp = requests.get(f"{base}/search_all_leagues.php",
                                 params={"c": country, "s": "Soccer"}, timeout=15)
        except Exception as exc:
            print(f"  EROARE: {exc}")
            continue
        print(f"  HTTP {resp.status_code}  {resp.url}")
        if resp.status_code != 200:
            continue
        data = resp.json()
        leagues = data.get("countries") or data.get("countrys") or []
        if not leagues:
            print("  (niciun rezultat)")
        for lg in leagues:
            print(f"    id={lg.get('idLeague')}  name={lg.get('strLeague')!r}")


def check_api_football() -> None:
    _print_header("4. API-Football — GET /leagues?country=<țară> (reutilizează scriptul existent)")
    for country in COUNTRIES:
        print(f"\n  --- {country} ---")
        apifootball_lookup_leagues(country)


def main() -> None:
    check_odds_api()
    check_football_data()
    check_tsdb()
    check_api_football()


if __name__ == "__main__":
    main()
