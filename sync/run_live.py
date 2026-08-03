"""
================================================================================
FOOTBALL ORACLE — Live Sync (Faza 2)
================================================================================
Module: sync/run_live.py

Nivelul UȘOR de sincronizare, gândit să ruleze FRECVENT, ziua — spre
deosebire de Night Sync (`sync/run_night.py`), care e pipeline-ul complet,
unic, o dată pe noapte. Actualizează DOAR:

    - discovery de meciuri noi (scheduled_fixtures, deja parte din
      sync/run_daily.py)
    - scoruri (sync_results)
    - cote (odds_persistence, odds_recent_results)
    - statistici de meci (sync_match_statistics + Flashscore stats/odds/
      lineups/player stats/H2H/standings, cu Delta Sync — sare meciurile
      deja colectate canonic)
    - lineups, player stats
    - H2H și standings (când e nevoie — Delta Sync face asta automat:
      un meci deja complet colectat nu se re-fetch-uiește)

NU recalculează Team DNA, NU rulează Oracle Refresh, NU rulează Feature
Engineering — acestea rămân exclusiv în Night Sync (sau, pentru Team
DNA/Oracle, calculate LIVE per predicție, niciodată batch, indiferent de
Live/Night Sync — vezi oracle_engine._build_flashscore_dna()).

Concret: `sync.run_daily.run(skip_features=True, skip_ml=True)` — cele
două flag-uri EXCLUD exact Pasul 3 (Feature Engineering/backfill) și
Pasul 6 (ML retrain) din run_daily.py, care sunt singurele pași "grei"
echivalenți cu ce trebuie exclus aici — plus fetch-ul Flashscore
(Foundation Data Layer, cu Delta Sync).

Idempotent — fiecare piesă apelată aici (sync_results, sync_match_
statistics, odds_persistence, Foundation Data Layer) e deja idempotentă
independent.

Schelet, NU rulat încă automat pe niciun cron (proprietarul produsului a
confirmat explicit: "e în regulă dacă Live Sync nu e încă complet
implementat... important e ca structura să fie pregătită") — vezi
`.github/workflows/live_sync.yml`, doar `workflow_dispatch` deocamdată.
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
    print("  Football Oracle — Live Sync (ușor, frecvent)")
    print("  Discovery + scoruri + cote + statistici + lineups + player stats +")
    print("  H2H/standings — FĂRĂ Team DNA / Oracle Refresh / Feature Engineering")
    print("═" * 78)

    result: dict = {}

    print("\n▶  Provideri API (sync/run_daily.py, skip_features=True, skip_ml=True)")
    try:
        from sync.run_daily import run as run_daily_sync
        run_daily_sync(skip_features=True, skip_ml=True, dry_run=dry_run)
        result["api_providers"] = {"ok": True}
        print("   ✅ OK")
    except Exception as exc:
        logger.error("[LiveSync] Provideri API — eșuat: %s", exc)
        result["api_providers"] = {"ok": False, "error": str(exc)}
        print(f"   ❌ EȘUAT: {exc}")

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
        description="Football Oracle — Live Sync (nivel ușor, discovery/scoruri/cote/statistici, fără Team DNA/Oracle/Feature Engineering)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Simulare fără scriere în Supabase")
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
