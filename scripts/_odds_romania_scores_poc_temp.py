"""
POC izolat, temporar — verifică live dacă Odds API `/scores` are date pentru
`soccer_romania_1_liga`, folosind exact codul de producție
(FootballOracleAPI.get_recent_completed_matches_raw()), nu un apel brut.

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
    from oracle_api import FootballOracleAPI

    api = FootballOracleAPI()

    print("--- Odds API /scores, soccer_romania_1_liga, days_back=3 (cale de productie) ---")
    romania = api.get_recent_completed_matches_raw("soccer_romania_1_liga", days_back=3)
    print(f"Meciuri intoarse: {len(romania)}")
    print(json.dumps(romania, indent=2, ensure_ascii=False))

    print("\n--- Control: Odds API /scores, soccer_usa_mls, days_back=3 (cunoscut ca functioneaza) ---")
    mls = api.get_recent_completed_matches_raw("soccer_usa_mls", days_back=3)
    print(f"Meciuri intoarse: {len(mls)}")
    print(json.dumps(mls[:3], indent=2, ensure_ascii=False))

    print("\n--- Odds API /scores, soccer_romania_1_liga, days_back=10 (fereastra mai larga) ---")
    romania_wide = api.get_recent_completed_matches_raw("soccer_romania_1_liga", days_back=10)
    print(f"Meciuri intoarse: {len(romania_wide)}")
    print(json.dumps(romania_wide, indent=2, ensure_ascii=False))
