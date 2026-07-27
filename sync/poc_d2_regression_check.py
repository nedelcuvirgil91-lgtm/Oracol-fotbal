"""
================================================================================
FOOTBALL ORACLE — Verificare LIVE D2 (ADR-023 Phase 6 / ADR-035 D2) +
R-Sync-4 (ADR-039): ELO canonic din match_history, fallback Supabase
pentru naționale
================================================================================
Module: sync/poc_d2_regression_check.py

Discovery/verificare, NU o schimbare de productie. Demonstreaza ca
get_latest_team_elo() (database/queries.py) e citit PRIMAR in
_build_profile(), iar fallback-ul pentru echipele fara meciuri de club
(tipic: nationale) citeste STRICT din Supabase
(get_national_team_elo(), national_team_elo_snapshot) — NU mai exista
niciun apel live catre eloratings.net din Oracle Engine (eliminat R-Sync-4,
ADR-039; vezi si tests/test_oracle_engine_single_profile_construction_
point.py::test_get_elo_rating_never_called_from_oracle_engine, garda AST
care impune asta mecanic).

Pentru fiecare echipa raporteaza: ELO citit direct din DB de club
(get_latest_team_elo), ELO citit din snapshot-ul national persistat
(get_national_team_elo), si elo_rating rezultat in profilul construit de
_build_profile() — verifica ca profilul foloseste DB de club cand exista,
snapshot-ul national doar cand DB e gol (Regula ADR-035: DB > fallback).

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
    ("tsdb_0", "France", "World Cup 2026"),  # asteptat: fallback Supabase (nationala)
]


def section(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def main() -> None:
    from oracle_engine import FootballOracleEngine
    from database.queries import get_latest_team_elo, get_national_team_elo

    engine = FootballOracleEngine()

    section("Verificare D2 + R-Sync-4 — ELO canonic (match_history) vs. snapshot national (Supabase)")
    rows = []
    for team_id, team_name, league in CASES:
        canonical = normalize_team_name(team_name)
        db_elo = get_latest_team_elo(canonical)
        national_row = get_national_team_elo(canonical)
        national_elo = national_row.get("elo_rating") if national_row else None
        p = engine._build_profile(team_id, team_name, league)

        used_db = db_elo is not None
        expected = db_elo if used_db else national_elo
        matches_expected = (p.elo_rating == expected)

        rows.append((league, canonical, db_elo, national_elo, p.elo_rating, used_db, matches_expected))
        print(f"\n[{league}] {canonical}")
        print(f"  ELO din DB de club (canonic)     = {db_elo}")
        print(f"  ELO din snapshot national (Supabase) = {national_elo}")
        print(f"  elo_rating in profil              = {p.elo_rating}")
        print(f"  sursa folosita                    = {'DB club' if used_db else 'snapshot national (fallback)'}")
        print(f"  conform Database-First            = {matches_expected}")

    section("TABEL SINTETIC")
    print(f"{'Liga':<20}{'Echipa':<22}{'DB club':<10}{'Snapshot nat.':<15}{'Profil':<8}{'Sursa':<18}{'OK?'}")
    for league, team, db_elo, nat_elo, prof_elo, used_db, ok in rows:
        print(f"{league:<20}{team:<22}{str(db_elo):<10}{str(nat_elo):<15}{str(prof_elo):<8}"
              f"{'DB club' if used_db else 'snapshot national':<18}{'DA' if ok else 'NU'}")

    section("VERDICT")
    all_ok = all(r[-1] for r in rows)
    print(f"Toate profilurile respecta Database-First (DB club > snapshot national): {all_ok}")
    print("Asteptat: Petrolul/Dinamo/PL/La Liga/Bundesliga/Champions League -> ELO din DB")
    print("(club-uri cu meciuri terminate in match_history).")
    print("World Cup 2026 (Franta) -> fallback snapshot national (Supabase,")
    print("national_team_elo_snapshot, populat de sync/sync_national_team_elo.py,")
    print("fara meciuri de club in match_history) — NICIUN apel live catre")
    print("eloratings.net din Oracle Engine (R-Sync-4, ADR-039). Daca snapshot-ul")
    print("nu a fost inca sincronizat pentru o echipa, national_elo apare None —")
    print("Regula #8: necunoscut, niciodata aproximat, niciodata completat live.")


if __name__ == "__main__":
    main()
