"""
================================================================================
FOOTBALL ORACLE v4.0 — Daily Sync Orchestrator
================================================================================
Module: sync/run_daily.py

Punctul de intrare pentru sincronizarea zilnică automată.
Rulat de GitHub Actions la 03:00 UTC în fiecare zi.

Flux de execuție:
  1. Sincronizează meciuri noi (football-data.org + openfootball)
  2. Calculează ELO intern din rezultatele noi
  3. Verifică dacă trebuie reantrenat modelul ML
  4. Afișează raport de sincronizare

Folosire:
  python sync/run_daily.py              # rulare completă
  python sync/run_daily.py --no-elo     # fără recalculare ELO
  python sync/run_daily.py --no-ml      # fără reantrenare ML
  python sync/run_daily.py --dry-run    # simulare fără scriere în Supabase
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Root în path
root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# Configurare logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.DailySync")


def _print_separator(char: str = "─", width: int = 60) -> None:
    print(char * width)


def _print_header() -> None:
    _print_separator("═")
    print("  ⚽  FOOTBALL ORACLE — Daily Sync")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    _print_separator("═")
    print()


def _print_sync_report(reports: list) -> None:
    """Afișează raportul de sincronizare meciuri."""
    print("\n📥  HISTORY SYNC")
    _print_separator()

    total_fetched = 0
    total_new     = 0
    total_skipped = 0
    all_leagues: set[str] = set()

    for r in reports:
        status_icon = "✅" if r.errors == 0 else "⚠️"
        print(f"  {status_icon} {r.source:<20} "
              f"+{r.matches_new} meciuri noi  "
              f"({r.matches_skipped} duplicate  "
              f"{r.duration_sec}s)")
        total_fetched += r.matches_fetched
        total_new     += r.matches_new
        total_skipped += r.matches_skipped
        all_leagues.update(r.leagues_synced)

    print()
    print(f"  Total descărcat : {total_fetched}")
    print(f"  Meciuri noi     : {total_new}")
    print(f"  Duplicate       : {total_skipped}")
    print(f"  Competiții      : {len(all_leagues)}")


def _print_elo_report(teams_updated: int, duration: float) -> None:
    print("\n📊  ELO RATINGS")
    _print_separator()
    print(f"  ✅ {teams_updated} echipe actualizate  ({duration}s)")


def _print_ml_report(status: dict) -> None:
    print("\n🤖  ML MODEL")
    _print_separator()
    if status.get("status") == "trained":
        acc = status.get("accuracy")
        acc_str = f"{acc*100:.1f}%" if acc else "N/A"
        print(f"  ✅ Model reantrenat")
        print(f"     Samples : {status.get('samples_used', 0)}")
        print(f"     Accuracy: {acc_str}")
    elif status.get("status") == "insufficient_data":
        print(f"  ℹ️  Insuficiente date ({status.get('samples_used', 0)} / 30 necesare)")
    elif status.get("status") == "skipped":
        print(f"  ℹ️  Sărit — mai puțin de 20 meciuri noi față de ultimul training")
    else:
        print(f"  ⚠️  {status.get('message', 'Status necunoscut')}")


def run(
    skip_elo: bool = False,
    skip_ml:  bool = False,
    dry_run:  bool = False,
) -> None:
    start_total = time.time()
    _print_header()

    if dry_run:
        print("  ⚠️  DRY RUN — nicio scriere în Supabase\n")

    # ── Pasul 1: Sincronizare meciuri ─────────────────────────────────────
    print("▶  Pasul 1/3 — Sincronizare meciuri istorice...")

    if not dry_run:
        from sync.sync_matches import sync_all
        sync_reports = sync_all(
            use_football_data = True,
            use_openfootball  = True,
        )
    else:
        # Simulare dry run
        from sync.sync_matches import SyncReport
        sync_reports = [
            SyncReport(source="football_data [DRY RUN]",
                       matches_fetched=100, matches_new=0,
                       matches_skipped=100, duration_sec=0.1),
            SyncReport(source="openfootball [DRY RUN]",
                       matches_fetched=50, matches_new=0,
                       matches_skipped=50, duration_sec=0.1),
        ]

    _print_sync_report(sync_reports)

    # ── Pasul 2: Recalculare ELO ──────────────────────────────────────────
    print("\n▶  Pasul 2/3 — Recalculare ELO...")

    if skip_elo:
        print("  ℹ️  ELO sărit (--no-elo)")
        elo_teams   = 0
        elo_duration = 0.0
    elif dry_run:
        elo_teams    = 0
        elo_duration = 0.0
        print("  ℹ️  ELO sărit (dry run)")
    else:
        try:
            elo_start = time.time()
            from sync.calculate_elo import recalculate_all_elo
            elo_teams = recalculate_all_elo()
            elo_duration = round(time.time() - elo_start, 1)
        except Exception as exc:
            logger.error("[DailySync] ELO recalculation failed: %s", exc)
            elo_teams    = 0
            elo_duration = 0.0

    _print_elo_report(elo_teams, elo_duration)

    # ── Pasul 3: ML retraining ────────────────────────────────────────────
    print("\n▶  Pasul 3/3 — Verificare / reantrenare ML...")

    if skip_ml:
        ml_status = {"status": "skipped", "message": "--no-ml flag"}
    elif dry_run:
        ml_status = {"status": "skipped", "message": "dry run"}
    else:
        try:
            from database.queries import should_retrain_ml, get_ml_sample_count
            sample_count = get_ml_sample_count()

            if should_retrain_ml(min_new_matches=20):
                # Antrenăm direct din ml_predictor — fără să încărcăm tot engine-ul
                from ml_predictor import MLPredictorEngine
                ml_engine = MLPredictorEngine()
                result    = ml_engine.train()
                ml_status = {
                    "status":       result.status,
                    "samples_used": result.samples_used,
                    "accuracy":     result.accuracy,
                    "message":      result.message,
                }
            else:
                ml_status = {
                    "status":       "skipped",
                    "samples_used": sample_count,
                    "message":      "Mai puțin de 20 meciuri noi față de ultimul training",
                }
        except Exception as exc:
            logger.error("[DailySync] ML retraining failed: %s", exc)
            ml_status = {"status": "error", "message": str(exc)}

    _print_ml_report(ml_status)

    # ── Raport final ──────────────────────────────────────────────────────
    total_duration = round(time.time() - start_total, 1)
    print()
    _print_separator("═")
    total_new = sum(r.matches_new for r in sync_reports)
    print(f"  ✅ Sincronizare completă în {total_duration}s")
    print(f"     +{total_new} meciuri noi în Supabase")
    _print_separator("═")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Football Oracle — Daily Sync"
    )
    parser.add_argument(
        "--no-elo", action="store_true",
        help="Sări recalcularea ELO"
    )
    parser.add_argument(
        "--no-ml", action="store_true",
        help="Sări reantrenarea ML"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulare fără scriere în Supabase"
    )
    args = parser.parse_args()

    run(
        skip_elo = args.no_elo,
        skip_ml  = args.no_ml,
        dry_run  = args.dry_run,
    )


if __name__ == "__main__":
    main()
