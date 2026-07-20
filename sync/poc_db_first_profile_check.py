"""
================================================================================
FOOTBALL ORACLE — Verificare LIVE ADR-035/D1: profil Database-First
================================================================================
Module: sync/poc_db_first_profile_check.py

Discovery/verificare, NU o schimbare de productie. Criteriul de succes D1
din ADR-035, masurat pe cazul care a declansat ADR-ul (Petrolul-Dinamo):
profilurile trebuie construite din match_history (data_source =
"supabase-history", meciuri reale, forma reala), nu din 1 meci TSDB cu
suturi sintetice.

Rulare:
    python sync/poc_db_first_profile_check.py
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))


def main() -> None:
    from oracle_engine import FootballOracleEngine

    engine = FootballOracleEngine()

    print("=" * 78)
    print("ADR-035/D1 — profiluri Database-First, caz real Petrolul-Dinamo")
    print("=" * 78)

    for team_id, team_name in (("tsdb_134398", "Petrolul Ploiești"),
                               ("tsdb_134121", "Dinamo București")):
        p = engine._build_profile(team_id, team_name, "Romania SuperLiga")
        print(f"\n[{p.team_name}]")
        print(f"  data_source      = {p.data_source}")
        print(f"  matches_analysed = {p.matches_analysed}")
        print(f"  form_results     = {''.join(p.form_results) or '(gol)'}")
        print(f"  avg_goals_for    = {p.avg_goals_for}")
        print(f"  avg_goals_against= {p.avg_goals_against}")
        print(f"  OFF/DEF          = {p.offensive_rating} / {p.defensive_rating}")
        print(f"  data_quality     = {p.data_quality}")

    print("\n" + "=" * 78)
    print("VERDICT D1: succes daca ambele profiluri au data_source=")
    print("'supabase-history' si matches_analysed >= 3 (nu 1 meci TSDB).")
    print("ELO ramane '—' pana la D2 — INTENTIONAT, in afara scope-ului D1.")
    print("=" * 78)


if __name__ == "__main__":
    main()
