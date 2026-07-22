"""
================================================================================
FOOTBALL ORACLE — Learning Core: Rollback Service (Stage R1.3)
================================================================================
Module: learning_core/rollback_service.py

Owner exclusiv al evenimentului de domeniu „Rollback Champion" — simetric cu
`promotion_service.py`, dar SEPARAT (vezi ADR-037: Rollback NU e opusul
Promotion — Promotion schimbă campionul fiindcă un alt model e mai bun;
Rollback îl schimbă fiindcă modelul curent nu mai e de încredere). Un singur
use-case, un singur punct de intrare public (`rollback_champion()`).

── Rollback execută, nu decide ─────────────────────────────────────────────
Decizia (sănătatea campionului, verdictul de degradare) e complet încheiată
înainte ca acest modul să fie invocat — în R1 rollback-ul e declanșat MANUAL
(operator/emergency), iar în R2/R3 va fi propus de Champion Guardian și aprobat
uman (T3a). Acest modul NU evaluează sănătatea, NU rulează teste statistice,
NU recalculează nimic — verifică EXCLUSIV precondiții structurale (există/valid)
și execută.

── Diviziunea Python vs. tranzacție Postgres (ATOMICITY_CONTRACT) ───────────
Precondițiile (citirea predecesorului, validarea artefactului lui) rulează
aici, în Python, ÎNAINTE de orice scriere — la primul eșec, zero apel RPC.
Cele două efecte cuplate (supersedarea campionului activ + reactivarea
predecesorului printr-un rând nou) sunt aplicate de UN singur apel RPC
(`rollback_champion`, migrarea 014) — o singură tranzacție Postgres, fie
ambele efecte, fie niciunul. Validarea artefactului rămâne în Python fiindcă
SQL nu poate deserializa un model XGBoost.

── Compare-and-Swap (audit pre-R1) ─────────────────────────────────────────
Predecesorul validat aici (al cărui artefact e verificat funcțional) e
transmis RPC-ului ca `expected_predecessor_training_run_id`. RPC-ul re-derivă
predecesorul server-side sub lock și îl compară — dacă starea s-a schimbat
concurent (ex. o promovare între citire și RPC), refuză (`predecessor_mismatch`),
zero scriere. Astfel artefactul validat e EXACT cel activat, sau operația e
respinsă (retry). Elimină complet TOCTOU-ul validare-Python → execuție-RPC.

── Idempotență (secvențial vs. concurent) ──────────────────────────────────
Secvențial (re-apel după un rollback încheiat): campionul activ e deja
predecesorul → `already_active`, curat. Concurent (două rollback-uri simultane):
garanția tare e SIGURANȚA (lock + index parțial unic → un singur câștigător,
zero dublă-scriere); pierzătorul poate primi `rejected` și trebuie să reia —
vezi CHAMPION_GUARDIAN_IMPLEMENTATION.md §11.

De la Stage R3.2A (ADR-037), `continuous_learning.py` importă acest modul —
pentru `is_rollback_promoted()` (citire de clasificare, gardă anti-ping-pong),
`VALID_ROLLBACK_REASONS` (validarea motivului mapat din sănătate), și — de
la Stage R3.2B — `rollback_champion()` însuși, apelat DOAR din Faza C
(execuția unei decizii T3a deja aprobate de om), întotdeauna cu
`expected_predecessor_training_run_id` explicit (ținta înghețată în
`evidence` la propunere, R3.2A.1 — vezi Execution Contract, ADR-037).
Rollback Service rămâne simplu și decuplat: nu citește niciodată
`decision_feed` direct, primește doar valori. Nu e wired în
`sync/run_daily.py` sau `oracle_engine.py`.

Depinde de două funcții de acces din `supabase_client` livrate la R1.4
(`get_champion_predecessor`, `rpc_rollback_champion`) — importate lazy, în
interiorul funcției, exact ca tiparul din `promotion_service.py`.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("FootballOracle.LearningCore.RollbackService")

# Setul închis de motive (ADR-037 §4). Validat aici (fail-fast, mesaj clar)
# ȘI server-side în RPC (defense-in-depth) — niciodată doar într-un singur loc.
VALID_ROLLBACK_REASONS = {
    "regression", "artifact_missing", "model_error",
    "data_error", "operator", "emergency",
}


@dataclass
class RollbackResult:
    status: str  # "rolled_back" | "already_active" | "rejected"
    reason: str | None = None
    predecessor_training_run_id: str | None = None


def rollback_champion(
    algorithm_family: str, league_scope: str, reason: str, rolled_back_by: str,
    expected_predecessor_training_run_id: str | None = None,
) -> RollbackResult:
    """Execută evenimentul „Rollback Champion" pentru `(algorithm_family,
    league_scope)` — reactivează un predecesor, dacă și numai dacă toate
    precondițiile structurale sunt satisfăcute. Niciodată nu ridică excepție
    către apelant — orice eșec (precondiție nesatisfăcută, Supabase
    indisponibil, cursă concurentă, eroare neașteptată) se întoarce ca
    `RollbackResult(status="rejected", reason=...)`.

    `reason` ∈ VALID_ROLLBACK_REASONS. `rolled_back_by` = identitatea celui
    care declanșează (obligatorie pentru trasabilitate; ajunge în
    `model_champions.promoted_by` ca `rollback:<motiv>:<by>`).

    `expected_predecessor_training_run_id` (opțional — Execution Contract,
    ADR-037, R3.2A.1/R3.2B): ținta CAS ÎNGHEȚATĂ la propunere. Dacă
    transmisă, e folosită DIRECT ca predecesor așteptat — NU se re-derivă
    dinamic din campionul activ curent. Obligatorie pentru orchestrarea
    automată (R3.2B: execuția unei decizii T3a deja aprobate) — fără ea,
    un retry peste timp (ex. proces mort între RPC și confirmarea deciziei)
    ar recalcula un predecesor diferit dintr-o stare deja schimbată,
    producând un rollback în lanț neintenționat. Dacă omisă (None,
    implicit), comportamentul rămâne cel din R1: predecesorul e derivat
    dinamic din campionul activ CURENT — corect pentru declanșare manuală
    (operator/CLI), unde „acum" chiar e intenția reală."""
    try:
        if reason not in VALID_ROLLBACK_REASONS:
            return RollbackResult(
                status="rejected",
                reason=f"motiv invalid: {reason!r} (trebuie unul din {sorted(VALID_ROLLBACK_REASONS)})",
            )

        import supabase_client as sb

        if expected_predecessor_training_run_id is not None:
            # Ținta e ÎNGHEȚATĂ (frozen la propunere) — folosită direct,
            # niciodată re-derivată. Sămânța CAS e chiar valoarea primită.
            predecessor_training_run_id = expected_predecessor_training_run_id
        else:
            # Precondiție (cale manuală, R1, neschimbată): campionul activ
            # are un predecesor la care să revină. get_champion_predecessor
            # întoarce training_run_id-ul predecesorului (rândul supersedat
            # de campionul activ), sau None dacă nu există campion activ ori
            # nu are predecesor (primul campion) — R1.4.
            predecessor_training_run_id = sb.get_champion_predecessor(algorithm_family, league_scope)
            if predecessor_training_run_id is None:
                return RollbackResult(
                    status="rejected",
                    reason=(
                        f"niciun predecesor pentru revenire la ({algorithm_family!r}, {league_scope!r}) "
                        "— fie nu există campion activ, fie campionul activ a fost primul (fără predecesor), "
                        "fie Supabase indisponibil (get_champion_predecessor a întors None)"
                    ),
                )

        # Precondiție: artefactul predecesorului e re-validat funcțional —
        # nu readucem un campion care e el însuși mort. ÎNAINTE de orice
        # scriere (ATOMICITY_CONTRACT).
        artifact_error = _validate_artifact(predecessor_training_run_id)
        if artifact_error is not None:
            return RollbackResult(
                status="rejected",
                predecessor_training_run_id=predecessor_training_run_id,
                reason=artifact_error,
            )

        # UN singur apel RPC — cele două efecte, atomic. Predecesorul validat
        # devine `expected_predecessor` (sămânța CAS). Excepția server-side
        # (precondiție structurală eșuată, predecessor_mismatch, cursă) e
        # lăsată de wrapper să urce și e prinsă aici, mapată la `rejected`.
        try:
            rpc_status = sb.rpc_rollback_champion(
                algorithm_family, league_scope,
                predecessor_training_run_id, reason, rolled_back_by,
            )
        except Exception as exc:
            return RollbackResult(
                status="rejected",
                predecessor_training_run_id=predecessor_training_run_id,
                reason=str(exc),
            )

        if rpc_status not in ("rolled_back", "already_active"):
            return RollbackResult(
                status="rejected",
                predecessor_training_run_id=predecessor_training_run_id,
                reason=f"răspuns neașteptat de la rollback_champion: {rpc_status!r}",
            )

        return RollbackResult(
            status=rpc_status,
            predecessor_training_run_id=predecessor_training_run_id,
        )
    except Exception as exc:
        logger.warning("[RollbackService] rollback_champion eșuat pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return RollbackResult(status="rejected", reason=str(exc))


def is_rollback_promoted(champion: dict | None) -> bool:
    """Singurul loc din proiect care interpretează formatul `promoted_by`
    pentru a decide dacă un campion a fost activat printr-un rollback (nu
    printr-o promovare normală). Owner semantic: acest modul produce
    evenimentul de rollback (RPC 014 setează `promoted_by =
    'rollback:'||reason||':'||by`) — deci tot el deține interpretarea
    formatului. Niciun alt fișier (ex. `continuous_learning.py`) nu are voie
    să parseze/verifice `promoted_by` direct — dacă formatul se schimbă
    vreodată, se modifică o singură funcție, aici.

    Folosit de orchestrarea Champion Guardian (R3.2, gardă anti-ping-pong):
    un campion deja reactivat prin rollback care s-ar degrada din nou NU
    trebuie să declanșeze automat un al doilea rollback (ar reveni la
    predecesorul deja abandonat ca degradat — ping-pong). Lanțul automat e
    plafonat la un singur pas (ADR-037 §14 — rollback în lanț = Future Work);
    pasul doi necesită intervenție manuală de operator."""
    if not champion:
        return False
    promoted_by = champion.get("promoted_by")
    return isinstance(promoted_by, str) and promoted_by.startswith("rollback:")


def _validate_artifact(training_run_id: str) -> str | None:
    """Re-validare funcțională a artefactului predecesorului — nu doar
    „fișierul există", ci un test real de inferență (predict_proba pe un rând
    -sondă). None dacă validarea reușește, mesajul de eroare altfel. Identic
    ca tipar cu `promotion_service._validate_artifact`."""
    try:
        from learning_core import model_artifact_storage

        model = model_artifact_storage.load_model_artifact(training_run_id)
        if model is None:
            return (
                f"artefactul predecesorului {training_run_id!r} nu a putut fi încărcat "
                "(lipsă, corupt, sau Supabase indisponibil) — nu se reactivează un campion mort"
            )

        import numpy as np
        from ml_predictor import FEATURE_COLUMNS

        probe = np.zeros((1, len(FEATURE_COLUMNS)))
        model.predict_proba(probe)
        return None
    except Exception as exc:
        return f"artefactul predecesorului {training_run_id!r} nu produce predicții valide: {exc}"
