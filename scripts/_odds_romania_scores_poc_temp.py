"""
POC izolat, temporar, runda 3 — bypass resolver/cache, cauta direct in
matches/day/full pentru 2026-07-25 orice meci cu "craiova" sau "dinamo"
in nume, sa vad numele brute SFI si campurile de scor disponibile.

Se șterge din cod după închiderea investigației.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


if __name__ == "__main__":
    from soccerfootballinfo_client import get_soccerfootballinfo_client

    client = get_soccerfootballinfo_client()

    for date_iso in ("2026-07-24", "2026-07-25", "2026-07-26"):
        payload = client.get_matches_for_day(date_iso)
        matches = (payload or {}).get("result") or []
        print(f"--- {date_iso}: {len(matches)} meciuri globale ---")
        for m in matches:
            ta = (m.get("teamA") or {}).get("name", "")
            tb = (m.get("teamB") or {}).get("name", "")
            if "craiova" in ta.lower() or "craiova" in tb.lower() or "dinamo" in ta.lower() or "dinamo" in tb.lower():
                champ = m.get("championship") or {}
                print(f"  GASIT: id={m.get('id')} champ={champ.get('name')!r} "
                      f"{ta!r} vs {tb!r} status={m.get('status')} date={m.get('date')}")
                print(f"  chei nivel1 meci: {sorted(m.keys())}")

    print("\n--- verificare directa match_id + detail, daca s-a gasit ceva mai sus ---")
