"""
================================================================================
FOOTBALL ORACLE — Pilot de reconciliere a identitatii (ADR-025 Faza 3)
================================================================================
Module: scripts/run_identity_reconciliation_pilot.py

SCRIE IN PRODUCTIE. Singurul script din tot lantul ID-025 care are voie sa
apeleze `run(dry_run=False)`. Suprafata de scriere e exact cea descrisa in
ADR-059: `superseded_by`/`superseded_at`/`superseded_reason`, exclusiv pe
randul NECANONIC al fiecarui grup tintit — randul canonic nu e atins de
niciun octet, nicio coloana de date nu e scrisa niciodata (garda structurala
AST: tests/test_adr059_reconciliation_is_identity.py).

DE CE ACESTE 6 GRUPURI (ADR-025 Faza 3 — pilot pe subset izolat, verificat
manual, inainte de rulare completa): sunt singurele 6 din cele 403 grupuri
reconciliabile cu compozitia de surse `flashscore + tsdb`. Verificat live pe
date reale (audit F4, 2026-08-21):
  - semnalul cel mai clar din tot setul — diferenta de completitudine intre
    randul canonic (flashscore) si cel necanonic (tsdb) e de 30-39 coloane,
    fata de 0-8 la restul compozitiilor de surse;
  - 0 copii FK pe randul necanonic in niciunul din cele 6 grupuri (verificat
    F4.1) — deci zero risc de re-parentare;
  - toate 6 au fost confirmate deterministe (0 tie-uri) sub regula
    completitudine -> FK -> sursa -> id, verificat mecanic pe toate cele 403
    grupuri, nu doar pe acestea 6;
  - toate 6 sunt confirmate azi (2026-08-22) inca prezente in
    `docs/00_GOVERNANCE/identity_drift_baseline.json`.

Cheile sunt `match_key()` (aceeasi functie folosita de tot lantul ID-025),
scrise explicit aici — NU calculate dintr-o lista de nume la runtime — ca
tinta pilotului sa fie identica, byte cu byte, indiferent de rulare.

PROVENANCE: nicio pierdere de date. Randurile necanonice raman fizic in
`match_history`, doar marcate. Rollback: `UPDATE match_history SET
superseded_by = NULL, superseded_at = NULL, superseded_reason = NULL WHERE id
IN (...)` — un singur pas, fara nicio reconstructie de date (ADR-059).

Utilizare:
    python scripts/run_identity_reconciliation_pilot.py
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78

# [ADR-025 Faza 3] Cele 6 chei — vezi antetul de mai sus pentru justificare.
# Format: "canon_home||canon_away||kickoff_date", produs de mappings.match_key().
PILOT_TARGET_KEYS: set[str] = {
    "kups||sabah baku||2026-07-28",                      # KuPS vs Sabah Baku
    "lincoln red imps||mjallby||2026-07-28",              # Lincoln Red Imps vs Mjallby
    "maccabi tel aviv||sheriff tiraspol||2026-07-30",     # Maccabi Tel Aviv vs Sheriff Tiraspol
    "ararat-armenia||celje||2026-08-04",                  # Ararat-Armenia vs Celje
    "fenerbahce||sturm graz||2026-08-05",                 # Fenerbahce vs Sturm Graz
    "ferencvaros||gornik zabrze||2026-08-05",             # Ferencvaros vs Gornik Zabrze
}


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from services.match_identity_reconciliation_service import (
        MatchIdentityReconciliationService,
    )

    print(BAR)
    print("  PILOT — reconciliere identitate (ADR-025 Faza 3)")
    print(BAR)
    print(f"  Grupuri tintite: {len(PILOT_TARGET_KEYS)}")
    for k in sorted(PILOT_TARGET_KEYS):
        print(f"    {k}")
    print(BAR)
    print("  Rulez EXECUTE — scrie superseded_by/at/reason DOAR pe randurile")
    print("  necanonice ale grupurilor de mai sus. Randul canonic nu e atins.")
    print(BAR)

    service = MatchIdentityReconciliationService()
    report = service.run(dry_run=False, target_keys=PILOT_TARGET_KEYS)

    print()
    print(BAR)
    print("  REZULTAT PILOT")
    print(BAR)
    print(f"  Grupuri reconciliate din tinta : {len(report.reconciled_group_keys)} / {len(PILOT_TARGET_KEYS)}")
    print(f"  Randuri de marcat              : {report.rows_to_mark}")
    print(f"  Randuri marcate cu succes      : {report.rows_marked_superseded}")
    print(f"  Erori de scriere               : {len(report.write_errors)}")
    print(f"  Chei tintite negasite          : {report.target_keys_not_found}")
    print(BAR)

    if report.reconciled_group_keys:
        print("  Grupuri reconciliate:")
        for k in sorted(report.reconciled_group_keys):
            print(f"    {k}")
        print(BAR)

    if report.write_errors:
        print("  ERORI:")
        for e in report.write_errors:
            print(f"    {e}")
        print(BAR)

    # Esec vizibil (job rosu in Actions) daca oricare din urmatoarele:
    #   - nu toate cele 6 chei tintite au fost gasite ca reconciliabile;
    #   - a existat vreo eroare de scriere;
    #   - numarul de randuri marcate nu coincide cu planul.
    ok = (
        not report.target_keys_not_found
        and not report.write_errors
        and report.rows_marked_superseded == report.rows_to_mark
        and len(report.reconciled_group_keys) == len(PILOT_TARGET_KEYS)
    )
    print("  PILOT REUSIT" if ok else "  PILOT INCOMPLET — vezi detaliile de mai sus")
    print(BAR)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
