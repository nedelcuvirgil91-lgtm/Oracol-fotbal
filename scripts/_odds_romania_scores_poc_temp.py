"""
POC izolat, temporar, runda 2 — verifică live dacă Soccer Football Info
`matches/view/full` (deja folosit de match_statistics) conține și scorul
final (nu doar statistici), pentru un meci real, deja verificat
(Dinamo București 5-1 Universitatea Craiova, 2026-07-25).

Se șterge din cod după închiderea investigației (dovada rămâne în
istoricul rulării GitHub Actions + commit message).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


if __name__ == "__main__":
    from soccerfootballinfo_event_resolver import get_soccerfootballinfo_event_resolver
    from soccerfootballinfo_client import get_soccerfootballinfo_client

    resolver = get_soccerfootballinfo_event_resolver()
    match_id = resolver.resolve(
        home_team="Din. Bucuresti", away_team="Universitatea Craiova",
        kickoff_date="2026-07-25", league="Romania SuperLiga",
    )
    print(f"match_id rezolvat: {match_id!r}")
    if not match_id:
        print("Nu s-a putut rezolva match_id - nu pot continua verificarea.")
        sys.exit(0)

    client = get_soccerfootballinfo_client()
    detail = client.get_match_detail(match_id)
    if not detail:
        print("get_match_detail a intors gol.")
        sys.exit(0)

    print("--- Chei de nivel 1 in payload-ul detaliat ---")
    print(sorted(detail.keys()))

    print("\n--- Cautare campuri de scor (recursiv, pe chei ce contin 'score'/'goal') ---")
    def _find_score_fields(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{path}.{k}" if path else k
                if "score" in k.lower() or "goal" in k.lower():
                    print(f"  {p} = {v!r}")
                _find_score_fields(v, p)
        elif isinstance(obj, list):
            for i, v in enumerate(obj[:2]):
                _find_score_fields(v, f"{path}[{i}]")

    _find_score_fields(detail)

    print("\n--- teamA/teamB, chei de nivel 1 ---")
    print("teamA:", sorted((detail.get("teamA") or {}).keys()))
    print("teamB:", sorted((detail.get("teamB") or {}).keys()))
