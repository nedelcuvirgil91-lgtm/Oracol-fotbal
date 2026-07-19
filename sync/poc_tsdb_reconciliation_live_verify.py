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

# Tokenuri alese DIN dovezi live anterioare, NU ghicite din numele oficial
# LPF — TSDB foloseste ortografii inconsistente pentru acelasi club intre
# apeluri diferite (ex. "Dinamo București" la un apel, "Din. Bucuresti" la
# altul) — substring pe numele oficial complet ("FK Csíkszereda...", "FC
# Rapid") a produs FALS-NEGATIVE dovedite anterior in aceasta investigatie
# (vezi poc_remaining_teams_check.py). Aici: token scurt, distinctiv,
# comun tuturor variantelor deja observate live.
KNOWN_PROBLEMATIC = [
    ("Universitatea Cluj", "Farul", "U Cluj-Farul — singurul meci din eventsnextleague.php"),
    ("Petrolul", "Din", "Petrolul-Dinamo — dovedit STRICT la nivel de echipa"),
    ("Corvinul", "Csíkszereda", "Corvinul-Csíkszereda — dovedit STRICT la nivel de echipa"),
    ("Rapid", "Sepsi", "Rapid-Sepsi — dovedit STRICT la nivel de echipa"),
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

    section("Verificare cele 4 meciuri anterior dovedite problematice (nu tot Etapa 1 — "
            "celelalte 4 meciuri ale rundei sunt deja in trecut fata de data curenta, "
            "filtrate corect, nu un gol de date)")
    found_flags = []
    for home_tok, away_tok, desc in KNOWN_PROBLEMATIC:
        found = any(home_tok in m["home_team"] and away_tok in m["away_team"] for m in results)
        found_flags.append(found)
        print(f"  [{desc}]: {'GASIT' if found else 'LIPSA'}")

    section("VERDICT")
    if all(found_flags):
        print("Toate cele 4 meciuri anterior problematice sunt acum prezente in rezultat.")
        print("Celelalte 4 meciuri din Etapa 1 (Voluntari-Botoșani, FCSB-Argeș, Craiova-UTA, "
              "Oțelul-CFR) nu sunt verificate aici — sunt deja in trecut fata de data curenta, "
              "filtrarea pe data e comportament CORECT (identic cu calea veche), nu un gol.")
    else:
        print("Cel putin unul dintre cele 4 meciuri anterior problematice INCA lipseste — regresie.")


if __name__ == "__main__":
    main()
