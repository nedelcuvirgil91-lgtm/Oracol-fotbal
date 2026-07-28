"""
================================================================================
POC IZOLAT, TEMPORAR — R-Sync-6a (Sprint 3)
================================================================================
Scop STRICT: inspectează payload-ul BRUT al endpoint-ului FreeLF
"football-get-standing-all" pentru UN singur rând de clasament, ca să
confirme (nu presupună) dacă răspunsul real conține vreun câmp de formă
recentă (ex. "form") — bug documentat în freelf_form_adapter.py /
oracle_api.get_freelf_standings(): câmpul nu e niciodată copiat în
dicționarele normalizate, deci get_team_form_freelf() întoarce mereu [].

Nu importă niciun modul de producție care ar fi afectat de rezultat
(freelf_form_adapter.py, oracle_engine.py) — doar oracle_api.py, pentru
cererea HTTP brută deja existentă (_free_lf_get), fără nicio rescriere.
Rulează DOAR manual (workflow_dispatch/push pe fișierul temporar), se
șterge după închiderea investigației — dovada rămâne în istoricul rulării.
================================================================================
"""
from __future__ import annotations

import json
import logging

logging.basicConfig(level=logging.INFO)


def run() -> None:
    from mappings import FREE_LF_LEAGUE_IDS
    from oracle_api import FootballOracleAPI

    api = FootballOracleAPI()

    # Câteva ligi cunoscute, cu șanse mari de clasament populat.
    candidates = ["Premier League", "La Liga", "Romania SuperLiga", "Serie A", "Bundesliga"]
    for league in candidates:
        league_id = FREE_LF_LEAGUE_IDS.get(league)
        if not league_id:
            print(f"[POC R-Sync-6a] {league}: fără league_id FreeLF, sărit")
            continue
        print(f"[POC R-Sync-6a] Interogare RAW pentru {league} (leagueid={league_id})...")
        data = api._free_lf_get("football-get-standing-all", params={"leagueid": league_id})
        if not data:
            print(f"[POC R-Sync-6a] {league}: răspuns gol/None")
            continue
        raw = data.get("standing") or data.get("response") or []
        if not raw:
            print(f"[POC R-Sync-6a] {league}: 'standing'/'response' gol în payload. Chei top-level: {list(data.keys())}")
            continue
        first = raw[0]
        print(f"[POC R-Sync-6a] {league}: {len(raw)} rânduri. Chei primul rând: {sorted(first.keys())}")
        print(f"[POC R-Sync-6a] {league}: primul rând COMPLET (RAW):")
        print(json.dumps(first, indent=2, ensure_ascii=False))
        # Găsit un răspuns real — suficient pentru investigație, oprim aici.
        return

    print("[POC R-Sync-6a] Nicio ligă din candidați nu a produs un răspuns cu date.")


if __name__ == "__main__":
    run()
