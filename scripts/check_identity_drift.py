"""
================================================================================
FOOTBALL ORACLE — Detectie recurenta a fragmentarii de identitate
================================================================================
Module: scripts/check_identity_drift.py

STRICT read-only. Nu scrie in Supabase, nu modifica `mappings.py`, nu modifica
baseline-ul — bump-ul baseline-ului e o decizie umana, separata, comisa
explicit (vezi mai jos).

DE CE EXISTA (ADR-059, sectiunea "Gol ramas deschis"): indexul unic
`idx_match_history_natural_key_canonical` opereaza pe nume BRUTE. Writerii
normalizeaza la scriere, deci intrarile NOI converg — dar orice extindere de
VOCABULAR (alias nou, sursa noua care scrie sub un nume neacoperit) poate face
ca randuri deja existente, scrise sub un vocabular mai vechi, sa devina
"acelasi meci" din perspectiva `match_key()`, fara ca indexul sa poata vedea
asta vreodata. S-a intamplat de doua ori intr-o singura zi (F3 dimineata,
TSDB noaptea, 2026-08-21) — descoperit prin investigatie manuala, nu prin
monitorizare. Acest script inchide golul de DETECTIE (nu golul structural —
vezi ADR-059 pentru optiunile respinse si motivul).

MECANISM: re-ruleaza descoperirea deja aprobata (`MatchIdentityReconciliationService.
run(dry_run=True)`, acelasi cod folosit de `run_identity_reconciliation_dryrun.py`
si verificat pe date reale de doua ori — rularile GitHub Actions 32536869017 si
32538543695) si compara SETUL de chei de grup (`match_key()`) cu un baseline
git-committed (`docs/00_GOVERNANCE/identity_drift_baseline.json`). Compararea e
pe SET, nu pe numar: un grup vechi disparut in aceeasi rulare in care unul nou
apare ar lasa numarul total neschimbat, dar setul de chei diferit — exact clasa
de regresie pe care un simplu `count() != baseline_count` ar rata-o.

IESIRE: exit code 0 daca nu exista grupuri/conflicte NOI fata de baseline
(succes silentios, fara zgomot). Exit code 1 daca apare ceva nou — job-ul
GitHub Actions devine rosu, vizibil in Actions, acelasi tipar deja folosit in
tot proiectul (ex. flashscore_weekly_fixtures.yml) pentru "asta cere atentie
umana", fara nicio infrastructura noua de notificare (Slack/email) — niciuna
nu exista azi in proiect, verificat explicit inainte de a alege acest tipar.

BUMP-UL BASELINE-ULUI: intentionat NEAUTOMAT. Cand acest script raporteaza
drift, decizia (e o fuziune falsa? o descoperire legitima ca F4.6/Jagiellonia?
un caz de investigat separat?) apartine omului. Odata inteles, baseline-ul se
regenereaza rulind acest script cu `--emit-baseline` si comitand rezultatul
explicit — exact tiparul deja folosit pentru
`docs/00_GOVERNANCE/identity_audit_F0/baseline_counts.json`.

Utilizare:
    python scripts/check_identity_drift.py                    # verifica drift
    python scripts/check_identity_drift.py --emit-baseline    # regenereaza baseline-ul
================================================================================
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78
BASELINE_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs" / "00_GOVERNANCE" / "identity_drift_baseline.json"
)


def _load_baseline() -> dict:
    if not BASELINE_PATH.exists():
        raise SystemExit(
            f"Baseline lipseste: {BASELINE_PATH}\n"
            "Genereaza-l intai cu: python scripts/check_identity_drift.py --emit-baseline"
        )
    with BASELINE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _run_discovery():
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        raise SystemExit(1)

    from services.match_identity_reconciliation_service import (
        MatchIdentityReconciliationService,
    )

    # `limit_groups` ramane implicit None — un pilot partial ar raporta doar un
    # subset ca "reconciled_group_keys", producand falsuri-pozitive de drift
    # pentru grupurile ramase neprocesate. Detectia de drift trebuie sa vada
    # TOATA descoperirea, chiar daca EXECUTE-ul propriu-zis va fi mai tarziu
    # limitat la un pilot.
    return MatchIdentityReconciliationService().run(dry_run=True)


def emit_baseline() -> int:
    report = _run_discovery()
    baseline = {
        "_comment": (
            "Baseline al fragmentarii de identitate CUNOSCUTE si acceptate — "
            "generat mecanic de scripts/check_identity_drift.py --emit-baseline, "
            "NICIODATA editat de mana (acelasi principiu ca "
            "identity_audit_F0/baseline_counts.json). Orice grup NOU aparut fata "
            "de acest fisier e semnalat de check_identity_drift.py ca drift."
        ),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "reconciled_group_keys": sorted(report.reconciled_group_keys),
        "hard_conflict_keys": sorted(report.excluded_hard_conflict),
        "unknown_source_keys": sorted(report.excluded_unknown_source),
    }
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with BASELINE_PATH.open("w", encoding="utf-8") as fh:
        json.dump(baseline, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print(f"Baseline scris: {BASELINE_PATH}")
    print(f"  reconciled_group_keys : {len(baseline['reconciled_group_keys'])}")
    print(f"  hard_conflict_keys    : {len(baseline['hard_conflict_keys'])}")
    print(f"  unknown_source_keys   : {len(baseline['unknown_source_keys'])}")
    return 0


def compute_drift(baseline: dict, current_known, current_hard_conflict,
                   current_unknown_source) -> dict:
    """Functie PURA — nicio dependinta de Supabase/fisier. Separata explicit
    de I/O ca sa fie testabila direct, fara mock-uri (`tests/
    test_check_identity_drift.py`)."""
    baseline_known = set(baseline["reconciled_group_keys"])
    baseline_hard_conflict = set(baseline.get("hard_conflict_keys", []))
    baseline_unknown_source = set(baseline.get("unknown_source_keys", []))

    current_known = set(current_known)
    current_hard_conflict = set(current_hard_conflict)
    current_unknown_source = set(current_unknown_source)

    return {
        "new_groups": sorted(current_known - baseline_known),
        "resolved_groups": sorted(baseline_known - current_known),
        "new_hard_conflicts": sorted(current_hard_conflict - baseline_hard_conflict),
        "new_unknown_source": sorted(current_unknown_source - baseline_unknown_source),
        "baseline_known_count": len(baseline_known),
        "current_known_count": len(current_known),
    }


def check_drift() -> int:
    baseline = _load_baseline()
    report = _run_discovery()

    diff = compute_drift(
        baseline, report.reconciled_group_keys,
        report.excluded_hard_conflict, report.excluded_unknown_source,
    )
    new_groups = diff["new_groups"]
    resolved_groups = diff["resolved_groups"]
    new_hard_conflicts = diff["new_hard_conflicts"]
    new_unknown_source = diff["new_unknown_source"]

    print()
    print(BAR)
    print("  DETECTIE RECURENTA — fragmentare de identitate (ADR-059)")
    print(BAR)
    print(f"  Baseline captat        : {baseline.get('captured_at_utc', '?')}")
    print(f"  Grupuri in baseline     : {diff['baseline_known_count']}")
    print(f"  Grupuri descoperite azi : {diff['current_known_count']}")
    print(BAR)

    drift = bool(new_groups or new_hard_conflicts or new_unknown_source)

    if new_groups:
        print(f"  \U0001f534 {len(new_groups)} grup(uri) NOI, absente din baseline:")
        for k in new_groups:
            print(f"      {k}")
    if new_hard_conflicts:
        print(f"  \U0001f534 {len(new_hard_conflicts)} conflict(e) HARD CONFLICT NOI:")
        for k in new_hard_conflicts:
            print(f"      {k}")
    if new_unknown_source:
        print(f"  \U0001f534 {len(new_unknown_source)} grup(uri) cu sursa NECUNOSCUTA, noua:")
        for k in new_unknown_source:
            print(f"      {k}")
    if resolved_groups:
        # Informativ, NU cauza de esec — un grup poate disparea legitim (ex.
        # marcat superseded de o executie F4 aprobata separat).
        print(f"  ℹ️  {len(resolved_groups)} grup(uri) din baseline nu mai apar (probabil deja reconciliate):")
        for k in resolved_groups:
            print(f"      {k}")

    print(BAR)
    if drift:
        print("  REZULTAT: DRIFT DETECTAT. Investigheaza cazurile de mai sus.")
        print("  Pentru raportul complet (owner, sursa, coloane): ")
        print("    python scripts/run_identity_reconciliation_dryrun.py")
        print("  Dupa investigare, daca noile grupuri sunt legitime, regenereaza baseline-ul:")
        print("    python scripts/check_identity_drift.py --emit-baseline")
        print(BAR)
        return 1

    print("  REZULTAT: fara drift. Vocabularul de identitate e stabil.")
    print(BAR)
    return 0


def main() -> int:
    if "--emit-baseline" in sys.argv:
        return emit_baseline()
    return check_drift()


if __name__ == "__main__":
    raise SystemExit(main())
