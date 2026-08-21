"""
================================================================================
FOOTBALL ORACLE — Runner DRY-RUN pentru reconcilierea de identitate (ID-025-02)
================================================================================
Module: scripts/run_identity_reconciliation_dryrun.py

DRY-RUN, EXCLUSIV. Acest script nu poate scrie in `match_history` nici din
greseala: apeleaza `run(dry_run=True)` cu argument literal, nu expune niciun
flag de executie, si nu importa nicio cale de scriere. Modul EXECUTE ramane
neimplementat in serviciu (`NotImplementedError`) si autorizabil doar prin
Phase Gate explicit (ADR-025).

DE CE EXISTA: raportul Faza 2 al ADR-025 declara explicit intentia ca
descoperirea sa fie rulabila din nou — "pentru o rulare viitoare (CLI/GitHub
Actions), nu doar pentru acest raport"
(`docs/03_ENGINE/ADR025_PHASE2_DRY_RUN_REPORT_2026-07-16.md:25`). Runner-ul
folosit atunci nu exista in repo, deci raportul nu era reproductibil. Acest
script inchide golul.

DE CE ACUM: F3 (ADR-058) a extins vocabularul `ALIAS_TO_CANONICAL` cu 130 de
rezolutii. `match_key()` — aceeasi functie folosita de descoperirea ID-025-02 —
produce acum grupuri duplicate care in iulie erau invizibile. Raportul de atunci
isi notase singur conditia de expirare: normalizarea "nu produce niciun grup
suplimentar fata de gruparea bruta, PENTRU DATELE CURENTE". Datele s-au
schimbat, deci raportul trebuie regenerat inainte de orice decizie de scriere.

Utilizare (necesita SUPABASE_URL + SUPABASE_SECRET_KEY):
    python scripts/run_identity_reconciliation_dryrun.py
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

BAR = "=" * 78


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from services.match_identity_reconciliation_service import (
        MatchIdentityReconciliationService,
    )
    from source_trust_policy import SOURCE_TRUST_RANK

    service = MatchIdentityReconciliationService()
    report = service.run(dry_run=True)  # literal, neparametrizabil — vezi antet

    print()
    print(BAR)
    print("  ID-025-02 — RAPORT DRY-RUN (zero scriere)")
    print(BAR)
    print("  Registru de incredere activ:")
    for source, rank in sorted(SOURCE_TRUST_RANK.items(), key=lambda kv: kv[1]):
        print(f"    {rank}. {source}")
    print(BAR)
    print(f"  Total grupuri duplicate descoperite : {report.total_groups}")
    print(f"  Reconciliabile                      : {report.reconciled_groups}")
    print(f"  Excluse — HARD CONFLICT             : {report.excluded_hard_conflict_count}")
    print(f"  Excluse — sursa necunoscuta         : {report.excluded_unknown_source_count}")
    print(f"  Randuri de marcat superseded        : {report.rows_to_mark}")
    print(f"  Randuri canonice cu goluri de date  : {report.canonical_rows_with_data_gap}")
    print(BAR)
    print("  [ADR-059] Reconcilierea MARCHEAZA, nu contopeste. Golurile de mai")
    print("  jos NU se scriu — se raporteaza, ca owner-ul lor sa le regenereze.")
    print(BAR)

    if report.columns_with_data_gap:
        print("  Goluri de date per coloana (lipsa pe canonic, prezenta pe necanonic):")
        for col, n in sorted(report.columns_with_data_gap.items(), key=lambda kv: -kv[1]):
            print(f"    {col:<32} {n}")
        print()
        print("  Cine poate regenera aceste goluri:")
        for owner, n in sorted(report.gaps_by_owner.items(), key=lambda kv: -kv[1]):
            print(f"    {owner:<32} {n}")
    else:
        print("  Niciun gol de date — randurile canonice au tot ce au necanonicele.")
    print(BAR)

    # Grupurile excluse sunt cele care cer decizie umana — se listeaza integral,
    # nu se rezuma: un grup exclus tacit e exact tiparul pe care guvernanta
    # proiectului il interzice.
    if report.excluded_hard_conflict:
        print("  HARD CONFLICT — necesita decizie manuala, per grup:")
        for key in report.excluded_hard_conflict:
            print(f"    {key}")
        print(BAR)

    if report.excluded_unknown_source:
        print("  SURSA NECUNOSCUTA — prefix nerezolvat de resolve_source():")
        for key in report.excluded_unknown_source:
            print(f"    {key}")
        print(BAR)

    print("  DRY-RUN incheiat. Zero scriere efectuata.")
    print(BAR)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
