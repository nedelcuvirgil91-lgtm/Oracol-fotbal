"""
================================================================================
FOOTBALL ORACLE — F3: emiterea mecanică a blocului de baze canonice (ADR-058)
================================================================================
Module: scripts/identity_f3_emit_aliases.py

Tooling de audit (nu cod de producție). Read-only: nu scrie în Supabase, nu
modifică `mappings.py`, nu ia nicio decizie. Doar EMITE textul Python pe care
îl consumă F3, pornind STRICT de la artefactul F0
(`docs/00_GOVERNANCE/identity_audit_F0/class_a_bases.csv`).

DE CE EXISTĂ (ADR-058 §2.5): în auditul manual, lista bazelor a fost
transcrisă de mână și a ieșit greșită de patru ori (E1-E3 + o a patra
descoperită chiar de scriptul de clasificare). Acest emitter elimină pasul
manual complet: ce intră în `mappings.py` e generat, nu copiat.

Emite DOAR intrările cu `status == NEW_CANONICAL_NEEDED`. Bazele deja
canonice (`ALREADY_CANONICAL`) sunt sărite deliberat — regula structurală de
sufix le rezolvă fără alias nou, iar re-declararea lor ar produce chei
duplicate în dicționar.

Utilizare:
    python scripts/identity_f3_emit_aliases.py
================================================================================
"""
from __future__ import annotations

import csv
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ARTIFACT = (
    Path(__file__).resolve().parent.parent
    / "docs" / "00_GOVERNANCE" / "identity_audit_F0" / "class_a_bases.csv"
)


def main() -> None:
    if not ARTIFACT.exists():
        raise SystemExit(
            f"Artefactul F0 lipsește: {ARTIFACT}\n"
            "Rulează întâi `python scripts/identity_f0_classify.py`."
        )

    with ARTIFACT.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    by_status: dict[str, list[str]] = {}
    for r in rows:
        by_status.setdefault(r["status"], []).append(r["base"])

    new_bases = sorted(set(by_status.get("NEW_CANONICAL_NEEDED", [])))
    already = sorted(set(by_status.get("ALREADY_CANONICAL", [])))
    conflicts = sorted(set(by_status.get("ALIAS_OF_OTHER", [])))

    # Gardă: o bază care rezolvă deja la ALTCEVA nu are voie în clasa A —
    # ar fi o fuziune peste un alias existent, decizie de clasa B/C.
    if conflicts:
        raise SystemExit(
            "ALIAS_OF_OTHER != 0 — bazele următoare intră în conflict cu "
            f"vocabularul existent și NU sunt clasa A: {conflicts}"
        )

    print()
    print("=" * 78)
    print("  F3 — bloc generat pentru mappings.TEAM_ALIASES")
    print("=" * 78)
    print(f"  Perechi în artefact          : {len(rows)}")
    print(f"  ALREADY_CANONICAL (sărite)   : {len(already)}")
    print(f"  NEW_CANONICAL_NEEDED (emise) : {len(new_bases)}")
    print(f"  ALIAS_OF_OTHER               : {len(conflicts)}")
    print("=" * 78)
    print()

    # O intrare pe linie — ieșirea trebuie să fie direct pastabilă în
    # mappings.py, fără reformatare manuală (care ar reintroduce exact
    # pasul manual pe care acest script îl elimină).
    width = max(len(b) for b in new_bases) + 3
    for b in new_bases:
        print(f'    {(chr(34) + b + chr(34) + ":"):<{width}} [],')
    print()


if __name__ == "__main__":
    main()
