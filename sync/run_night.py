"""
================================================================================
FOOTBALL ORACLE — Night Sync (Faza 2, §7)
================================================================================
Module: sync/run_night.py

Orchestrator de noapte, decuplat de `daily.yml`/`sync/run_daily.py`
(Tier 1 API providers) — secvențiază fluxul complet cerut explicit:

    Discovery → API Providers → Flashscore → Validation → Canonical
    Database → Team DNA → Oracle Data Layer → Diagnostics → Cleanup →
    Backup → Final Report

Plus o etapă SUPLIMENTARĂ, în afara acestor 11 nume — Continuous Learning
(Learning Core, ADR-030), PRE-EXISTENTĂ, complet independentă de
Flashscore/Team DNA/Faza 2/Faza 3 (Champion/Challenger, nu recalibrare
Predictor) — păstrată aici doar ca să nu se piardă automatizarea ei după
consolidarea schedulerului (vezi `.github/workflows/continuous_learning.yml`,
cron dezactivat acolo). Gatată intern de `learning_core_enabled`, implicit
OPRIT — no-op sigur azi.

Fiecare etapă rulează IZOLAT (o excepție într-o etapă nu oprește restul
pipeline-ului — la fel ca `sync/run_daily.py`, care deja tratează fiecare
Pas independent). Idempotent: fiecare etapă individuală apelată aici
(`sync.run_daily.run`, `providers.flashscore.run_foundation_data_layer.run`
cu Delta Sync, `learning_core.run_continuous_learning.main`,
`providers.flashscore.season_cleanup.build_cleanup_dry_run_report`,
`providers.flashscore.backup.run_backup`) e deja idempotentă independent
— rularea secvențială, repetată, nu produce duplicate (Backup produce un
fișier nou per rulare, niciodată suprascriere).

Team DNA rulează LIVE, la fiecare predicție din Oracle Engine — nu are
(și nu are nevoie de) un pas batch separat; raportat explicit ca atare,
niciodată simulat ca un pas care "rulează" ceva. Oracle Data Layer e
DOAR infrastructură/context (home/away_flashscore_dna pe
MatchPrediction) — nicio recalibrare, nicio schimbare de blending/
confidence (Faza 3, neînceput). Backup e REAL (`providers/flashscore/
backup.py`, export JSON read-only) — Delete/Integrity Check rămân
neimplementate (ADR-044 Addendum A6, `delete_executed` rămâne mereu
False în Season Cleanup).
================================================================================
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.NightSync")


def _run_stage(name: str, fn: Callable[[], Any], report: list[dict]) -> None:
    print(f"\n▶  {name}")
    t0 = time.time()
    try:
        detail = fn()
        report.append({
            "stage": name, "ok": True,
            "duration_s": round(time.time() - t0, 1), "detail": detail,
        })
        print(f"   ✅ OK ({report[-1]['duration_s']}s)")
    except Exception as exc:
        logger.error("[NightSync] Etapa %s a eșuat: %s", name, exc)
        report.append({
            "stage": name, "ok": False,
            "duration_s": round(time.time() - t0, 1), "error": str(exc),
        })
        print(f"   ❌ EȘUAT: {exc}")


def _stage_api_providers() -> str:
    """1. Discovery + Provideri API + Validation + Canonical Database —
    întreg `sync/run_daily.py` (Pașii 0-6, cadență Tier 1, deja idempotent)."""
    from sync.run_daily import run as run_daily_sync
    run_daily_sync()
    return "sync/run_daily.py rulat complet (Pașii 0-6)"


def _stage_flashscore() -> str:
    """2. Flashscore — Discovery + fetch/normalize/validate/persist, cu
    Delta Sync (sare meciurile deja persistate canonic, Faza 2 §7)."""
    from providers.flashscore.run_foundation_data_layer import run as run_flashscore
    exit_code = run_flashscore(leagues=None, limit_per_league=None, dry_run=False)
    return f"exit_code={exit_code}"


def _stage_team_dna() -> str:
    """6. Team DNA (flashscore_team_dna.py) — rulează LIVE, per predicție,
    în Oracle Engine (_build_flashscore_dna, apelat din evaluate_match())
    — niciun pas batch de precalcul există azi, deci nimic de rulat aici.
    Documentat explicit, nu simulat."""
    return "calculat live per predicție (Oracle Engine) — fără pas batch de precalcul"


def _stage_oracle_data_layer() -> str:
    """7. Oracle Data Layer — infrastructura/contextul (home/away_
    flashscore_dna pe MatchPrediction) există deja, populată la fiecare
    evaluate_match(); NU există (și nu trebuie să existe, per cerința
    explicită "doar infrastructură și context") un pas batch de
    precalcul/recalibrare aici — asta rămâne Faza 3."""
    return "context disponibil live în Oracle Engine (home/away_flashscore_dna) — fără recalibrare, fără pas batch"


def _stage_ml_refresh_pre_existing() -> str:
    """Etapă SUPLIMENTARĂ, în afara celor 11 numite explicit — Continuous
    Learning (Learning Core, ADR-030) PRE-EXISTENTĂ, independentă de
    Flashscore/Faza 2/Faza 3 (Champion/Challenger, nu recalibrare Team
    DNA/Predictor). Rulată aici DOAR ca să nu se piardă automatizarea ei
    (cron-ul propriu, continuous_learning.yml, a fost dezactivat la
    consolidarea schedulerului — vezi acel fișier) — gatată intern de
    `learning_core_enabled`, implicit OPRIT, deci no-op sigur azi."""
    from learning_core.run_continuous_learning import main as run_continuous_learning
    run_continuous_learning()
    return "learning_core.run_continuous_learning executat (pre-existent, ADR-030, gatat de learning_core_enabled)"


def _stage_diagnostics() -> dict:
    """8. Diagnostics — snapshot real de completitudine Foundation Data
    Layer (ultimele meciuri procesate), NU un probe live nou (acela e
    diagnostics_api_football.py, unealtă POC separată, nefolosită aici)."""
    from database.queries import get_recent_flashscore_matches
    recent = get_recent_flashscore_matches(limit=20)
    if not recent:
        return {"matches_checked": 0, "avg_coverage_percent": None}
    coverages = [r.get("coverage_percent", 0.0) for r in recent]
    return {
        "matches_checked": len(recent),
        "avg_coverage_percent": round(sum(coverages) / len(coverages), 1),
        "min_coverage_percent": min(coverages),
    }


def _stage_cleanup() -> dict:
    """9. Cleanup — Season Cleanup DRY RUN (ADR-044 Addendum A6) — RAPORT
    DOAR, nicio ștergere (`delete_executed` rămâne mereu False, garantat
    prin construcție de `season_cleanup.py`, care nu conține niciun DELETE)."""
    from providers.flashscore.season_cleanup import build_cleanup_dry_run_report
    report = build_cleanup_dry_run_report()
    return {"delete_executed": report.get("delete_executed", False),
            "cleanup_candidates": report.get("cleanup_candidates", [])}


def _stage_backup() -> dict:
    """10. Backup — export JSON, read-only, al celor 6 tabele Foundation
    Data Layer (`providers/flashscore/backup.py`) — activarea explicit
    cerută a pasului lăsat neimplementat de ADR-044 Addendum A6. Delete/
    Integrity Check rămân neimplementate (scope neschimbat, doar Backup a
    fost cerut)."""
    from providers.flashscore.backup import run_backup
    return run_backup()


def run() -> list[dict[str, Any]]:
    print()
    print("═" * 78)
    print("  Football Oracle — Night Sync")
    print("  Discovery → API Providers → Flashscore → Validation →")
    print("  Canonical Database → Team DNA → Oracle Data Layer → Diagnostics →")
    print("  Cleanup → Backup → Final Report")
    print("  (+ Continuous Learning, ADR-030, pre-existentă, gatată OFF implicit)")
    print("═" * 78)

    started_at = datetime.now(timezone.utc).isoformat()
    report: list[dict[str, Any]] = []

    _run_stage("1-4. Discovery + API Providers + Validation + Canonical Database", _stage_api_providers, report)
    _run_stage("5. Flashscore (Discovery + fetch/persist, Delta Sync)", _stage_flashscore, report)
    _run_stage("6. Team DNA", _stage_team_dna, report)
    _run_stage("7. Oracle Data Layer", _stage_oracle_data_layer, report)
    _run_stage("[extra, pre-existentă] Continuous Learning (ADR-030)", _stage_ml_refresh_pre_existing, report)
    _run_stage("8. Diagnostics", _stage_diagnostics, report)
    _run_stage("9. Cleanup (Season Cleanup — dry run)", _stage_cleanup, report)
    _run_stage("10. Backup", _stage_backup, report)

    finished_at = datetime.now(timezone.utc).isoformat()
    ok_count = sum(1 for r in report if r["ok"])
    fail_count = len(report) - ok_count

    print()
    print("═" * 78)
    print(f"  RAPORT FINAL — Night Sync")
    print(f"  Început: {started_at}   Sfârșit: {finished_at}")
    print(f"  Etape: {ok_count} reușite, {fail_count} eșuate din {len(report)}")
    for r in report:
        status = "✅" if r["ok"] else "❌"
        print(f"    {status} {r['stage']} ({r['duration_s']}s)")
    print("═" * 78)
    print()

    return report


if __name__ == "__main__":
    run()
