"""
================================================================================
FOOTBALL ORACLE v4.0 — Daily Sync Orchestrator
================================================================================
Module: sync/run_daily.py

Punctul de intrare pentru sincronizarea zilnică automată.
Rulat de GitHub Actions la 03:00 UTC în fiecare zi.

Flux de execuție:
  1. Sincronizează meciuri noi (football-data.org + openfootball)
  2. Actualizează feature-urile derivate (formă, H2H, cornere, cartonașe,
     faulturi) pentru meciurile noi — sync.backfill_features.run_backfill(),
     non-destructiv, gating per-coloană (Regula #13). Vezi ADR-014. ELO-ul
     e recalculat aici (ELOTracker, MOV V2_damped — ADR-022), nu mai printr-un
     pas separat — vezi ARCHITECTURE_AUDIT_2026-07-15.md pt eliminarea
     implementării ELO necanonice (sync/calculate_elo.py).
  3. Evaluează experimentele shadow active (shadow_testing.py — vezi
     architecture/ADR-004-continuous-learning.md pt ordinea completă)
  4. Persistă cote de piață (odds_history) — vezi
     docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md (Frozen, ADR-005, ADR-006)
  5. Verifică dacă trebuie reantrenat modelul ML
  6. Afișează raport de sincronizare

Folosire:
  python sync/run_daily.py                # rulare completă
  python sync/run_daily.py --no-features  # fără actualizare feature-uri derivate
  python sync/run_daily.py --no-ml        # fără reantrenare ML
  python sync/run_daily.py --dry-run      # simulare fără scriere în Supabase
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


def _print_features_report(result: dict) -> None:
    print("\n🧩  FEATURE UPDATE")
    _print_separator()
    status = result.get("status")
    if status == "done":
        print(f"  ✅ {result.get('processed', 0)} meciuri actualizate "
              f"({result.get('already_done', 0)} deja complete, "
              f"{result.get('errors', 0)} erori)")
    elif status == "skipped":
        print(f"  ℹ️  {result.get('message', 'Sărit')}")
    else:
        print(f"  ⚠️  {result.get('message', 'Status necunoscut')}")


def run(
    skip_features: bool = False,
    skip_ml:       bool = False,
    dry_run:       bool = False,
) -> None:
    start_total = time.time()
    _print_header()

    if dry_run:
        print("  ⚠️  DRY RUN — nicio scriere în Supabase\n")

    # ── Pasul 0: Rezultate de ieri ────────────────────────────────────────
    print("▶  Pasul 0/6 — Rezultate meciuri de ieri...")

    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from sync.sync_results import sync_yesterday_results
            results_status = sync_yesterday_results()
            updated   = results_status.get("updated", 0)
            not_found = results_status.get("not_found", 0)
            print(f"  ✅ {updated} meciuri actualizate cu scoruri reale")
            if not_found > 0:
                print(f"  ℹ️  {not_found} meciuri negăsite în match_history")
        except Exception as exc:
            logger.error("[DailySync] sync_yesterday_results failed: %s", exc)
            print(f"  ⚠️  Eroare la sync rezultate: {exc}")

    # ── Pasul 1: Sincronizare meciuri ─────────────────────────────────────
    print("▶  Pasul 1/6 — Sincronizare meciuri istorice...")

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

    # ── Pasul 3: Actualizare feature-uri derivate ──────────────────────────
    # [ADAUGAT — ADR-014] Completează implementarea ADR-004 ("Toate
    # feature-urile — ELO, formă, standings — se recalculează incremental
    # după fiecare actualizare de rezultate"): înainte, acest pas rula doar
    # manual (workflow_dispatch pe backfill.yml). run_backfill() e deja
    # non-destructiv (gating per-coloană, Regula #13) și idempotent — sigur
    # de rulat zilnic pe tot dataset-ul, cost marginal pentru rândurile deja
    # complete.
    print("\n▶  Pasul 3/6 — Actualizare feature-uri derivate (formă, H2H, cornere, cartonașe, faulturi)...")

    if skip_features:
        print("  ℹ️  Sărit (--no-features)")
        features_result = {"status": "skipped", "message": "--no-features flag"}
    elif dry_run:
        print("  ℹ️  Sărit (dry run)")
        features_result = {"status": "skipped", "message": "dry run"}
    else:
        try:
            from sync.backfill_features import run_backfill
            features_result = run_backfill(dry_run=False)
        except Exception as exc:
            logger.error("[DailySync] run_backfill failed: %s", exc)
            features_result = {"status": "error", "message": str(exc)}

    _print_features_report(features_result)

    # ── Pasul 4: Evaluare experimente shadow ──────────────────────────────
    # [ADAUGAT] Vezi architecture/ADR-004-continuous-learning.md — ordinea
    # corectă e ELO/formă/standings -> shadow evaluation -> ML retraining,
    # NU recalibrare automată per-meci (deja discutat, dezactivat separat).
    print("\n▶  Pasul 4/6 — Evaluare experimente shadow...")

    if dry_run:
        print("  ℹ️  Sărit (dry run)")
        shadow_eval_results = []
    else:
        try:
            import shadow_testing
            shadow_eval_results = shadow_testing.evaluate_all_active_experiments()
            if shadow_eval_results:
                for r in shadow_eval_results:
                    print(f"  ✅ {r['experiment_name']}/{r['experiment_version']}: "
                          f"status={r['status']} (n={r['n_matches_evaluated']})")
            else:
                print("  ℹ️  Niciun experiment activ de evaluat")
            from database.queries import upsert_sync_status
            upsert_sync_status(
                source="experiment_evaluation",
                last_sync=datetime.now(timezone.utc).isoformat(),
                matches_added=0, matches_updated=len(shadow_eval_results),
                status="ok",
                notes=f"{len(shadow_eval_results)} experimente evaluate",
            )
        except Exception as exc:
            logger.error("[DailySync] evaluate_all_active_experiments failed: %s", exc)
            shadow_eval_results = []
            try:
                from database.queries import upsert_sync_status
                upsert_sync_status(
                    source="experiment_evaluation",
                    last_sync=datetime.now(timezone.utc).isoformat(),
                    matches_added=0, matches_updated=0,
                    status="error", notes=str(exc),
                )
            except Exception:
                pass

    # ── Pasul 5: Persistare cote de piață (odds_history) ──────────────────
    # [ADAUGAT] Conform docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md (Frozen,
    # ADR-005, ADR-006). Domain service independent - vezi services/.
    print("\n▶  Pasul 5/6 — Persistare cote de piață (odds_history)...")

    if dry_run:
        print("  ℹ️  Sărit (dry run)")
    else:
        try:
            from oracle_api import FootballOracleAPI
            from services.odds_persistence_service import OddsPersistenceService

            api = FootballOracleAPI()
            matches_with_odds = api.get_matches_for_week(days_ahead=7)
            odds_service = OddsPersistenceService()
            odds_result = odds_service.persist_odds_snapshot(matches_with_odds)

            print(f"  ✅ {odds_result.attempted} meciuri verificate, {odds_result.written} scrieri efective")
            print(f"     ({odds_result.skipped_ineligible} kickoff trecut, "
                  f"{odds_result.skipped_invalid} date invalide, "
                  f"{odds_result.skipped_no_odds} fără cote, "
                  f"{len(odds_result.errors)} erori)")

            from database.queries import upsert_sync_status
            upsert_sync_status(
                source="odds_persistence",
                last_sync=datetime.now(timezone.utc).isoformat(),
                matches_added=0, matches_updated=odds_result.written,
                status="ok" if not odds_result.errors else "partial",
                notes=f"{odds_result.written} scrise / {odds_result.attempted} verificate",
            )
        except Exception as exc:
            logger.error("[DailySync] OddsPersistenceService failed: %s", exc)
            try:
                from database.queries import upsert_sync_status
                upsert_sync_status(
                    source="odds_persistence",
                    last_sync=datetime.now(timezone.utc).isoformat(),
                    matches_added=0, matches_updated=0,
                    status="error", notes=str(exc),
                )
            except Exception:
                pass

    # ── Pasul 6: ML retraining ────────────────────────────────────────────
    print("\n▶  Pasul 6/6 — Verificare / reantrenare ML...")

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
        "--no-features", action="store_true",
        help="Sări actualizarea feature-urilor derivate (formă, H2H, cornere, cartonașe, faulturi)"
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
        skip_features = args.no_features,
        skip_ml       = args.no_ml,
        dry_run       = args.dry_run,
    )


if __name__ == "__main__":
    main()
