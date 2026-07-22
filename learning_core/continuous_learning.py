"""
================================================================================
FOOTBALL ORACLE — Learning Core: Continuous Learning (ADR-030)
================================================================================
Module: learning_core/continuous_learning.py

Implementează exact contractul înghețat prin ADR-030:
docs/00_GOVERNANCE/ADR-030-continuous-learning.md

Funcție DECUPLATĂ de sync/run_daily.py — nu un pas al lui, nu un subsistem
nou. Nu reimplementează nimic din mecanica deja existentă (Model Registry,
Training Runner, Challenger FSM, Statistics Engine, Promotion Service) —
decide exclusiv CÂND se apelează fiecare bucată deja construită.

Patru faze, independente, idempotente, sigure la rerulare — pentru fiecare
(algorithm_family, league_scope) din Model Registry, la fiecare invocare:

  A. Monitorizare — există deja un Challenger activ? -> verifică verdictul
     de evaluare (shadow logging acumulat din trafic live, nu sintetic).
  B. Antrenare — nu există Challenger activ? -> verifică pragul de volum,
     antrenează unul nou dacă e atins.
  D. Sănătatea campionului (ADR-037, Stage R3.1) — evaluează campionul ACTIV
     prin Champion Guardian și jurnalizează rezultatul. STRICT READ-ONLY în
     R3.1: nu propune nicio decizie T3a, nu apelează serviciul de rollback —
     doar demonstrează integrarea Guardian în buclă, fără efect de decizie.
     Propunerea de rollback e R3.2, neimplementată încă.
  C. Execuție — există decizii T3a aprobate de om, neexecutate încă? ->
     finalizează promovarea (fără coadă/scheduler nou — aceeași rulare
     periodică acoperă și acest caz).

Gardă de consistență (cerută explicit, precondiție pentru A/B): NU se
reutilizează supabase_client.get_active_challenger() (care ia tăcut
rows[0] dacă ar exista mai mulți) — se numără independent Challengerii
activi; dacă invariantul "cel mult unul" (index unic parțial
idx_challengers_active_unique) pare încălcat, se raportează T2 de eroare
și NU se continuă — fără antrenare, fără tranziții, fără alegere arbitrară.

Fereastra pre-ADR-034 (acceptată explicit, per Clarification Pass ADR-030):
orice decizie T3a propusă aici poartă `correction_method="none — pre-ADR-034"`
până la livrarea ADR-034.
================================================================================
"""
from __future__ import annotations

import logging

import automation_runs as ar
import supabase_client as sb
from database.queries import get_client
from learning_core import challenger_evaluation, challenger_manager, champion_guardian, model_registry
from learning_core.promotion_service import promote_challenger
from learning_core.training_runner import run_training
from ml_predictor import MIN_SAMPLES_TO_TRAIN

logger = logging.getLogger("FootballOracle.LearningCore.ContinuousLearning")

PRODUCER = "ADR-030"
MIN_MATCHES_FOR_EVALUATION = 200
_DEFAULT_CONFIG = {"learning_core_enabled": False}

# TTL provizoriu pentru deciziile T3a de promovare — valoare de implementare,
# nu decizie de arhitectură (per Open Question ADR-030, netratată ca blocantă).
_PROMOTION_DECISION_TTL_HOURS = 168.0  # 7 zile


def is_enabled() -> bool:
    """learning_core_enabled — nume păstrat din documentul de proiectare
    vechi, SENS COMPLET REDEFINIT (ADR-030): activează exclusiv verificarea
    de prag decuplată, independentă de run_daily.py — nu un pas al lui.
    Implicit False (P1 — nimic nou pornește implicit activ)."""
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("learning_core_enabled", False))


def run_cycle() -> dict:
    """Punctul de intrare public — un ciclu complet peste tot Model
    Registry-ul. Sigur de rerulat oricând (idempotent pe toate cele trei
    faze) — declanșatorul extern (ex. GitHub Actions, programat, decuplat
    de daily.yml) nu are nevoie de nicio garanție suplimentară.

    Nu apelează register_default_algorithms() — exact tiparul deja folosit
    de learning_core/train.py: populate registry-ul e responsabilitatea
    apelantului (CLI/script de workflow), nu a funcției de orchestrare (o
    funcție pură nu trebuie să aibă efecte laterale de import ascunse)."""
    if not is_enabled():
        logger.info("[ContinuousLearning] learning_core_enabled=False — ciclu sarit complet.")
        return {"enabled": False}

    summary = {
        "enabled": True, "checked": 0, "trained": 0, "evaluated": 0,
        "proposed": 0, "committed": 0, "guard_failures": 0,
        "health_checked": 0,
    }

    for name, version in model_registry.list_available():
        algorithm = model_registry.get(name, version)
        family, league = algorithm.name, algorithm.league_scope
        summary["checked"] += 1
        try:
            _process_pair(family, league, algorithm, version, summary)
        except Exception as exc:
            logger.error("[ContinuousLearning] eroare neasteptata pentru %s/%s: %s", family, league, exc)

    return summary


def _process_pair(family: str, league: str, algorithm, version: str, summary: dict) -> None:
    target_key = f"{family}|{league}"

    # [ADR-028] Descoperire de reconnaissance, nu presupusă: nu orice algoritm
    # din Model Registry e Challenger-compatibil — lanțul shadow/promotion e
    # construit peste artefacte XGBoost (model_artifact_storage.py). Un
    # algoritm care declară explicit participates_in_challenger_framework=False
    # (ex. league_weights_adaptive) e sărit complet aici — altfel Faza B ar
    # crea un Challenger "zombie", fără nicio cale spre evaluare reală, care
    # ar ocupa la nesfârșit slotul "cel mult un Challenger activ". Implicit
    # True — comportamentul existent (xgboost_v1, production_champion) rămâne
    # neschimbat.
    if not algorithm.describe().get("participates_in_challenger_framework", True):
        return

    active_count = sb.count_active_challengers(family, league)
    if active_count not in (0, 1):
        run_id = ar.write_run(PRODUCER, "consistency_guard", "T1", target_key=target_key)
        if run_id:
            ar.start_run(run_id)
            ar.fail_run(
                run_id,
                f"anomalie de infrastructura: {active_count} challengeri activi (asteptat 0 sau 1) "
                f"pentru ({family}, {league}) - indexul unic idx_challengers_active_unique pare "
                "incalcat. Fara antrenare, fara tranzitii - necesita interventie manuala.",
            )
        summary["guard_failures"] += 1
        logger.error(
            "[ContinuousLearning] GARDA DE CONSISTENTA INCALCATA: %s challengeri activi pentru %s/%s",
            active_count, family, league,
        )
        return

    if active_count == 1:
        _phase_a_monitor_existing(family, league, target_key, summary)
    else:
        _phase_b_train_new(family, league, algorithm, version, target_key, summary)

    _phase_d_champion_health(family, league, target_key, summary)
    _phase_c_execute_approved(target_key, summary)


# ════════════════════════════════════════════════════════════════════════
# Faza A — monitorizare Challenger existent
# ════════════════════════════════════════════════════════════════════════

def _phase_a_monitor_existing(family: str, league: str, target_key: str, summary: dict) -> None:
    run_id = ar.write_run(PRODUCER, "challenger_evaluation_check", "T2", target_key=target_key)
    if run_id is None:
        return
    ar.start_run(run_id)

    result = challenger_evaluation.evaluate_active_challenger(
        family, league, min_matches=MIN_MATCHES_FOR_EVALUATION,
    )
    if result is None:
        ar.skip_run(run_id, "niciun verdict inca — insuficiente esantioane acumulate din trafic live, sau eroare degradata")
        return

    summary["evaluated"] += 1
    verdict = result.get("status")
    active = challenger_manager.get_active_challenger(family, league)
    training_run_id = active["training_run_id"] if active else None

    if verdict == "candidate_for_promotion" and training_run_id:
        _handle_candidate_for_promotion(run_id, training_run_id, target_key, result, summary)
    elif verdict == "rejected" and training_run_id:
        _handle_rejected_verdict(run_id, training_run_id, result)
    else:
        # monitoring / insufficient_data — legitim, fara actiune
        ar.complete_run(run_id, summary={"verdict": verdict, "n_matches_evaluated": result.get("n_matches_evaluated")})


def _handle_candidate_for_promotion(
    run_id: int, training_run_id: str, target_key: str, result: dict, summary: dict,
) -> None:
    try:
        challenger_manager.transition(training_run_id, "SUCCEEDED")
    except challenger_manager.ChallengerManagerError as exc:
        ar.fail_run(run_id, f"tranzitie SUCCEEDED esuata: {exc}")
        return

    ar.complete_run(run_id, summary={"verdict": "candidate_for_promotion", "training_run_id": training_run_id})

    decision_run_id = ar.write_run(PRODUCER, "promotion_candidate", "T3a", target_key=target_key)
    if decision_run_id is None:
        return
    ar.start_run(decision_run_id)
    ar.complete_run(decision_run_id)

    evidence = dict(result)
    evidence["training_run_id"] = training_run_id  # necesar pentru Faza C

    decision_id = ar.propose_decision(
        decision_run_id, tier="T3a",
        rollback_plan="revert la campionul anterior din model_champions (supersede automat de promote_challenger)",
        evidence=evidence,
        correction_method="none — pre-ADR-034",
        ttl_hours=_PROMOTION_DECISION_TTL_HOURS,
    )
    if decision_id:
        ar.surface_decision(decision_id)
        summary["proposed"] += 1


def _handle_rejected_verdict(run_id: int, training_run_id: str, result: dict) -> None:
    try:
        challenger_manager.transition(training_run_id, "REJECTED", rejection_reason="verdict_negative")
    except challenger_manager.ChallengerManagerError as exc:
        ar.fail_run(run_id, f"tranzitie REJECTED esuata: {exc}")
        return
    ar.complete_run(run_id, summary={"verdict": "rejected", "training_run_id": training_run_id})


# ════════════════════════════════════════════════════════════════════════
# Faza B — antrenare Challenger nou
# ════════════════════════════════════════════════════════════════════════

def _phase_b_train_new(family: str, league: str, algorithm, version: str, target_key: str, summary: dict) -> None:
    run_id = ar.write_run(PRODUCER, "threshold_check", "T2", target_key=target_key)
    if run_id is None:
        return
    ar.start_run(run_id)

    last_run = sb.get_latest_training_run(family, league)
    if last_run is None:
        n_matches = _count_finished_matches(league)
        should_train = n_matches >= MIN_SAMPLES_TO_TRAIN
        reason = f"prima antrenare — {n_matches} meciuri disponibile (prag {MIN_SAMPLES_TO_TRAIN})"
    else:
        n_new = _count_finished_matches(league, since=last_run.get("created_at"))
        should_train = n_new >= MIN_SAMPLES_TO_TRAIN
        reason = f"{n_new} meciuri noi de la ultima antrenare (prag {MIN_SAMPLES_TO_TRAIN})"

    if not should_train:
        ar.skip_run(run_id, f"prag de volum neatins ({reason})")
        return
    ar.complete_run(run_id, summary={"decision": "train", "reason": reason})

    train_run_id = ar.write_run(PRODUCER, "training_run", "T2", target_key=target_key)
    if train_run_id is None:
        return
    ar.start_run(train_run_id)

    try:
        report = run_training(algorithm.name, version)
    except Exception as exc:
        ar.fail_run(train_run_id, f"run_training a esuat: {exc}")
        return

    summary["trained"] += 1
    if report.result.status != "trained":
        ar.complete_run(train_run_id, summary={"status": report.result.status, "message": report.result.message})
        return

    ar.complete_run(train_run_id, summary={
        "training_run_id": report.result.training_run_id,
        "samples_used": report.result.samples_used,
    })

    try:
        challenger_manager.create_challenger(report.result.training_run_id, family, league)
        challenger_manager.transition(report.result.training_run_id, "WAITING")
        challenger_manager.transition(report.result.training_run_id, "EVALUATING")
    except challenger_manager.ChallengerManagerError as exc:
        logger.error(
            "[ContinuousLearning] crearea/tranzitia Challenger-ului a esuat pentru %s: %s",
            report.result.training_run_id, exc,
        )


def _count_finished_matches(league: str, since: str | None = None) -> int:
    """Meciuri terminate (actual_result cunoscut), opțional doar cele mai noi
    decât `since`. Read-only, nu atinge nicio scriere.

    [Descoperit prin observare pre-activare learning_core_enabled, corectat
    generic] `league="all"` e SENTINELUL folosit de league_scope pentru "nu
    e restrâns la o singură ligă" (valoarea league_scope a tuturor
    algoritmilor înregistrați azi) — NU o valoare reală din coloana
    match_history.league (care conține "Premier League", "La Liga", etc.).
    Fără acest tratament, .eq("league", "all") nu s-ar potrivi niciodată cu
    vreun rând real, iar Faza B nu ar porni NICIODATĂ o antrenare automată
    pentru un algoritm cu league_scope="all", indiferent de câte meciuri
    există. Tratat generic (pe valoare, nu pe nume de algoritm) — pentru o
    ligă reală, filtrul .eq() rămâne exact ca înainte."""
    client = get_client()
    if client is None:
        return 0
    try:
        q = client.table("match_history").select("id").not_.is_("actual_result", "null")
        if league != "all":
            q = q.eq("league", league)
        if since:
            q = q.gt("created_at", since)
        res = q.execute()
        return len(res.data or [])
    except Exception as exc:
        logger.error("[ContinuousLearning] _count_finished_matches esuat pentru %s: %s", league, exc)
        return 0


# ════════════════════════════════════════════════════════════════════════
# Faza D — sănătatea campionului activ (Champion Guardian, ADR-037 R3.1)
# ════════════════════════════════════════════════════════════════════════

def _phase_d_champion_health(family: str, league: str, target_key: str, summary: dict) -> None:
    """R3.1 — integrare STRICT READ-ONLY a Champion Guardian în buclă:
    evaluează sănătatea campionului activ (evaluate_champion_health, care
    persistă intern faptul de sănătate, neatins aici) și jurnalizează
    rezultatul într-un automation_run. NU propune nicio decizie T3a, NU
    apelează serviciul de rollback — scope strict, impus și mecanic (vezi
    tests/test_continuous_learning_rollback.py). Propunerea de rollback
    e Stage R3.2, neimplementată încă."""
    run_id = ar.write_run(PRODUCER, "champion_health_check", "T2", target_key=target_key)
    if run_id is None:
        return
    ar.start_run(run_id)

    result = champion_guardian.evaluate_champion_health(family, league)
    if result is None:
        ar.skip_run(run_id, "niciun campion activ pentru evaluarea de sanatate")
        return

    summary["health_checked"] += 1
    ar.complete_run(run_id, summary={
        "health_state": result.health_state,
        "recommends_rollback": result.recommends_rollback,
        "reason": result.reason,
    })


# ════════════════════════════════════════════════════════════════════════
# Faza C — execuție a promovărilor deja aprobate de om
# ════════════════════════════════════════════════════════════════════════

def _phase_c_execute_approved(target_key: str, summary: dict) -> None:
    for decision in ar.list_approved_decisions_for_target(target_key):
        evidence = decision.get("evidence") or {}
        training_run_id = evidence.get("training_run_id")
        if not training_run_id:
            ar.fail_decision_commit(decision["id"], "evidence fara training_run_id — nu se poate executa promovarea")
            continue

        family, league = target_key.split("|", 1)
        result = promote_challenger(
            training_run_id=training_run_id, algorithm_family=family,
            league_scope=league, promoted_by="ADR-030-continuous-learning",
        )
        if result.status in ("promoted", "already_active"):
            ar.commit_decision(decision["id"])
            summary["committed"] += 1
        else:
            ar.fail_decision_commit(decision["id"], f"promote_challenger: {result.status} — {result.reason}")
