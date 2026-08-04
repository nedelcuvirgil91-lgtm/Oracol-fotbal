"""
================================================================================
FOOTBALL ORACLE — POC: verificare live provider_ids pentru 4 ligi noi
================================================================================
Module: sync/poc_new_leagues_verification.py

Discovery, NU integrare — mirror exact al `sync/poc_api_football_league_lookup.py`.
Verifică, cu chei reale (secrets GitHub Actions, indisponibile în sandbox-ul
de dezvoltare), provider_ids candidați pentru 4 ligi cerute explicit de
proprietarul produsului, dar neînregistrate încă în `mappings.py`:
Portugalia (Primeira Liga), Olanda (Eredivisie), Croația (HNL), Turcia
(Süper Lig). Afișează brut ce găsește fiecare provider — nicio valoare nu
e presupusă sau scrisă direct în `mappings.py` din acest script.

Nu scrie în match_history, nu atinge mappings.py, nu e importat de
oracle_engine.py. Rulat o singură dată, prin workflow_dispatch (vezi
.github/workflows/poc_new_leagues_verification.yml) — șters din cod după
ce rezultatele sunt transcrise, cu citare (dovada rămâne în istoricul
rulărilor GitHub Actions + CHANGELOG, exact tiparul deja stabilit pentru
MLS/Conference League/Romania SuperLiga în mappings.py).

Rulare:
  python sync/poc_new_leagues_verification.py
================================================================================
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import requests

from key_manager import get_key_manager

# Candidați identificați prin cercetare publică (WebSearch, TheSportsDB /
# GitHub docs comunitare) — DE CONFIRMAT aici cu apel real, nu presupuși.
TSDB_CANDIDATES = {
    "Portugal (Primeira Liga)": "4344",
    "Netherlands (Eredivisie)": "4337",
    "Croatia (HNL)": "4629",
    "Turkey (Super Lig)": "4339",
}
ESPN_CANDIDATES = {
    "Portugal (Primeira Liga)": ["por.1"],
    "Netherlands (Eredivisie)": ["ned.1"],
    "Croatia (HNL)": ["cro.1", "hrv.1", "croatia.1"],
    "Turkey (Super Lig)": ["tur.1"],
}
FOOTBALL_DATA_CANDIDATES = {
    "Portugal (Primeira Liga)": "PPL",
    "Netherlands (Eredivisie)": "DED",
}
COUNTRIES_FOR_API_FOOTBALL = ["Portugal", "Netherlands", "Croatia", "Turkey"]
ODDS_SEARCH_TERMS = ["portugal", "netherlands", "croatia", "turkey", "dutch", "eredivisie", "primeira", "super_lig", "superlig", "hnl"]


def _print_header(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def check_tsdb() -> None:
    _print_header("TheSportsDB — lookupleague.php (cheie publică '3', fără autentificare)")
    for label, league_id in TSDB_CANDIDATES.items():
        url = f"https://www.thesportsdb.com/api/v1/json/3/lookupleague.php?id={league_id}"
        try:
            resp = requests.get(url, timeout=15)
            data = resp.json() if resp.status_code == 200 else {}
            leagues = (data or {}).get("leagues") or []
            name = leagues[0].get("strLeague") if leagues else None
            print(f"  {label:32s} id={league_id:6s} HTTP {resp.status_code}  strLeague={name!r}")
        except Exception as exc:
            print(f"  {label:32s} id={league_id:6s} EROARE: {exc}")


def check_espn() -> None:
    _print_header("ESPN site.api.espn.com — scoreboard (public, fără cheie)")
    for label, slugs in ESPN_CANDIDATES.items():
        for slug in slugs:
            url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
            try:
                resp = requests.get(url, timeout=15)
                ok = resp.status_code == 200
                league_name = None
                if ok:
                    data = resp.json()
                    league_name = ((data.get("leagues") or [{}])[0]).get("name")
                print(f"  {label:32s} slug={slug:12s} HTTP {resp.status_code}  leagues[0].name={league_name!r}")
            except Exception as exc:
                print(f"  {label:32s} slug={slug:12s} EROARE: {exc}")


def check_football_data() -> None:
    _print_header("football-data.org — /v4/competitions/{code} (cheie reală)")
    km = get_key_manager()
    if not km.is_available("footballdata"):
        print("  Nicio cheie football-data.org activă — verificare abandonată.")
        return
    headers = km.get_headers("footballdata")
    for label, code in FOOTBALL_DATA_CANDIDATES.items():
        url = f"https://api.football-data.org/v4/competitions/{code}"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            km.record_request("footballdata")
            name = None
            if resp.status_code == 200:
                name = resp.json().get("name")
            print(f"  {label:32s} code={code:6s} HTTP {resp.status_code}  name={name!r}")
        except Exception as exc:
            print(f"  {label:32s} code={code:6s} EROARE: {exc}")

    print("\n  --- /v4/competitions (lista completă, confirmă absența Croația/Turcia) ---")
    try:
        resp = requests.get("https://api.football-data.org/v4/competitions", headers=headers, timeout=15)
        km.record_request("footballdata")
        if resp.status_code == 200:
            comps = resp.json().get("competitions", [])
            names = sorted(f"{c.get('code')}={c.get('name')}" for c in comps)
            for n in names:
                print(f"    {n}")
        else:
            print(f"  HTTP {resp.status_code}: {resp.text[:300]}")
    except Exception as exc:
        print(f"  EROARE: {exc}")


def check_odds_api() -> None:
    _print_header("The Odds API — /v4/sports (listă completă sport_key)")
    km = get_key_manager()
    if not km.is_available("oddsapi"):
        print("  Nicio cheie Odds API activă — verificare abandonată.")
        return
    api_key = km.get_api_key_param("oddsapi")
    try:
        resp = requests.get("https://api.the-odds-api.com/v4/sports", params={"apiKey": api_key, "all": "true"}, timeout=15)
        km.record_request("oddsapi")
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code}: {resp.text[:300]}")
            return
        sports = resp.json()
        matches = [s for s in sports if any(term in s.get("key", "").lower() or term in s.get("title", "").lower() for term in ODDS_SEARCH_TERMS)]
        print(f"  {len(matches)} sport_key(uri) care conțin termenii căutați:")
        for s in matches:
            print(f"    key={s.get('key')!r}  title={s.get('title')!r}  active={s.get('active')}")
    except Exception as exc:
        print(f"  EROARE: {exc}")


def check_api_football() -> None:
    _print_header("API-Football — /leagues?country=<țară>")
    km = get_key_manager()
    if not km.is_available("apifootball"):
        print("  Nicio cheie API-Football activă — verificare abandonată.")
        return
    headers = km.get_headers("apifootball")
    for country in COUNTRIES_FOR_API_FOOTBALL:
        try:
            resp = requests.get("https://v3.football.api-sports.io/leagues", headers=headers, params={"country": country}, timeout=15)
            km.record_request("apifootball")
            print(f"\n  --- country={country} — HTTP {resp.status_code} ---")
            if resp.status_code != 200:
                print(f"    {resp.text[:300]}")
                continue
            results = resp.json().get("response", [])
            for entry in results:
                league = entry.get("league", {})
                if league.get("type") != "League":
                    continue
                seasons = entry.get("seasons", [])
                current = [s for s in seasons if s.get("current")]
                print(f"    league_id={league.get('id')}  name={league.get('name')!r}  "
                      f"sezon_curent={current[0].get('year') if current else None}")
        except Exception as exc:
            print(f"    EROARE: {exc}")


def check_soccerfootballinfo() -> None:
    _print_header("Soccer Football Info (RapidAPI) — matches/day/full pe 14 zile, scanare competiții")
    km = get_key_manager()
    if not km.is_available("soccerfootballinfo"):
        print("  Nicio cheie Soccer Football Info activă — verificare abandonată.")
        return
    headers = km.get_headers("soccerfootballinfo")
    base = "https://soccer-football-info.p.rapidapi.com/matches/day/full/"
    seen: dict[str, tuple[str, str]] = {}  # competition name -> (competition_id, sample_date)
    today = date.today()
    for i in range(14):
        d = (today + timedelta(days=i)).strftime("%Y%m%d")
        try:
            resp = requests.get(base, headers=headers, params={"d": d}, timeout=20)
            km.record_request("soccerfootballinfo")
            if resp.status_code != 200:
                continue
            result = resp.json().get("result", []) or []
            for m in result:
                comp = (m.get("competition") or {})
                comp_name = comp.get("name", "")
                comp_id = comp.get("id") or m.get("competition_id")
                low = comp_name.lower()
                if any(term in low for term in ["portugal", "primeira", "liga portugal", "eredivisie", "netherlands",
                                                  "croatia", "hnl", "turkey", "super lig", "süper"]):
                    seen[comp_name] = (comp_id, d)
        except Exception as exc:
            print(f"  {d}: EROARE {exc}")
    if not seen:
        print("  Nicio competiție relevantă găsită în fereastra de 14 zile scanată.")
    for name, (comp_id, d) in seen.items():
        print(f"  competition_id={comp_id!r}  name={name!r}  (văzut prima dată {d})")


def main() -> None:
    check_tsdb()
    check_espn()
    check_football_data()
    check_odds_api()
    check_api_football()
    check_soccerfootballinfo()
    print("\nGata. Transcrie rezultatele în mappings.py cu citare (run ID), apoi șterge acest script.")


if __name__ == "__main__":
    main()
