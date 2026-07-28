"""
POC izolat — declanșează o rulare reală get_matches_for_week() ca să
producă prima evaluare shadow R-Sync-7b (equivalence_evaluations).

Nu e integrare — reproduce exact apelul din app.py (COMPETITIONS_META),
NU introduce cod nou de producție. Se șterge după ce prima evaluare
e confirmată în Supabase.
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from oracle_api import FootballOracleAPI

COMPETITIONS = [
    "World Cup 2026", "Champions League", "Premier League", "La Liga",
    "Serie A", "Bundesliga", "Ligue 1", "Europa League", "Romania SuperLiga",
]


def main() -> None:
    api = FootballOracleAPI()
    matches = api.get_matches_for_week(days_ahead=7, competitions=COMPETITIONS)
    print(f"get_matches_for_week() -> {len(matches)} meciuri live")
    for m in matches[:5]:
        print(f"  {m.get('home_team')} vs {m.get('away_team')} ({m.get('kickoff_date')}) source={m.get('source')}")


if __name__ == "__main__":
    main()
