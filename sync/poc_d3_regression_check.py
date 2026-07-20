"""
================================================================================
FOOTBALL ORACLE — Verificare LIVE D3 (ADR-035): H2H Database-First
================================================================================
Module: sync/poc_d3_regression_check.py

Discovery/verificare, NU o schimbare de productie. Demonstreaza ca
_build_h2h() citeste PRIMAR din match_history (recalc din date brute,
get_h2h_from_history), global per pereche de cluburi, cu prag minim 3
confruntari, inaintea FreeLF/Odds API.

Pentru fiecare pereche raporteaza: confruntari gasite in DB, bilantul
recalculat (W-D-L din perspectiva gazdei), h2h_modifier si sursa H2H-ului
din H2HRecord-ul construit de _build_h2h().

Rulare:
    python sync/poc_d3_regression_check.py
================================================================================
"""
from __future__ import annotations

import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from mappings import normalize_team_name

# (home, away, league) — perechi cu istoric direct real in match_history.
# Include cazul central + perechi multi-competitie (Champions League + liga
# interna) ca sa demonstreze cautarea GLOBALA (Decizia 1).
CASES = [
    ("Petrolul Ploiești", "Din. Bucuresti", "Romania SuperLiga"),
    ("Rapid București", "Din. Bucuresti", "Romania SuperLiga"),
    ("FCSB", "CFR Cluj", "Romania SuperLiga"),
    ("Real Madrid", "Atletico Madrid", "La Liga"),      # istoric si in Champions League
    ("Bayern Munich", "Bayer Leverkusen", "Bundesliga"),  # idem
    ("Arsenal", "Chelsea", "Premier League"),
]


def section(title: str) -> None:
    print("\n" + "=" * 82)
    print(title)
    print("=" * 82)


def main() -> None:
    from oracle_engine import FootballOracleEngine
    from database.queries import get_h2h_from_history

    engine = FootballOracleEngine()

    section("Verificare D3 — H2H canonic (match_history, recalc din brute, global)")
    rows_out = []
    for home, away, league in CASES:
        home_c = normalize_team_name(home)
        away_c = normalize_team_name(away)
        raw = get_h2h_from_history(home_c, away_c)
        # match fara _freelf_event_id -> forteaza calea DB-first / fallback,
        # exact ca in productie cand FreeLF nu are event pentru meci.
        h = engine._build_h2h(home, away, {"home_team": home, "away_team": away,
                                           "league": league})
        from_db = h.meetings >= 3 and len(raw) >= 3
        rows_out.append((f"{home_c} vs {away_c}", len(raw), h.meetings,
                         f"{h.home_wins}-{h.draws}-{h.away_wins}", h.h2h_modifier, from_db))
        print(f"\n[{league}] {home_c} vs {away_c}")
        print(f"  confruntari brute in DB     = {len(raw)}")
        print(f"  H2HRecord.meetings          = {h.meetings}")
        print(f"  bilant (gazda W-D-L)        = {h.home_wins}-{h.draws}-{h.away_wins}")
        print(f"  goluri medii (gazda–oaspete)= {h.home_goals_avg}–{h.away_goals_avg}")
        print(f"  h2h_modifier                = {h.h2h_modifier}")
        print(f"  ultimele                    = {''.join(h.last_5) or '(gol)'}")
        print(f"  sursa = DB (≥3 confruntari) : {from_db}")

    section("TABEL SINTETIC")
    print(f"{'Pereche':<40}{'DB brute':<10}{'meetings':<10}{'W-D-L':<10}{'mod':<10}{'DB?'}")
    for pair, nraw, nm, wdl, mod, db in rows_out:
        print(f"{pair:<40}{nraw:<10}{nm:<10}{wdl:<10}{str(mod):<10}{'DA' if db else 'nu'}")

    section("VERDICT")
    print("Asteptat: perechile cu ≥3 confruntari in match_history -> H2H din DB,")
    print("recalculat din actual_result/goluri (Decizia 2), global peste toate")
    print("competitiile (Decizia 1). Perechile sub 3 confruntari -> fallback")
    print("provider / empty (Decizia 3), fara aproximare.")


if __name__ == "__main__":
    main()
