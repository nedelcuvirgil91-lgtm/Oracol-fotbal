"""
================================================================================
FOOTBALL ORACLE — Learning Core: Shadow Evaluation pentru Challenger activ
(Pasul 4, Implementation Contract) — vezi ADR-018
================================================================================
Module: learning_core/challenger_evaluation.py

Produce EXCLUSIV un verdict determinist, derivat din rezultate reale deja
acumulate în shadow_predictions/match_history (prin
shadow_testing.evaluate_experiment(), infrastructură generică deja
existentă, complet neschimbată), și îl persistă ca FAPT ISTORIC IMUABIL în
`challenger_evaluations` — nimic altceva.

Nu modifică Runtime, Champion, sau Challenger FSM. Nu declanșează
Promotion. `challenger_manager.transition()` NU e apelat de acest modul —
un verdict `candidate_for_promotion` e doar informație persistată, nu o
acțiune asupra stării Challenger-ului (promovarea reală rămâne un pas
viitor, separat, explicit — Pasul 5).

Complet izolat: niciun alt fișier din proiect nu importă acest modul —
zero apelanți reali, la fel ca Pasul 1/2. Nu e wired în sync/run_daily.py.

── Imuabilitate (cerința explicită a Chief Architect Review) ─────────────
Odată calculat pentru un training_run_id și o fereastră de evaluare dată
(n_matches_evaluated), un verdict NU se recalculează și NU se schimbă la o
rerulare ulterioară a job-ului — garantat la nivel de bază de date, nu doar
prin convenție de cod: `challenger_evaluations` are UNIQUE
(training_run_id, n_matches_evaluated), iar scrierea folosește
`ignore_duplicates=True` (ON CONFLICT DO NOTHING la nivel Postgres). O
rerulare cu aceeași fereastră e un no-op garantat. O fereastră NOUĂ (mai
multe meciuri acumulate între timp) produce un rând NOU, distinct — un fapt
nou, nu o corecție a celui vechi. O corecție reală (ex. bug descoperit în
testul statistic) ar necesita o acțiune explicită separată (nu simpla
rerulare a job-ului obișnuit de evaluare).
================================================================================
"""
from __future__ import annotations

import logging

logger = logging.getLogger("FootballOracle.LearningCore.ChallengerEvaluation")

_VALID_VERDICTS = {"candidate_for_promotion", "rejected", "monitoring", "insufficient_data"}


def evaluate_active_challenger(
    algorithm_family: str, league_scope: str,
    min_matches: int = 200, statistical_method: str = "paired_bootstrap",
) -> dict | None:
    """Evaluează Challenger-ul activ (dacă există) pentru
    (algorithm_family, league_scope) și persistă verdictul ca fapt istoric
    imuabil. None dacă nu există Challenger activ, sau la orice eșec
    (Supabase indisponibil, eroare în shadow_testing) — niciodată excepție
    propagată către apelant (Regula #8, degradare grațioasă)."""
    try:
        from learning_core import challenger_manager

        active = challenger_manager.get_active_challenger(algorithm_family, league_scope)
        if active is None:
            return None

        import shadow_testing

        result = shadow_testing.evaluate_experiment(
            experiment_name=algorithm_family, experiment_version=active["training_run_id"],
            league_scope=league_scope, min_matches=min_matches, statistical_method=statistical_method,
        )
        if result is None:
            return None

        _persist_immutable_verdict(
            active["training_run_id"], algorithm_family, league_scope, statistical_method, result,
        )
        return result
    except Exception as exc:
        logger.warning("[ChallengerEvaluation] evaluate_active_challenger eșuat: %s", exc)
        return None


def _persist_immutable_verdict(
    training_run_id: str, algorithm_family: str, league_scope: str,
    default_statistical_method: str, result: dict,
) -> bool:
    verdict = result.get("status")
    if verdict not in _VALID_VERDICTS:
        logger.warning("[ChallengerEvaluation] verdict necunoscut, nu se persistă: %r", verdict)
        return False

    import supabase_client as sb

    return sb.record_challenger_evaluation(
        training_run_id=training_run_id, algorithm_family=algorithm_family, league_scope=league_scope,
        n_matches_evaluated=result.get("n_matches_evaluated", 0),
        evaluation_window_start=result.get("evaluation_window_start"),
        evaluation_window_end=result.get("evaluation_window_end"),
        verdict=verdict,
        statistical_method=result.get("statistical_method", default_statistical_method),
        brier_baseline=result.get("brier_baseline"), brier_experiment=result.get("brier_experiment"),
        delta_brier=result.get("delta_brier"), brier_significant=result.get("brier_significant"),
        logloss_baseline=result.get("logloss_baseline"), logloss_experiment=result.get("logloss_experiment"),
        delta_logloss=result.get("delta_logloss"), logloss_significant=result.get("logloss_significant"),
        accuracy_baseline=result.get("accuracy_baseline"), accuracy_experiment=result.get("accuracy_experiment"),
        delta_accuracy=result.get("delta_accuracy"), accuracy_significant=result.get("accuracy_significant"),
    )
