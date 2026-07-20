"""
================================================================================
FOOTBALL ORACLE — Verificare LIVE regresie D1 (ADR-035) pe alte ligi
================================================================================
Module: sync/poc_d1_regression_check.py

Discovery/verificare, NU o schimbare de productie. Cerut explicit la review
PR #30: demonstreaza ca noua cascada (Level DB, primul in _build_profile)
NU introduce regresii pe ligile deja functionale — Premier League, La Liga,
Bundesliga, Champions League, World Cup 2026.

Pentru fiecare echipa raporteaza: sursa profilului (data_source),
numarul de meciuri folosite (matches_analysed) si daca s-a cazut pe
fallback (provider extern / national-stats-hardcoded / neutral-defaults).

Rulare:
    python sync/poc_d1_regression_check.py
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# (team_id fictiv - nu conteaza pentru Level DB, doar pentru fallback-urile
#  care il folosesc ca prefix; folosim "tsdb_0" ca sa nu activeze niciun
#  cod special legat de alt provider), team_name, league
CASES = [
    ("tsdb_0", "Arsenal", "Premier League"),
    ("tsdb_0", "Real Madrid", "La Liga"),
    ("tsdb_0", "Bayern Munich", "Bundesliga"),
    ("tsdb_0", "Paris Saint-Germain", "Champions League"),
    ("tsdb_0", "France", "World Cup 2026"),  # asteptat: fallback national-stats
]


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    from oracle_engine import FootballOracleEngine

    engine = FootballOracleEngine()

    section("Verificare regresie D1 — 5 ligi, echipe reprezentative")
    rows = []
    for team_id, team_name, league in CASES:
        p = engine._build_profile(team_id, team_name, league)
        fallback = p.data_source != "supabase-history"
        rows.append((league, p.team_name, p.data_source, p.matches_analysed, fallback))
        print(f"\n[{league}] {p.team_name}")
        print(f"  data_source      = {p.data_source}")
        print(f"  matches_analysed = {p.matches_analysed}")
        print(f"  form_results     = {''.join(p.form_results) or '(gol)'}")
        print(f"  fallback folosit = {fallback}")

    section("TABEL SINTETIC")
    print(f"{'Liga':<20}{'Echipa':<22}{'Sursa':<20}{'Meciuri':<10}{'Fallback?'}")
    for league, team, src, n, fb in rows:
        print(f"{league:<20}{team:<22}{src:<20}{n:<10}{'DA' if fb else 'nu'}")

    section("VERDICT")
    print("Asteptat: PL/La Liga/Bundesliga/Champions League -> supabase-history,")
    print("cu matches_analysed >= 3 (istoric bogat in match_history).")
    print("World Cup 2026 -> fallback (national-stats-hardcoded), pentru ca")
    print("match_history are 0 randuri cu actual_result populat pentru turneu")
    print("(verificat separat, SQL) — comportament IDENTIC cu pre-D1, nu regresie.")


if __name__ == "__main__":
    main()
