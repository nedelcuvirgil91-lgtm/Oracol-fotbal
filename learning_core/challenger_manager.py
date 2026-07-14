"""
================================================================================
FOOTBALL ORACLE — Learning Core: Challenger FSM (Pasul 2, izolat)
================================================================================
Module: learning_core/challenger_manager.py

Singurul modul care scrie în tabela `challengers` — vezi
docs/00_GOVERNANCE/ADR-016-challenger-fsm-bookkeeping.md. Introduce DOAR
starea și tranzițiile unui Challenger (un training_run selectat pentru
evaluare în vederea promovării). Nu implementează Shadow Evaluation,
Promotion, sau citirea Champion/Runtime — nimic altceva.

Modul complet izolat: niciun alt fișier din proiect nu importă acest modul.
Dacă fișierul ar fi șters, restul aplicației funcționează identic — zero
apelanți reali, verificat prin grep.

Spre deosebire de learning_core/model_artifact_storage.py (Pasul 1 —
best-effort, degradare grațioasă, fiindcă rulează în paralel cu un flux deja
garantat de producție), acest modul RIDICĂ excepție la orice eșec de creare
sau tranziție. Corect, fiindcă bookkeeping-ul Challenger e sursa unică de
adevăr a propriei stări — o tranziție care nu se poate confirma nu trebuie
niciodată raportată drept succes tăcut (Regula #8 CLAUDE.md).

── ATENȚIE — tranziția SUCCEEDED → PROMOTED (Pasul 5, ADR-019) ────────────
`transition(training_run_id, "PROMOTED")` rămâne valid aici la nivel de FSM
(ALLOWED_TRANSITIONS) și testat ca atare, dar NU e calea reală de promovare
în producție. O promovare reală se întâmplă EXCLUSIV prin funcția Postgres
`promote_challenger()` (database/migrations/005_promotion.sql), apelată din
`learning_core/promotion_service.py` — acolo, tranziția `challengers.state
= 'PROMOTED'` e scrisă direct în SQL, ATOMIC împreună cu inserarea rândului
`model_champions` corespunzător, în aceeași tranzacție (vezi
docs/04_LEARNING_CORE/ATOMICITY_CONTRACT.md — un `transition()` Python
separat, urmat de o scriere separată în model_champions, NU ar fi atomic).

Apelarea directă a `transition(tid, "PROMOTED")` din orice cod de producție
ar marca un Challenger drept promovat FĂRĂ să creeze rândul `model_champions`
corespunzător — o stare inconsistentă reală. Azi, zero cod de producție face
asta (`promotion_service.py` folosește exclusiv RPC-ul) — funcția rămâne în
ALLOWED_TRANSITIONS doar pentru completitudinea FSM-ului și pentru teste.
================================================================================
"""
from __future__ import annotations

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"WAITING", "REJECTED"},
    "WAITING": {"EVALUATING", "REJECTED"},
    "EVALUATING": {"SUCCEEDED", "REJECTED"},
    "SUCCEEDED": {"PROMOTED", "REJECTED"},
    "PROMOTED": set(),
    "REJECTED": set(),
}

TERMINAL_STATES = {"PROMOTED", "REJECTED"}

VALID_REJECTION_REASONS = {"verdict_negative", "expired", "superseded", "artifact_dead"}


class ChallengerManagerError(Exception):
    """Eșec explicit de creare/tranziție — niciodată aproximat ca succes."""


def create_challenger(training_run_id: str, algorithm_family: str, league_scope: str) -> dict:
    """Creează un Challenger nou, în starea CREATED, pentru training_run_id
    dat. Ridică ChallengerManagerError dacă există deja un Challenger activ
    pentru (algorithm_family, league_scope) — verificat explicit în Python
    pentru un mesaj clar, dar garanția reală împotriva curselor rămâne
    indexul unic parțial din baza de date (idx_challengers_active_unique);
    dacă verificarea din Python trece dar scrierea e respinsă concurent de
    acel index, eroarea reflectă tot un eșec real, nu un fals succes."""
    import supabase_client as sb

    existing_active = sb.get_active_challenger(algorithm_family, league_scope)
    if existing_active is not None:
        raise ChallengerManagerError(
            f"există deja un Challenger activ pentru "
            f"(algorithm_family={algorithm_family!r}, league_scope={league_scope!r}): "
            f"training_run_id={existing_active['training_run_id']!r}, "
            f"state={existing_active['state']!r}"
        )

    created = sb.create_challenger(training_run_id, algorithm_family, league_scope)
    if created is None:
        raise ChallengerManagerError(
            f"crearea Challenger-ului a eșuat pentru training_run_id={training_run_id!r} "
            "(Supabase indisponibil, sau constrângerea de invariant a respins scrierea "
            "la nivel de bază de date)"
        )
    return created


def transition(training_run_id: str, to_state: str, rejection_reason: str | None = None) -> dict:
    """Tranziționează Challenger-ul identificat prin training_run_id în
    to_state, doar dacă tranziția e validă din starea curentă. Scrierea
    propriu-zisă e un compare-and-swap la nivel de bază de date
    (UPDATE ... WHERE state = starea_citită) — dacă starea s-a schimbat
    concurent între citire și scriere, tranziția eșuează explicit, nu se
    aplică orbește peste o presupunere învechită."""
    if to_state not in ALLOWED_TRANSITIONS:
        raise ChallengerManagerError(f"stare necunoscută: {to_state!r}")

    if to_state == "REJECTED":
        if rejection_reason not in VALID_REJECTION_REASONS:
            raise ChallengerManagerError(
                f"rejection_reason invalid: {rejection_reason!r} "
                f"(trebuie să fie unul din {sorted(VALID_REJECTION_REASONS)})"
            )
    elif rejection_reason is not None:
        raise ChallengerManagerError(
            "rejection_reason e permis doar la tranziția către REJECTED"
        )

    import supabase_client as sb

    current = sb.get_challenger(training_run_id)
    if current is None:
        raise ChallengerManagerError(
            f"niciun Challenger găsit pentru training_run_id={training_run_id!r}"
        )

    from_state = current["state"]
    if to_state not in ALLOWED_TRANSITIONS[from_state]:
        raise ChallengerManagerError(
            f"tranziție invalidă: {from_state} -> {to_state} "
            f"(permise din {from_state}: {sorted(ALLOWED_TRANSITIONS[from_state]) or 'nimic (stare terminală)'})"
        )

    updated = sb.update_challenger_state(
        training_run_id=training_run_id,
        expected_current_state=from_state,
        new_state=to_state,
        rejection_reason=rejection_reason,
        terminal=(to_state in TERMINAL_STATES),
    )
    if not updated:
        raise ChallengerManagerError(
            f"tranziția {from_state} -> {to_state} pentru training_run_id={training_run_id!r} "
            "a eșuat: starea s-a schimbat concurent (compare-and-swap), sau Supabase indisponibil"
        )

    return sb.get_challenger(training_run_id)


def get_challenger(training_run_id: str) -> dict | None:
    import supabase_client as sb
    return sb.get_challenger(training_run_id)


def get_active_challenger(algorithm_family: str, league_scope: str) -> dict | None:
    import supabase_client as sb
    return sb.get_active_challenger(algorithm_family, league_scope)
