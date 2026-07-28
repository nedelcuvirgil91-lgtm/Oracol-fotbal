"""
POC izolat, temporar — verifică live, pentru Champions League, dacă
eventsseason.php (TheSportsDB) și/sau get_matches_for_day (Soccer Football
Info) găsesc meciurile de calificare de azi pe care eventsnextleague.php
(calea curentă, singura folosită azi pentru cupele europene) le ratează.

Nu importă key_manager.py/oracle_api.py — folosește clienții deja existenți
direct, fără fallback live către alt provider. Se șterge din cod după
închiderea investigației (dovada rămâne în istoricul rulării GitHub Actions +
commit message), per regula POC-urilor din CLAUDE.md.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

import requests

TODAY = date.today().isoformat()
UCL_TSDB_ID = "4480"
UCL_SFI_CHAMPIONSHIP_ID = "3f2c3ee6eba0dd06"


def _season_string() -> str:
    d = date.today()
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{start + 1}"


def check_tsdb_eventsnextleague() -> list[dict]:
    resp = requests.get(
        "https://www.thesportsdb.com/api/v1/json/3/eventsnextleague.php",
        params={"id": UCL_TSDB_ID}, timeout=15,
    )
    data = resp.json() if resp.ok else {}
    events = data.get("events") or []
    return [
        {"date": e.get("dateEvent"), "home": e.get("strHomeTeam"), "away": e.get("strAwayTeam")}
        for e in events
    ]


def check_tsdb_eventsseason() -> list[dict]:
    season = _season_string()
    resp = requests.get(
        "https://www.thesportsdb.com/api/v1/json/3/eventsseason.php",
        params={"id": UCL_TSDB_ID, "s": season}, timeout=15,
    )
    data = resp.json() if resp.ok else {}
    events = data.get("events") or []
    today_events = [e for e in events if e.get("dateEvent") == TODAY]
    return [
        {"date": e.get("dateEvent"), "home": e.get("strHomeTeam"), "away": e.get("strAwayTeam")}
        for e in today_events
    ]


def check_sfi_matches_for_day() -> list[dict]:
    from key_manager import get_key_manager

    km = get_key_manager()
    headers = km.get_headers("soccerfootballinfo") or {}
    compact = TODAY.replace("-", "")
    resp = requests.get(
        "https://soccer-football-info.p.rapidapi.com/matches/day/full/",
        params={"d": compact}, headers=headers, timeout=20,
    )
    if not resp.ok:
        return [{"error": f"HTTP {resp.status_code}: {resp.text[:300]}"}]
    data = resp.json()
    matches = data.get("result") or []
    ucl = [m for m in matches if str((m.get("championship") or {}).get("id")) == UCL_SFI_CHAMPIONSHIP_ID]
    return [
        {
            "status": m.get("status"), "date": m.get("date"),
            "home": (m.get("teamA") or {}).get("name"),
            "away": (m.get("teamB") or {}).get("name"),
        }
        for m in ucl
    ]


if __name__ == "__main__":
    print(f"=== TODAY = {TODAY} ===\n")

    print("--- 1. TSDB eventsnextleague.php (calea CURENTĂ) ---")
    en = check_tsdb_eventsnextleague()
    print(f"Total evenimente viitoare (toate datele): {len(en)}")
    print(json.dumps(en, indent=2, ensure_ascii=False))

    print("\n--- 2. TSDB eventsseason.php, filtrat pe azi ---")
    es = check_tsdb_eventsseason()
    print(f"Meciuri azi ({TODAY}): {len(es)}")
    print(json.dumps(es, indent=2, ensure_ascii=False))

    print("\n--- 3. Soccer Football Info, matches/day/full, filtrat pe UCL ---")
    sfi = check_sfi_matches_for_day()
    print(f"Meciuri UCL azi ({TODAY}): {len(sfi)}")
    print(json.dumps(sfi, indent=2, ensure_ascii=False))
