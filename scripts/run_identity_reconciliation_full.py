"""
================================================================================
FOOTBALL ORACLE — Reconciliere completa a identitatii (ADR-025 Faza 4)
================================================================================
Module: scripts/run_identity_reconciliation_full.py

SCRIE IN PRODUCTIE. Suprafata exacta, fixata de ADR-059:
`superseded_by`/`superseded_at`/`superseded_reason`, EXCLUSIV pe randul
necanonic al fiecarui grup. Randul canonic nu e atins de niciun octet, nicio
coloana de date nu e scrisa niciodata (garda structurala AST:
tests/test_adr059_reconciliation_is_identity.py).

CE NU FACE: nu redenumeste nimic. Cele ~537 de randuri istorice care poarta un
nume fragmentat FARA sa colizioneze cu un canonic (categoria "D2") raman
neatinse — redenumirea scrie in `home_team`/`away_team`, o suprafata complet
diferita de cea autorizata de ADR-059. Necesita design si aprobare proprii.

PRECONDITIE INDEPLINITA (ADR-025 Faza 3): pilotul pe 6 grupuri a rulat pe
productie (Actions run 32557328800, 2026-08-22) si a fost verificat
independent in baza — 6/6 randuri marcate corect, 0 randuri canonice atinse,
0 coloane de date scrise, 0 pierdere de randuri, 0 erori. Detectia de drift a
confirmat apoi comportamentul asteptat (run 32557539823: 0 grupuri noi, 6
rezolvate, verde).

PROFIL DE IMPACT AL ACESTUI SET (verificat live inainte de rulare, 2026-08-22):
  - 398 randuri necanonice (397 grupuri reconciliabile + 1 grup HARD CONFLICT,
    al carui rand NU va fi scris — mecanismul il exclude automat);
  - TOATE au `actual_result` si `home_elo` — spre deosebire de cele 6 pilotate.
    Deci sunt ACUM in setul de antrenare ML (`get_training_data` filtreaza
    `superseded_by IS NULL`) si in replay-ul ELO (`fetch_all_matches`, idem).
    Marcarea le scoate din ambele: exact efectul urmarit — opreste dubla
    numarare a aceluiasi meci real.
  - 0 copii FK pe randurile necanonice -> zero re-parentare.

CE NU REPARA: valorile ELO deja scrise raman gresite. `run_backfill()` e
NULL-only prin design, deci replay-ul devine corect de acum inainte, dar nu
recalculeaza ce e deja persistat. Reparatia efectiva cere mecanismul de
rebuild proiectat in ADR-059 §"Gol ramas deschis" — operatie separata.

PROVENANCE: nicio pierdere de date. Randurile necanonice raman fizic in
`match_history`, doar marcate. Rollback:
  UPDATE match_history
     SET superseded_by = NULL, superseded_at = NULL, superseded_reason = NULL
   WHERE superseded_at >= '<timestamp-ul rularii>';
Un singur pas, fara nicio reconstructie de date (ADR-059).

Utilizare:
    python scripts/run_identity_reconciliation_full.py
================================================================================
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78


def main() -> int:
    import supabase_client as sb

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    from services.match_identity_reconciliation_service import (
        MatchIdentityReconciliationService,
    )

    print(BAR)
    print("  RECONCILIERE COMPLETA — ADR-025 Faza 4")
    print(BAR)
    print("  Scrie superseded_by/at/reason DOAR pe randurile necanonice.")
    print("  Randul canonic nu e atins. Nicio coloana de date nu e scrisa.")
    print("  Grupurile HARD CONFLICT si cele cu sursa necunoscuta sunt excluse")
    print("  automat de mecanism — nu sunt sarite manual aici.")
    print(BAR)

    service = MatchIdentityReconciliationService()
    report = service.run(dry_run=False)

    print()
    print(BAR)
    print("  REZULTAT")
    print(BAR)
    print(f"  Grupuri duplicate descoperite  : {report.total_groups}")
    print(f"  Grupuri reconciliate           : {report.reconciled_groups}")
    print(f"  Excluse — HARD CONFLICT        : {report.excluded_hard_conflict_count}")
    print(f"  Excluse — sursa necunoscuta    : {report.excluded_unknown_source_count}")
    print(f"  Randuri de marcat (plan)       : {report.rows_to_mark}")
    print(f"  Randuri marcate cu succes      : {report.rows_marked_superseded}")
    print(f"  Erori de scriere               : {len(report.write_errors)}")
    print(BAR)

    if report.excluded_hard_conflict:
        print("  HARD CONFLICT — raman nereconciliate, cer decizie manuala:")
        for k in report.excluded_hard_conflict:
            print(f"    {k}")
        print(BAR)

    if report.write_errors:
        print("  ERORI (marcajul e idempotent — reluarea e sigura):")
        for e in report.write_errors:
            print(f"    {e}")
        print(BAR)

    ok = (
        not report.write_errors
        and report.rows_marked_superseded == report.rows_to_mark
    )
    print("  RECONCILIERE REUSITA" if ok else "  RECONCILIERE INCOMPLETA — vezi erorile")
    print(BAR)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
