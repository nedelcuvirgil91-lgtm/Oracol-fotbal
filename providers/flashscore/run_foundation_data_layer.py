"""
================================================================================
FOOTBALL ORACLE — Flashscore Foundation Data Layer CLI (ADR-044)
================================================================================
Module: providers/flashscore/run_foundation_data_layer.py

Punct de intrare unic, executabil, care leagă `discovery.discover_matches()`
de `discovery.run_foundation_data_layer_for_discovered_matches()` — Discovery
găsește meciurile pentru competițiile urmărite, apoi Foundation Data Layer
rulează peste fiecare meci descoperit (fetch/normalize/validate/persist,
Data Trust Layer complet).

Complet SEPARAT de `sync/run_daily.py` (API providers, Tier 1) — Flashscore
e Tier 2 Playwright, auxiliar, rulat separat/la cerere, nu parte din
orchestrarea zilnică (ADR-044, ADR-042 tiering). Nicio schimbare aici la
`sync/run_daily.py`.

`--dry-run` rulează DOAR Discovery (nicio scriere, niciun fetch pe meci) —
util pentru verificarea listei de meciuri găsite înainte de rulare reală.
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import sys

from .discovery import (
    FLASHSCORE_TRACKED_COMPETITIONS,
    discover_matches,
    run_foundation_data_layer_for_discovered_matches,
)

logger = logging.getLogger("FootballOracle.Flashscore.CLI")


def _print_separator(char: str = "─", width: int = 78) -> None:
    print(char * width)


def run(leagues: list[str] | None, limit_per_league: int | None, dry_run: bool) -> int:
    targets = leagues if leagues is not None else list(FLASHSCORE_TRACKED_COMPETITIONS.keys())
    print()
    _print_separator("═")
    print("  Football Oracle — Flashscore Foundation Data Layer")
    _print_separator("═")
    print(f"  Competiții: {', '.join(targets)}")
    print(f"  Limită per competiție: {limit_per_league if limit_per_league is not None else 'fără limită'}")
    print(f"  Mod: {'DRY RUN (doar Discovery, fără fetch/persist)' if dry_run else 'LIVE (fetch + persist real)'}")
    _print_separator("─")
    print()

    matches = discover_matches(leagues=leagues, limit_per_league=limit_per_league)
    print(f"Discovery: {len(matches)} meciuri găsite.")
    for m in matches:
        print(f"  [{m.league}] {m.match_base_url} (mid={m.mid}, source={m.source})")

    if dry_run:
        print()
        print("Dry run — nicio scriere, niciun fetch per meci.")
        return 0

    if not matches:
        print("Niciun meci descoperit — nimic de rulat.")
        return 0

    print()
    _print_separator("─")
    print("Foundation Data Layer — fetch/normalize/validate/persist per meci:")
    reports = run_foundation_data_layer_for_discovered_matches(matches)

    ok_count = sum(1 for r in reports if r.get("ok"))
    fail_count = len(reports) - ok_count
    for r in reports:
        m = r.get("match")
        if r.get("ok"):
            status = "OK"
        elif r.get("error"):
            status = f"ESUAT ({r['error']})"
        elif r.get("validation_errors"):
            status = f"ESUAT (validare identitate: {r['validation_errors']})"
        else:
            # [FIX — gasit prin testare live, "ESUAT (None)" neinformativ]
            # fetch/normalize/validate au trecut, dar cel putin un pas din
            # persist_match_foundation_data() a esuat (steps["ceva"]=False) -
            # motivul exact al esecului acelui pas e deja logat separat de
            # database/queries.py (logger.error, cu numele functiei
            # upsert_*), dar fara asta CLI-ul nu spunea NIMIC util. Arata
            # match_ref + steps, ca sa se poata corela direct cu acel log.
            failed_steps = [k for k, v in (r.get("steps") or {}).items() if not v]
            status = f"ESUAT (match_ref={r.get('match_ref')}, pași eșuați: {failed_steps or 'necunoscut'})"
        print(f"  [{m.league if m else '?'}] mid={m.mid if m else '?'} -> {status}")

    print()
    _print_separator("═")
    print(f"  Rezultat: {ok_count} reușite, {fail_count} eșuate din {len(reports)} meciuri.")
    _print_separator("═")
    print()
    return 0 if fail_count == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Football Oracle — Flashscore Foundation Data Layer (Discovery + fetch/normalize/validate/persist)"
    )
    parser.add_argument(
        "--leagues", nargs="+", default=None,
        help=f"Competiții urmărite (implicit toate din FLASHSCORE_TRACKED_COMPETITIONS: "
             f"{', '.join(FLASHSCORE_TRACKED_COMPETITIONS.keys())})",
    )
    parser.add_argument(
        "--limit-per-league", type=int, default=None,
        help="Limitează numărul de meciuri descoperite per competiție (implicit fără limită)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Rulează doar Discovery — nu apelează fetch()/persist() pentru niciun meci",
    )
    args = parser.parse_args()

    exit_code = run(leagues=args.leagues, limit_per_league=args.limit_per_league, dry_run=args.dry_run)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
