"""
================================================================================
FOOTBALL ORACLE — Verificare LIVE a reconcilierii TSDB (Fir B, post-fix)
================================================================================
Module: sync/poc_tsdb_reconciliation_live_verify.py

Discovery, NU o schimbare de productie — ruleaza codul de productie deja
patch-uit (_fetch_matches_tsdb din oracle_api.py) cu apeluri REALE catre
TheSportsDB, pentru Romania SuperLiga, si compara rezultatul cu cele 8
meciuri oficiale LPF Etapa 1 — dovada finala, live, ca reconcilierea
(eventsseason.php + supliment per echipa) rezolva golul demonstrat anterior.

Rulare:
    python sync/poc_tsdb_reconciliation_live_verify.py
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

OFFICIAL_ETAPA_1 = [
    ("FC Voluntari", "FC Botoșani"),
    ("FCSB", "FC Argeș"),
    ("Oțelul Galați", "CFR 1907 Cluj"),
    ("Universitatea Craiova", "UTA Arad"),
    ("Universitatea Cluj", "Farul Constanța"),
    ("Petrolul Ploiești", "Dinamo"),
    ("Corvinul Hunedoara", "FK Csíkszereda Miercurea Ciuc"),
    ("FC Rapid", "Sepsi OSK Sf. Gheorghe"),
]


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    from oracle_api import FootballOracleAPI

    api = FootballOracleAPI()

    section("_fetch_matches_tsdb('4691', 'Romania SuperLiga') — apel REAL, cod de productie patch-uit")
    results = api._fetch_matches_tsdb("4691", "Romania SuperLiga")
    print(f"Total meciuri intoarse: {len(results)}")
    for m in results:
        print(f"  {m['home_team']} vs {m['away_team']}  kickoff_date={m['kickoff_date']}  "
              f"kickoff_utc={m['kickoff_utc']}  source={m['source']}")

    section("Completitudine fata de calendarul oficial LPF Etapa 1 (8 meciuri)")
    found_count = 0
    for home, away in OFFICIAL_ETAPA_1:
        home_key = home.split()[0]
        away_key = away.split()[0]
        found = any(
            (home_key in m["home_team"] and away_key in m["away_team"])
            or (home_key in m["away_team"] and away_key in m["home_team"])
            for m in results
        )
        found_count += int(found)
        print(f"  {home} vs {away}: {'GASIT' if found else 'LIPSA'}")

    print(f"\nCompletitudine dupa reconciliere: {found_count}/8")

    section("VERDICT")
    if found_count == 8:
        print("8/8 — reconcilierea rezolva complet golul demonstrat in investigatia anterioara.")
    else:
        print(f"{found_count}/8 — inca exista un gol, necesita investigatie suplimentara "
              f"(posibil: TSDB nu are inca datele pt meciurile lipsa, independent de cod).")


if __name__ == "__main__":
    main()
