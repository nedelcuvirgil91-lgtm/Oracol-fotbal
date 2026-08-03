"""
================================================================================
FOOTBALL ORACLE — Live Sync (Faza 2; redefinit Pasul 2, Master Repair Plan)
================================================================================
Module: sync/run_live.py

Nivelul UȘOR de sincronizare, gândit să ruleze FRECVENT, ziua — spre
deosebire de Night Sync (`sync/run_night.py`), care e pipeline-ul complet,
unic, o dată pe zi. Actualizează EXCLUSIV Flashscore (Foundation Data
Layer, Delta Sync).

[REDEFINIT — Pasul 2 Master Repair Plan] Apelul `sync.run_daily.run()`
(cele 12 sub-sync-uri către provideri API — rezultate, statistici,
sincronizare istoric, discovery meciuri, formă, sănătate echipe, cote
recente etc.) a fost ELIMINAT de aici. Motiv, verificat direct din cod:
`night_sync.yml` Stage 1 apelează deja `run_daily.run()` COMPLET
(neargumentat), o dată pe zi — orice apel suplimentar de aici ar fi
exact tipul de "interogare inutilă către provideri live" interzis
explicit de filosofia proiectului (cota API critică, Single Owner,
ADR-045). Providerii API nu au nevoie de mai mult de o rulare/zi — datele
lor (rezultate, clasamente, sănătate echipe) nu se schimbă suficient de
des ca să justifice o cadență mai agresivă, spre deosebire de Flashscore,
care are Delta Sync real (ieftin de rulat des).

Concret: `providers.flashscore.run_foundation_data_layer.run(leagues=None,
limit_per_league=get_limit_per_league_automated(), include_future_
fixtures=False)` — plafon configurabil (Supabase `model_config`) și
excludere explicită a meciurilor viitoare (zero valoare pentru Flashscore
azi, per ADR-045 Owner matrix) — identic mecanismului din
`sync/run_night.py::_stage_flashscore()`.

NU recalculează Team DNA, NU rulează Oracle Refresh, NU rulează Feature
Engineering, NU mai atinge providerii API — acestea rămân exclusiv în
Night Sync (sau, pentru Team DNA/Oracle, calculate LIVE per predicție,
niciodată batch — vezi oracle_engine._build_flashscore_dna()).

Idempotent — Foundation Data Layer e deja idempotent independent (Delta
Sync + upsert-uri canonice).

Cron: la 4 ore, decalat 30 min față de ora fixă (`night_sync.yml` rulează
la 03:00 UTC) — evită coliziunea directă a două sesiuni Playwright
Flashscore concurente (verificare explicită, Pasul 2 Master Repair Plan)
— vezi `.github/workflows/live_sync.yml`.
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

root = Path(__file__).parent.parent
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)s]  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("FootballOracle.LiveSync")


def run(dry_run: bool = False) -> dict:
    print()
    print("═" * 78)
    print("  Football Oracle — Live Sync (Flashscore, ușor, frecvent)")
    print("  DOAR Foundation Data Layer (Delta Sync) — providerii API rulează")
    print("  exclusiv în Night Sync, o dată pe zi (Single Owner, ADR-045)")
    print("═" * 78)

    result: dict = {}

    print("\n▶  Flashscore (Foundation Data Layer, Delta Sync)")
    if dry_run:
        result["flashscore"] = {"ok": True, "detail": "sărit (--dry-run)"}
        print("   ℹ️  Sărit (dry run)")
    else:
        try:
            # [ADAUGAT Pasul 1 Master Repair Plan, ADR-045; rafinat dupa
            # feedback] Plafon configurabil + excludere meciuri viitoare —
            # vezi comentariul complet din sync/run_night.py._stage_flashscore().
            from providers.flashscore.discovery import get_limit_per_league_automated
            from providers.flashscore.run_foundation_data_layer import run as run_flashscore
            exit_code = run_flashscore(leagues=None, limit_per_league=get_limit_per_league_automated(),
                                        dry_run=False, include_future_fixtures=False)
            result["flashscore"] = {"ok": exit_code == 0, "exit_code": exit_code}
            print("   ✅ OK" if exit_code == 0 else f"   ⚠️  exit_code={exit_code}")
        except Exception as exc:
            logger.error("[LiveSync] Flashscore — eșuat: %s", exc)
            result["flashscore"] = {"ok": False, "error": str(exc)}
            print(f"   ❌ EȘUAT: {exc}")

    print()
    print("═" * 78)
    print(f"  Live Sync — terminat. {result}")
    print("═" * 78)
    print()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Football Oracle — Live Sync (Flashscore Foundation Data Layer, ușor, frecvent)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulare fără scriere în Supabase")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
