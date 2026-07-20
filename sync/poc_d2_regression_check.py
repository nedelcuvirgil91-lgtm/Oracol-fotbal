"""
================================================================================
FOOTBALL ORACLE — Verificare LIVE D2 (ADR-023 Phase 6 / ADR-035 D2): ELO
canonic din match_history
================================================================================
Module: sync/poc_d2_regression_check.py

Discovery/verificare, NU o schimbare de productie. Demonstreaza ca
get_latest_team_elo() (database/queries.py) e citit PRIMAR in
_build_profile(), inaintea oricarui apel catre oracle_api.get_elo_rating()
(eloratings.net + fallback hardcodat), fara regresie pe ligile deja
functionale.

Pentru fiecare echipa raporteaza: ELO citit direct din DB
(get_latest_team_elo), ELO citit direct din provider (get_elo_rating), si
elo_rating rezultat in profilul construit de _build_profile() — verifica
ca profilul foloseste DB cand exista, provider doar cand DB e gol (Regula
ADR-035: DB > provider).

Rulare:
    python sync/poc_d2_regression_check.py
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from mappings import normalize_team_name

CASES = [
    ("tsdb_0", "Petrolul Ploiești", "Romania SuperLiga"),
    ("tsdb_0", "Dinamo București", "Romania SuperLiga"),
    ("tsdb_0", "Arsenal", "Premier League"),
    ("tsdb_0", "Real Madrid", "La Liga"),
    ("tsdb_0", "Bayern Munich", "Bundesliga"),
    ("tsdb_0", "Paris Saint-Germain", "Champions League"),
    ("tsdb_0", "France", "World Cup 2026"),  # asteptat: fallback provider (nationala)
]


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    from oracle_engine import FootballOracleEngine
    from database.queries import get_latest_team_elo

    engine = FootballOracleEngine()

    section("Verificare D2 — ELO canonic (match_history) vs. provider extern")
    rows = []
    for team_id, team_name, league in CASES:
        canonical = normalize_team_name(team_name)
        db_elo = get_latest_team_elo(canonical)
        provider_elo = engine.api.get_elo_rating(canonical)
        p = engine._build_profile(team_id, team_name, league)

        used_db = db_elo is not None
        expected = db_elo if used_db else provider_elo
        matches_expected = (p.elo_rating == expected)

        rows.append((league, canonical, db_elo, provider_elo, p.elo_rating, used_db, matches_expected))
        print(f"\n[{league}] {canonical}")
        print(f"  ELO din DB (canonic)   = {db_elo}")
        print(f"  ELO din provider       = {provider_elo}")
        print(f"  elo_rating in profil   = {p.elo_rating}")
        print(f"  sursa folosita         = {'DB' if used_db else 'provider (fallback)'}")
        print(f"  conform Database-First = {matches_expected}")

    section("TABEL SINTETIC")
    print(f"{'Liga':<20}{'Echipa':<22}{'DB':<8}{'Provider':<10}{'Profil':<8}{'Sursa':<10}{'OK?'}")
    for league, team, db_elo, prov_elo, prof_elo, used_db, ok in rows:
        print(f"{league:<20}{team:<22}{str(db_elo):<8}{str(prov_elo):<10}{str(prof_elo):<8}"
              f"{'DB' if used_db else 'provider':<10}{'DA' if ok else 'NU'}")

    section("VERDICT")
    all_ok = all(r[-1] for r in rows)
    print(f"Toate profilurile respecta Database-First (DB > provider): {all_ok}")
    print("Asteptat: Petrolul/Dinamo/PL/La Liga/Bundesliga/Champions League -> ELO din DB")
    print("(club-uri cu meciuri terminate in match_history).")
    print("World Cup 2026 (Franta) -> fallback provider (ELO_RATINGS_FALLBACK,")
    print("nationala, fara meciuri de club in match_history) — comportament")
    print("IDENTIC cu pre-D2 pentru acest caz, nu regresie.")


if __name__ == "__main__":
    main()
