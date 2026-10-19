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


def _plan_recuperare(
    matches: list, max_recover: int, days_back: int,
) -> tuple[set[str], list, dict[str, int]]:
    """Setul de `mid`-uri de recuperat (ADR-076 D-B) și lista de meciuri
    restrânsă la ele.

    De ce se RESTRÂNGE lista, în loc să se paseze doar `force_mids`: o
    rulare de recuperare care parcurge toate meciurile descoperite ar cere
    Delta Sync pentru fiecare (o interogare Supabase per meci) degeaba.
    Recuperarea are o singură treabă — meciurile din restanță.

    De ce există un PLAFON: 653 de meciuri × 7 taburi × ~3,5 s + pacing
    politicos ≈ 5 ore, iar workflow-ul are 90 de minute. Fără plafon,
    rularea ar fi tăiată la mijloc — exact tiparul deja plătit de
    `live_sync` și `sync_pre_match_odds`. Se rulează repetat, în tranșe."""
    from database.queries import get_flashscore_mids_missing_statistics

    tinta = get_flashscore_mids_missing_statistics(days_back=days_back)
    gasite = [m for m in matches if m.mid in tinta]
    plafonate = gasite[:max_recover] if max_recover > 0 else gasite
    stats = {
        "in_restanta": len(tinta),
        "gasite_pe_hub": len(gasite),
        "de_recuperat_acum": len(plafonate),
    }
    return {m.mid for m in plafonate}, plafonate, stats


def run(
    leagues: list[str] | None, limit_per_league: int | None, dry_run: bool,
    include_future_fixtures: bool = True, future_fixtures_only: bool = False,
    recover_missing_stats: bool = False, max_recover: int = 50,
    recover_days_back: int = 60,
) -> int:
    """`include_future_fixtures` [ADAUGAT Pasul 1 Master Repair Plan] —
    implicit True (comportament CLI/manual neschimbat). Rulările automate
    (`run_night.py`/`run_live.py`) apelează cu `False` — vezi
    `discovery._discover_for_hub()` pentru motivul complet.

    `future_fixtures_only` [ADAUGAT 2026-08-05] — cere `/fixtures/`
    necondiționat (nu ca fallback la `/results/` gol). Folosit DOAR de
    flashscore_weekly_fixtures.yml — vezi `discovery._discover_for_hub()`
    pentru motivul complet (fără el, `/fixtures/` nu era aproape niciodată
    verificat, pentru că `/results/` are aproape mereu conținut)."""
    targets = leagues if leagues is not None else list(FLASHSCORE_TRACKED_COMPETITIONS.keys())
    if future_fixtures_only:
        future_fixtures_desc = "DOAR meciuri viitoare (/fixtures/, necondiționat — /results/ neatins)"
    elif include_future_fixtures:
        future_fixtures_desc = "incluse (fallback pe /fixtures/ doar dacă /results/ e gol)"
    else:
        future_fixtures_desc = "excluse (doar meciuri terminate)"
    print()
    _print_separator("═")
    print("  Football Oracle — Flashscore Foundation Data Layer")
    _print_separator("═")
    print(f"  Competiții: {', '.join(targets)}")
    print(f"  Limită per competiție: {limit_per_league if limit_per_league is not None else 'fără limită'}")
    print(f"  Mod: {'DRY RUN (doar Discovery, fără fetch/persist)' if dry_run else 'LIVE (fetch + persist real)'}")
    print(f"  Meciuri viitoare: {future_fixtures_desc}")
    _print_separator("─")
    print()

    # [ADR-067] `persist_calendar=not dry_run` — un dry-run nu scrie NIMIC,
    # nici macar calendarul sezonului, altfel mesajul „Dry run — nicio scriere"
    # de mai jos ar fi fals.
    matches = discover_matches(leagues=leagues, limit_per_league=limit_per_league,
                                include_future_fixtures=include_future_fixtures,
                                future_fixtures_only=future_fixtures_only,
                                persist_calendar=not dry_run)
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

    force_mids: set[str] | None = None
    if recover_missing_stats:
        force_mids, matches, plan = _plan_recuperare(matches, max_recover, recover_days_back)
        print()
        _print_separator("─")
        print("  MOD RECUPERARE (ADR-076 D-B) — Delta Sync ocolit DOAR pentru ținte")
        print(f"  meciuri în restanță (terminate, `home_shots IS NULL`): {plan['in_restanta']}")
        print(f"  dintre ele, găsite pe hub-urile descoperite acum       : {plan['gasite_pe_hub']}")
        print(f"  de recuperat în această tranșă (plafon {max_recover})  : {plan['de_recuperat_acum']}")
        if plan["gasite_pe_hub"] > plan["de_recuperat_acum"]:
            print(f"  RĂMÂN pentru tranșele următoare: "
                  f"{plan['gasite_pe_hub'] - plan['de_recuperat_acum']} "
                  "(rulează din nou — lista se recalculează din bază)")
        _print_separator("─")
        if not matches:
            print("Niciun meci din restanță nu e pe hub-urile cerute — nimic de recuperat.")
            return 0

    print()
    _print_separator("─")
    print("Foundation Data Layer — fetch/normalize/validate/persist per meci:")
    reports = run_foundation_data_layer_for_discovered_matches(matches, force_mids=force_mids)

    ok_count = sum(1 for r in reports if r.get("ok"))
    skipped_count = sum(1 for r in reports if r.get("skipped"))
    fail_count = len(reports) - ok_count
    for r in reports:
        m = r.get("match")
        if r.get("skipped"):
            status = "SĂRIT (deja colectat — Delta Sync)"
        elif r.get("ok"):
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
    print(f"  Rezultat: {ok_count} reușite ({skipped_count} sărite, Delta Sync), "
          f"{fail_count} eșuate din {len(reports)} meciuri.")
    _print_separator("═")
    print()
    # [REEVALUAT 2026-08-25 — pragul RAMANE 0 tolerant, cu date, nu din inertie]
    #
    # `CLAUDE.md` nota pragul ca „de reevaluat dupa cateva rulari curate".
    # Reevaluarea s-a facut pe istoricul complet al celor doua workflow-uri care
    # folosesc aceasta functie — 27 de rulari:
    #
    #   Foundation Data Layer (16 rulari): 2 esecuri, ambele la inceput
    #     (2026-07-29) — un jucator duplicat in lot care facea sa esueze TOT
    #     meciul (ON CONFLICT ... cannot affect row a second time), si o
    #     excludere documentata de player-stats raportata gresit ca esec.
    #     Ambele erau defecte REALE, ambele reparate. De atunci: 9 rulari verzi.
    #
    #   Weekly Fixtures (11 rulari): 3 esecuri (17, 20, 23 august), toate cu
    #     ACEEASI cauza — meciul reprogramat Celta Vigo – Osasuna. Descoperirea
    #     de fixture-uri noi a fost blocata 10 zile. Reparat prin migrarea 048.
    #     Rularea urmatoare (24 august): verde.
    #
    # CONCLUZIA: in 27 de rulari, ZERO alarme false. Fiecare rosu a fost un
    # defect real si actionabil. Un prag relaxat (ex. „esueaza doar sub 95%")
    # ar fi ascuns exact reprogramarea — pe 20 august rata a fost 389/393
    # (99,0%), deci ar fi trecut drept verde, iar bugul ar fi continuat sa
    # blocheze descoperirea.
    #
    # Problema reala de pe 20 august nu era pragul, ci RAPORTAREA: „4 esecuri
    # din 393" si „intreaga rulare s-a prabusit" arata la fel in interfata.
    # Aia se rezolva prin raport mai bun (ce anume a esuat, gruparea pe cauza),
    # nu prin slabirea semnalului. Vezi lista de sub, in raportul de mai sus,
    # care deja enumera fiecare meci esuat cu motivul lui.
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
    parser.add_argument(
        "--no-future-fixtures", action="store_true",
        help="Exclude meciurile VIITOARE (hub /fixtures/) — colectează doar meciuri deja terminate "
             "(implicit folosit de rulările automate, night_sync.yml/live_sync.yml)",
    )
    parser.add_argument(
        "--future-fixtures-only", action="store_true",
        help="Cere DOAR /fixtures/ (meciuri viitoare), necondiționat — nu ca fallback la /results/ gol "
             "(folosit de flashscore_weekly_fixtures.yml; incompatibil cu --no-future-fixtures)",
    )
    parser.add_argument(
        "--recover-missing-stats", action="store_true",
        help="MOD RECUPERARE (ADR-076 D-B): procesează DOAR meciurile terminate rămase fără "
             "statistici (`home_shots IS NULL`), ocolind Delta Sync strict pentru ele. "
             "Lista se calculează din bază la fiecare rulare, nu se dă manual.",
    )
    parser.add_argument(
        "--max-recover", type=int, default=50,
        help="Plafon de meciuri recuperate într-o tranșă (implicit 50). Există pentru că "
             "restanța întreagă ar depăși timeout-ul workflow-ului; se rulează repetat.",
    )
    parser.add_argument(
        "--recover-days-back", type=int, default=60,
        help="Cât de departe în trecut caută restanța (implicit 60 de zile)",
    )
    args = parser.parse_args()

    if args.recover_missing_stats and args.future_fixtures_only:
        parser.error("--recover-missing-stats lucrează pe meciuri TERMINATE; "
                     "--future-fixtures-only cere doar meciuri viitoare. Se exclud reciproc.")

    if args.future_fixtures_only and args.no_future_fixtures:
        parser.error("--future-fixtures-only și --no-future-fixtures sunt incompatibile.")

    exit_code = run(leagues=args.leagues, limit_per_league=args.limit_per_league, dry_run=args.dry_run,
                     include_future_fixtures=not args.no_future_fixtures,
                     future_fixtures_only=args.future_fixtures_only,
                     recover_missing_stats=args.recover_missing_stats,
                     max_recover=args.max_recover,
                     recover_days_back=args.recover_days_back)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
