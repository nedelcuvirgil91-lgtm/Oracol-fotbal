"""
================================================================================
FOOTBALL ORACLE — Team Profile (finalizare): probă informativă cupe europene
================================================================================
Module: scripts/team_profile_ablation_probe.py

Tooling de analiză (nu cod de producție — niciun modul din app.py/
oracle_engine.py/sync/*/learning_core/* îl importă). Read-only: nicio
scriere în Supabase, niciun flag de producție atins, nicio decizie luată
automat, nicio schimbare a formulei de finalizare din flashscore_team_dna.
rolling_finishing_and_setpieces() — doar raport descriptiv.

Context: pragul Team Profile (database.queries.TEAM_PROFILE_TEST_THRESHOLD
= 400, agregat pe toate ligile, strict sezonul curent) a fost atins
(2026-08-18). Înainte de orice decizie despre prag (rămâne 400? crește la
600?), proprietarul produsului a ridicat o îngrijorare concretă: cupele
europene (Champions/Europa/Conference League) sunt ~42.5% din cele 400 de
meciuri (170/400, verificat live), iar în august sunt majoritar tururi de
calificare — adversari de forțe foarte diferite, posibil nereprezentativi
pentru eficiența de finalizare "normală" a unei echipe.

Întrebarea la care răspunde acest script: se schimbă semnificativ
goals_per_xg / goals_per_shot_on_target dacă excludem cele 3 cupe europene
din eșantion? Dacă da → pragul de 400 (neagregat pe tip de competiție) e
contaminat, iar decizia (600? filtru pe competiție?) revine proprietarului
produsului. Dacă nu → cupele europene nu distorsionează vizibil rezultatul,
pragul de 400 poate rămâne cum e.

Formula reprodusă aici e IDENTICĂ cu flashscore_team_dna.
rolling_finishing_and_setpieces() (sumă goluri / sumă xG pe perechi aliniate
per meci, nu media rapoartelor) — dar POOLED global (toate echipele, ambele
părți, home+away), nu per echipă, pentru că întrebarea e despre eșantionul
agregat de proiect, nu despre o echipă anume.

Utilizare:
    python scripts/team_profile_ablation_probe.py
================================================================================
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.queries import TEAM_PROFILE_EXCLUDED_LEAGUES  # noqa: E402

# [CORECTAT 2026-08-18] Nu mai e o listă locală — importată din
# database.queries ca să nu diverge de excluderea reală aplicată în
# producție (get_finishing_data_readiness/get_team_recent_advanced_stats).
EU_CUP_LEAGUES = set(TEAM_PROFILE_EXCLUDED_LEAGUES)


def _current_season_start_date() -> str:
    """Aceeași convenție iulie-cutover ca oracle_engine.
    FootballOracleEngine._current_season_start_date() — reimplementată
    local, nu importată (oracle_engine pornește dependințe grele de I/O pe
    care acest script de analiză nu trebuie să le declanșeze)."""
    d = date.today()
    start_year = d.year if d.month >= 7 else d.year - 1
    return date(start_year, 7, 1).isoformat()


def fetch_rows(since_date: str) -> list[dict]:
    """Read-only — SELECT direct pe match_history, sezonul curent, toate
    ligile, meciuri terminate, rânduri nesuprascrise (aceleași filtre ca
    database.queries.get_finishing_data_readiness())."""
    import supabase_client as sb

    client = sb.get_client()
    cols = ("league,actual_home_goals,actual_away_goals,"
            "home_xg_actual,away_xg_actual,"
            "home_shots_on_target,away_shots_on_target,"
            "home_corners,away_corners")
    all_rows: list[dict] = []
    offset = 0
    page_size = 1000
    while True:
        res = (
            client.table("match_history")
            .select(cols)
            .not_.is_("actual_result", "null")
            .is_("superseded_by", "null")
            .gte("kickoff_date", since_date)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        all_rows.extend(rows)
        if len(rows) < page_size:
            break
        offset += page_size
    return all_rows


def _sum_ratio(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    denom = sum(p[1] for p in pairs)
    return sum(p[0] for p in pairs) / denom if denom > 0 else None


def _pooled_finishing(rows: list[dict]) -> dict:
    """Aceeași logică de agregare ca rolling_finishing_and_setpieces()
    (sumă/sumă pe perechi aliniate, nu media rapoartelor), dar POOLED pe
    toate echipele — fiecare meci contribuie DOUĂ observații (partea
    gazdă + partea oaspete)."""
    goals_xg_pairs: list[tuple[float, float]] = []
    goals_sot_pairs: list[tuple[float, float]] = []
    corners: list[float] = []
    for r in rows:
        for side in ("home", "away"):
            g = r.get(f"actual_{side}_goals")
            xg = r.get(f"{side}_xg_actual")
            sot = r.get(f"{side}_shots_on_target")
            cor = r.get(f"{side}_corners")
            if g is not None and xg is not None:
                goals_xg_pairs.append((float(g), float(xg)))
            if g is not None and sot is not None:
                goals_sot_pairs.append((float(g), float(sot)))
            if cor is not None:
                corners.append(float(cor))
    return {
        "n_matches": len(rows),
        "goals_per_xg": _sum_ratio(goals_xg_pairs),
        "goals_per_xg_n": len(goals_xg_pairs),
        "goals_per_shot_on_target": _sum_ratio(goals_sot_pairs),
        "goals_per_sot_n": len(goals_sot_pairs),
        "avg_corners": sum(corners) / len(corners) if corners else None,
        "avg_corners_n": len(corners),
    }


def _fmt(v) -> str:
    return "—" if v is None else f"{v:.3f}"


def _print_block(title: str, stats: dict) -> None:
    print(f"  {title:<28} meciuri={stats['n_matches']:<4} "
          f"goluri/xG={_fmt(stats['goals_per_xg'])} (n={stats['goals_per_xg_n']})  "
          f"goluri/SOT={_fmt(stats['goals_per_shot_on_target'])} (n={stats['goals_per_sot_n']})  "
          f"cornere/meci={_fmt(stats['avg_corners'])} (n={stats['avg_corners_n']})")


def run() -> None:
    since = _current_season_start_date()
    rows = fetch_rows(since)

    print()
    print("=" * 96)
    print("  Football Oracle — Team Profile (finalizare): probă cupe europene, informativ")
    print("=" * 96)
    print(f"  Sezon curent (>= {since}), toate ligile, meciuri terminate: {len(rows)}")
    print("=" * 96)

    if not rows:
        print("\nNiciun meci în sezonul curent — nimic de analizat.")
        return

    eu_rows = [r for r in rows if r.get("league") in EU_CUP_LEAGUES]
    non_eu_rows = [r for r in rows if r.get("league") not in EU_CUP_LEAGUES]

    print(f"\n  Excluse (TEAM_PROFILE_EXCLUDED_LEAGUES — {', '.join(sorted(EU_CUP_LEAGUES))}): "
          f"{len(eu_rows)} ({100 * len(eu_rows) / len(rows):.1f}% din eșantion)")
    print(f"  Ligi domestice (folosite azi de Team Profile): {len(non_eu_rows)}")

    print("\n── Comparație pooled (toate echipele, home+away combinate) ──")
    _print_block("Tot eșantionul", _pooled_finishing(rows))
    _print_block("Ligi domestice (folosite azi)", _pooled_finishing(non_eu_rows))
    _print_block("Excluse (cupe UEFA + WC2026)", _pooled_finishing(eu_rows))

    print("\n── Per competiție (context, toate) ──")
    leagues = sorted(
        {r.get("league") for r in rows if r.get("league")},
        key=lambda lg: -sum(1 for r in rows if r.get("league") == lg),
    )
    for lg in leagues:
        lg_rows = [r for r in rows if r.get("league") == lg]
        _print_block(lg, _pooled_finishing(lg_rows))

    print()
    print("=" * 96)
    print("  NOTĂ: raport strict informativ. Nu schimbă TEAM_PROFILE_TEST_THRESHOLD, nu")
    print("  modifică formula rolling_finishing_and_setpieces(), nu scrie nimic în Supabase,")
    print("  nu afectează Oracle/ML/Blend. Decizia (prag 400 vs. 600, filtru pe competiție,")
    print("  sau fără schimbare) rămâne a proprietarului produsului.")
    print("=" * 96)
    print()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
