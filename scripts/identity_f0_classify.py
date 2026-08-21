"""
================================================================================
FOOTBALL ORACLE — F0: clasificarea mecanică a bazelor din perechile cu sufix
================================================================================
Module: scripts/identity_f0_classify.py

Tooling de audit (nu cod de producție — niciun modul din app.py/
oracle_engine.py/sync/*/learning_core/* îl importă). Read-only: nicio
scriere în Supabase, niciun flag atins, nicio decizie luată automat.

MOTIVUL EXISTENȚEI (important, nu doar convenabil): în auditul manual
anterior lista bazelor a fost transcrisă de mână și a ieșit GREȘITĂ — 6
nume clasificate ca „necunoscute" erau de fapt deja canonice (E2), iar
totalul nu se împăca cu interogarea (84 vs. 85, E3). O listă purtată de
mână printr-un audit e exact mecanismul care produce astfel de erori.

Acest script consumă artefactul generat de interogare
(`docs/00_GOVERNANCE/identity_audit_F0/suffix_pairs.csv`, produs de SQL-ul
citat în README-ul aceluiași director) și îl clasifică STRICT programatic
contra stării reale a `mappings.TEAM_ALIASES`. Rezultatul e artefactul pe
care F3 are voie să-l consume — niciodată o listă din text.

Utilizare:
    python scripts/identity_f0_classify.py
================================================================================
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ARTIFACT_DIR = Path(__file__).resolve().parent.parent / "docs" / "00_GOVERNANCE" / "identity_audit_F0"
PAIRS_CSV = ARTIFACT_DIR / "suffix_pairs.csv"
OUT_CSV = ARTIFACT_DIR / "class_a_bases.csv"


def classify() -> list[dict]:
    """Pentru fiecare bază: e deja canonică în TEAM_ALIASES, e alias către
    altceva, sau e necunoscută? Nicio decizie nu e luată aici — doar se
    constată starea curentă a vocabularului."""
    import mappings as m

    canonical_keys = set(m.TEAM_ALIASES.keys())
    rows: list[dict] = []
    with PAIRS_CSV.open(encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            base = rec["base"]
            resolved = m.normalize_team_name(base)
            if base in canonical_keys:
                status = "ALREADY_CANONICAL"
            elif resolved != base:
                status = "ALIAS_OF_OTHER"
            else:
                status = "NEW_CANONICAL_NEEDED"
            rows.append({
                "suffixed": rec["suffixed"],
                "base": base,
                "country_code": rec["country_code"],
                "status": status,
                "resolves_to_today": resolved,
                # Ce ar returna normalize_team_name() pentru forma CU sufix,
                # în starea de AZI (înainte de orice patch) — dovada că
                # varianta suffixată e azi o identitate separată.
                "suffixed_resolves_to_today": m.normalize_team_name(rec["suffixed"]),
            })
    return rows


def main() -> None:
    rows = classify()
    with OUT_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    print()
    print("=" * 78)
    print("  F0 — clasificare mecanică a bazelor (perechi cu sufix de țară)")
    print("=" * 78)
    print(f"  Perechi în artefactul de intrare : {len(rows)}")
    print(f"  Baze distincte                   : {len({r['base'] for r in rows})}")
    for status, n in sorted(counts.items()):
        print(f"    {status:<24} {n}")
    print()
    print(f"  Scris: {OUT_CSV.relative_to(Path.cwd())}" if OUT_CSV.is_relative_to(Path.cwd())
          else f"  Scris: {OUT_CSV}")

    # Invariant de siguranță: nicio bază nu are voie să rezolve azi la
    # altceva — ar însemna că fuziunea propusă intră în conflict cu un
    # alias deja existent (semnal de clasa B/C, niciodată clasa A).
    conflicts = [r for r in rows if r["status"] == "ALIAS_OF_OTHER"]
    if conflicts:
        print()
        print("  ⚠️  CONFLICTE (bază deja mapată la alt canonic) — NU sunt clasa A:")
        for r in conflicts:
            print(f"     {r['base']!r} -> {r['resolves_to_today']!r}")
    print("=" * 78)
    print()


if __name__ == "__main__":
    main()
