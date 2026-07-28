"""
POC izolat, temporar — runda 2: verifică live dacă Soccer Football Info
etichetează calificările UCL sub un championship_id SEPARAT de turneul
principal, și ce întoarce ESPN direct (folosind codul de producție
_fetch_matches_espn(), nu un apel brut) pentru Champions League azi.

Se șterge din cod după închiderea investigației (dovada rămâne în
istoricul rulării GitHub Actions + commit message).
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


def sfi_all_championships_today() -> None:
    from key_manager import get_key_manager

    km = get_key_manager()
    headers = km.get_headers("soccerfootballinfo") or {}
    compact = TODAY.replace("-", "")
    resp = requests.get(
        "https://soccer-football-info.p.rapidapi.com/matches/day/full/",
        params={"d": compact}, headers=headers, timeout=20,
    )
    if not resp.ok:
        print(f"SFI HTTP {resp.status_code}: {resp.text[:300]}")
        return
    data = resp.json()
    matches = data.get("result") or []
    print(f"Total meciuri globale SFI azi: {len(matches)}")

    # Caută orice championship al cărui nume conține "champions" / "uefa"
    seen: dict[str, str] = {}
    for m in matches:
        champ = m.get("championship") or {}
        cid, cname = str(champ.get("id")), champ.get("name", "")
        if cid not in seen:
            seen[cid] = cname
        if "champion" in (cname or "").lower() or "uefa" in (cname or "").lower():
            print(f"  MATCH candidat: champ_id={cid} champ_name={cname!r} "
                  f"{(m.get('teamA') or {}).get('name')} vs {(m.get('teamB') or {}).get('name')} "
                  f"status={m.get('status')}")

    # Caută explicit echipele cunoscute din UI (Lincoln Red Imps / Mjällby)
    for m in matches:
        ta = (m.get("teamA") or {}).get("name", "")
        tb = (m.get("teamB") or {}).get("name", "")
        if "lincoln" in ta.lower() or "lincoln" in tb.lower() or "mjall" in ta.lower() or "mjall" in tb.lower():
            champ = m.get("championship") or {}
            print(f"  GASIT prin nume echipa: champ_id={champ.get('id')} champ_name={champ.get('name')!r} "
                  f"{ta} vs {tb} status={m.get('status')}")


def espn_raw_via_production_code() -> None:
    from oracle_api import FootballOracleAPI

    api = FootballOracleAPI()
    raw_events = api._fetch_matches_espn("Champions League", TODAY)
    print(f"_fetch_matches_espn('Champions League', {TODAY!r}) -> {len(raw_events)} meciuri (dupa filtrare stare pre/in)")
    print(json.dumps(raw_events, indent=2, ensure_ascii=False))


def espn_raw_unfiltered() -> None:
    """Bypasseaza filtrul stare pre/in din _fetch_matches_espn, ca sa vedem
    daca ESPN chiar intoarce toate cele 6 meciuri dar cu o stare neasteptata."""
    from mappings import ESPN_LEAGUE_SLUGS

    slug = ESPN_LEAGUE_SLUGS.get("Champions League")
    resp = requests.get(
        f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard",
        headers={"User-Agent": "Mozilla/5.0"},
        params={"dates": TODAY.replace("-", "")},
        timeout=15,
    )
    if not resp.ok:
        print(f"ESPN HTTP {resp.status_code}")
        return
    data = resp.json()
    events = data.get("events", [])
    print(f"ESPN RAW (fara filtrare stare) -> {len(events)} evenimente")
    for ev in events:
        comps = ev.get("competitions", [{}])[0]
        competitors = comps.get("competitors", [])
        names = [c.get("team", {}).get("displayName", "?") for c in competitors]
        state = (ev.get("status") or {}).get("type", {}).get("state", "?")
        print(f"  {ev.get('date')} | {names} | state={state}")


if __name__ == "__main__":
    print(f"=== TODAY = {TODAY} ===\n")

    print("--- A. SFI: toate championship-urile din ziua de azi (cauta UCL sub alt id) ---")
    sfi_all_championships_today()

    print("\n--- B. ESPN, cod de productie (_fetch_matches_espn, cu filtrare stare) ---")
    espn_raw_via_production_code()

    print("\n--- C. ESPN, raspuns brut, FARA filtrare stare (verifica daca gate-ul pre/in scapa meciuri) ---")
    espn_raw_unfiltered()
