"""
================================================================================
FOOTBALL ORACLE — Poarta Team Profile: cât de aproape e testul de ablație?
================================================================================
Module: scripts/check_team_profile_readiness.py

STRICT read-only. Nu scrie nimic, nicaieri.

DE CE EXISTA (ADR-062): pragul TEAM_PROFILE_TEST_THRESHOLD numara acum
`evaluable_matches` — meciuri cu AMBELE echipe avand >=TEAM_PROFILE_WINDOW
meciuri anterioare cu xG real — nu meciurile jucate in sezon. Diferenta e
mare: la 298 de meciuri "terminate" existau doar 15 evaluabile (5,0%).

Scriptul raporteaza ambele cifre, ca sa se vada progresul REAL spre test,
nu unul iluzoriu. De rulat periodic in saptamanile urmatoare — pragul e
estimat a fi atins spre finalul lui septembrie 2026.

Utilizare:
    python scripts/check_team_profile_readiness.py
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from database.queries import (
        TEAM_PROFILE_EXCLUDED_LEAGUES,
        TEAM_PROFILE_TEST_THRESHOLD,
        TEAM_PROFILE_WINDOW,
        get_finishing_data_readiness,
    )
    from oracle_engine import FootballOracleEngine

    since = FootballOracleEngine._current_season_start_date()

    print(BAR)
    print("  POARTA TEAM PROFILE — progres real spre testul de ablație (ADR-062)")
    print(f"  Sezon de la: {since}  ·  fereastră formulă: {TEAM_PROFILE_WINDOW} meciuri")
    print(f"  Ligi excluse: {', '.join(TEAM_PROFILE_EXCLUDED_LEAGUES)}")
    print(BAR)

    r = get_finishing_data_readiness(since)
    n_eval = r.get("evaluable_matches", 0)
    n_finished = r.get("finished_total", 0)

    print(f"  EVALUABILE (cifra care guvernează poarta) : {n_eval} / {TEAM_PROFILE_TEST_THRESHOLD}")
    pct = (100.0 * n_eval / TEAM_PROFILE_TEST_THRESHOLD) if TEAM_PROFILE_TEST_THRESHOLD else 0.0
    print(f"    progres                                : {pct:.1f}%")
    print(BAR)
    print("  Context informativ (NU guvernează poarta):")
    print(f"    meciuri terminate în sezon             : {n_finished}")
    print(f"    dintre ele, cu șuturi pe poartă        : {r.get('shots_on_target', 0)}")
    print(f"    dintre ele, cu xG real                 : {r.get('xg', 0)}")
    if n_finished:
        print(f"    raport evaluabile/terminate            : {100.0 * n_eval / n_finished:.1f}%")
    print(BAR)

    if n_eval >= TEAM_PROFILE_TEST_THRESHOLD:
        print("  PRAG ATINS — testul de ablație devine posibil (cere aprobare separată).")
    else:
        print(f"  Prag NEatins — mai lipsesc {TEAM_PROFILE_TEST_THRESHOLD - n_eval} meciuri evaluabile.")
    print(BAR)
    print("  Verificare încheiată. ZERO scriere efectuată.")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
