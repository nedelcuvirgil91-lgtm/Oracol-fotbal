"""
================================================================================
FOOTBALL ORACLE — Backfill Match Statistics (FreeLF) — Sprint 1, ADR-039
================================================================================
Module: sync/backfill_match_statistics_freelf.py

Backfill istoric, SEPARAT deliberat de sincronizarea zilnică
(`sync/sync_match_statistics.py`) — decizie de politică explicit aprobată
(`DATA_WAREHOUSE_ARCHITECTURE_ETAPA_B_2026-07-27.md §1`: „sincronizare
zilnică pentru meciuri recente; backfill istoric separat, o singură
rulare per extindere de acoperire").

Reutilizează EXACT `MatchStatisticsAdapter` + `FreelfEventResolver` — nu
reimplementă logica de rezoluție/scriere, doar schimbă fereastra de date
(explicită, `--date-from`/`--date-to`, în loc de „ultimele N zile").

[LIMITĂ RECUNOSCUTĂ EXPLICIT, nu ascunsă] FreeLF NU garantează retenție
istorică pentru date vechi (necunoscut, neverificat — Regula #8, nu se
presupune). Acest script raportează onest 0 meciuri rezolvate pentru
intervale unde FreeLF nu (mai) are date, nu tratează asta ca eroare —
exact comportamentul așteptat, nu un defect.

Rulare:
    python -m sync.backfill_match_statistics_freelf --date-from 2025-05-26 --date-to 2025-06-25 --league "Premier League"
================================================================================
"""
from __future__ import annotations

import argparse
import logging

from match_statistics_adapter import MatchStatisticsAdapter

logger = logging.getLogger("FootballOracle.Backfill.MatchStatisticsFreelf")


def run_backfill(date_from: str, date_to: str, league: str | None = None, dry_run: bool = False) -> dict:
    from database.queries import get_finished_matches_missing_stats

    adapter = MatchStatisticsAdapter()
    matches = get_finished_matches_missing_stats(
        date_from=date_from, date_to=date_to, league=league, limit=1000,
    )
    logger.info("[BackfillMatchStatsFreelf] %d meciuri fără statistici în [%s, %s]%s",
                len(matches), date_from, date_to, f" ({league})" if league else "")

    resolved = 0
    unresolved = 0
    written = 0
    errors = 0
    for match in matches:
        try:
            raw = adapter.fetch({
                "home_team": match["home_team"], "away_team": match["away_team"],
                "kickoff_date": match["kickoff_date"], "league": match["league"],
            })
        except Exception as exc:
            logger.error("[BackfillMatchStatsFreelf] fetch eșuat pt %s vs %s (%s): %s",
                          match["home_team"], match["away_team"], match["kickoff_date"], exc)
            errors += 1
            continue
        if raw is None:
            # [ADAUGAT] Numărat EXPLICIT, nu deuds din candidates-resolved —
            # cerință explicită: "nu vreau ca unresolved să fie calculat
            # implicit". FreeLF nu a găsit event_id pentru acest meci (fie
            # nu-l acoperă deloc, fie nu (mai) are date pentru interval).
            unresolved += 1
            continue
        resolved += 1
        records = adapter.validate(adapter.normalize(raw))
        if not records:
            continue
        if dry_run:
            written += len(records)
            continue
        if adapter.persist(records):
            written += len(records)
        else:
            errors += 1

    return {
        "candidates": len(matches), "resolved": resolved,
        "written": written, "unresolved": unresolved, "errors": errors,
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", required=True, help="YYYY-MM-DD")
    parser.add_argument("--date-to", required=True, help="YYYY-MM-DD")
    parser.add_argument("--league", default=None, help="Opțional — restrânge la o singură ligă")
    parser.add_argument("--dry-run", action="store_true", help="Simulare — fără scriere în Supabase")
    args = parser.parse_args()

    result = run_backfill(args.date_from, args.date_to, league=args.league, dry_run=args.dry_run)

    print("═" * 60)
    print(f"  BACKFILL MATCH STATISTICS (FreeLF) — [{args.date_from}, {args.date_to}]"
          f"{' / ' + args.league if args.league else ''} (dry_run={args.dry_run})")
    print("═" * 60)
    print(f"  Candidați (fără statistici azi) : {result['candidates']}")
    print(f"  Rezolvate (event_id găsit)      : {result['resolved']}")
    print(f"  Nerezolvate (event_id negăsit)  : {result['unresolved']}")
    print(f"  Scrise cu succes                : {result['written']}")
    print(f"  Erori                           : {result['errors']}")
    print("═" * 60)
    if result["candidates"] > 0 and result["resolved"] == 0:
        print("  ℹ️  Zero meciuri rezolvate — posibil FreeLF nu (mai) reține date pentru acest interval (necunoscut, neconfirmat).")


if __name__ == "__main__":
    main()
