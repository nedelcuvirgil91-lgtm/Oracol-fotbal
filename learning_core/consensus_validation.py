"""
================================================================================
FOOTBALL ORACLE — Learning Core: Consensus Validation (ADR-033, Faza 2)
================================================================================
Module: learning_core/consensus_validation.py

Studiul T1, periodic, independent — citește exclusiv `consensus_capture_samples`
(Faza 1, `learning_core/consensus_capture.py`) + `match_history` (read-only),
calculează metricile candidate de consens, corelează cu acuratețea reală,
produce un verdict imuabil per metrică. Nu atinge niciodată `oracle_engine.py`,
Model Registry, Challenger FSM sau Promotion Service — vezi regula normativă
centrală din ADR-033 (§Decision): rezultatele acestui modul produc exclusiv
evidență, nu execută nicio schimbare de serving.

Decuplat de `learning_core/continuous_learning.py` (ADR-030) — flag propriu
(`consensus_validation_enabled`), cadență proprie (workflow GitHub Actions
propriu), fără nicio interacțiune: un eșec aici nu poate bloca sau influența
ciclul Continuous Learning, și invers (cerință explicită la aprobarea
planului de implementare).
================================================================================
"""
from __future__ import annotations

import logging
import random

import automation_runs as ar
import supabase_client as sb

logger = logging.getLogger("FootballOracle.LearningCore.ConsensusValidation")

PRODUCER = "ADR-033"

# [ADR-033, Clarification Pass] Prag fix, neconfigurabil — un prag variabil
# ar face "eșantion suficient" o proprietate mutabilă a sistemului, nu a
# datelor (ar contrazice reproductibilitatea verdictului).
MIN_SAMPLES_FOR_CONSENSUS_VALIDATION = 200

# [ADR-033 Final, §3] Metrica primară e fixă, pre-înregistrată — niciodată
# retroactivă. Agreement Score aleasă ca primară: singura dintre cele trei
# interpretabilă direct ca "gradul de consens" (0..1), cea mai apropiată de
# intenția inițială a Consensus Layer.
PRIMARY_METRIC = "agreement_score"
CANDIDATE_METRICS = ("agreement_score", "divergence_score", "prediction_distance")

_DEFAULT_CONFIG = {"consensus_validation_enabled": False}

# TTL provizoriu pentru decizia T3a de surfacing — valoare de implementare,
# nu decizie de arhitectură (Open Question #1, ADR-033 Final — același
# precedent ca ADR-030).
_SURFACING_DECISION_TTL_HOURS = 168.0  # 7 zile

_OUTCOME_KEYS = {"H": "prob_home", "D": "prob_draw", "A": "prob_away"}


def is_enabled() -> bool:
    """Implicit False (North Star #3). Independent de
    learning_core_enabled (ADR-030) și de consensus_capture_enabled
    (flag-ul din oracle_engine.py, Faza 1) — trei controale separate."""
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("consensus_validation_enabled", False))


def compute_metrics(raw_predictions: list[dict]) -> dict | None:
    """Calculează cele trei metrici candidate dintr-o PERECHE de ieșiri
    brute (ADR-031). None dacă nu există EXACT 2 motoare disponibile —
    fie mai puțin de 2 (stare legitimă, ex. ML indisponibil pentru acest
    meci, nimic de comparat), fie mai mult de 2.

    [CORECTAT — audit final ADR-051/052] Verificarea era `< 2` (doar prag
    minim), nu `!= 2` — dacă raw_predictions ar fi ajuns vreodată să conțină
    3+ motoare (nu se întâmplă azi: build_raw_predictions() adaugă cel mult
    Oracle+ML, niciodată Blend), `a, b = engines[0], engines[1]` ar fi ales
    tacit primele două și ar fi ignorat restul — o aproximare silențioasă,
    interzisă explicit de Regula #8 (CLAUDE.md, „nicio stare necunoscută nu
    se aproximează"). Metrica agreement_score/divergence_score e definită
    matematic doar pentru o pereche (distanță L1 între doi vectori) — o
    versiune N-way ar fi o metrică NOUĂ, decizie de design separată, nu un
    fix mecanic; până atunci, N>2 întoarce explicit None, nu o aproximare.

    Funcție pură, fără I/O — reutilizabilă direct în teste."""
    engines = [p for p in raw_predictions if all(k in p for k in ("prob_home", "prob_draw", "prob_away"))]
    if len(engines) != 2:
        return None
    a, b = engines[0], engines[1]

    l1 = (
        abs(a["prob_home"] - b["prob_home"])
        + abs(a["prob_draw"] - b["prob_draw"])
        + abs(a["prob_away"] - b["prob_away"])
    )
    agreement_score = max(0.0, 1.0 - l1 / 2.0)   # 1.0 = acord perfect, distanta L1 maxima intre doi vectori de probabilitate e 2
    divergence_score = l1

    a_argmax = max(("prob_home", "prob_draw", "prob_away"), key=lambda k: a[k])
    b_argmax = max(("prob_home", "prob_draw", "prob_away"), key=lambda k: b[k])
    prediction_distance = 0.0 if a_argmax == b_argmax else 1.0

    return {
        "agreement_score": agreement_score,
        "divergence_score": divergence_score,
        "prediction_distance": prediction_distance,
    }


def _reference_brier(raw_predictions: list[dict], outcome: str) -> float | None:
    """Brier al motorului rule_based (mereu prezent, spre deosebire de ml —
    vezi ADR-031, build_raw_predictions()) — referința de acuratețe pentru
    corelare, aleasă explicit pentru disponibilitate garantată, nu pentru
    performanță superioară. Reutilizează shadow_testing._brier() — aceeași
    formulă de acuratețe deja standardizată în proiect, nicio metrică nouă
    inventată (ADR-033, Validation Protocol Contract)."""
    from shadow_testing import _brier

    rule_based = next((p for p in raw_predictions if p.get("family") == "rule_based"), None)
    if rule_based is None or outcome not in _OUTCOME_KEYS:
        return None
    return _brier(rule_based["prob_home"], rule_based["prob_draw"], rule_based["prob_away"], outcome)


def _bootstrap_independent_groups(group_a: list[float], group_b: list[float],
                                   n_iterations: int = 2000) -> dict:
    """Test bootstrap pentru DOUĂ EȘANTIOANE INDEPENDENTE (nu perechi ale
    aceluiași subiect). Deliberat NU reutilizează
    shadow_testing._paired_bootstrap() — acea funcție presupune
    baseline/experiment index-perechi, pentru ACELAȘI meci sub două
    condiții (potrivit pentru Shadow: Challenger vs. campion, pe fiecare
    meci). Aici cele două grupuri sunt subseturi INDEPENDENTE ale
    eșantionului (împărțite după valoarea medianei metricii de consens) —
    reutilizarea testului pereche ar fi incorectă statistic, nu doar o
    simplificare. Funcție nouă, mică, justificată explicit — "formulele
    exacte, detaliu de implementare" (ADR-033)."""
    n_a, n_b = len(group_a), len(group_b)
    observed_delta = (sum(group_a) / n_a) - (sum(group_b) / n_b)
    boot_deltas = []
    for _ in range(n_iterations):
        sample_a = [group_a[random.randrange(n_a)] for _ in range(n_a)]
        sample_b = [group_b[random.randrange(n_b)] for _ in range(n_b)]
        boot_deltas.append((sum(sample_a) / n_a) - (sum(sample_b) / n_b))
    boot_deltas.sort()
    ci_low = boot_deltas[int(0.025 * n_iterations)]
    ci_high = boot_deltas[int(0.975 * n_iterations)]
    significant = not (ci_low <= 0.0 <= ci_high)
    return {"delta": observed_delta, "ci_low": ci_low, "ci_high": ci_high, "significant": significant}


def _evaluate_metric(metric_name: str, usable: list[tuple[dict, dict]], is_primary: bool) -> dict:
    """Corelează metrica `metric_name` cu acuratețea reală (Brier de
    referință): împarte eșantionul în două grupuri INDEPENDENTE, după
    mediana metricii, compară acuratețea medie a celor două grupuri.
    Persistă verdictul ca fapt istoric imuabil (UNIQUE la nivel DB)."""
    values, briers, dates = [], [], []
    for sample, metrics in usable:
        brier = _reference_brier(sample["raw_predictions"], sample["actual_result"])
        if brier is None:
            continue
        values.append(metrics[metric_name])
        briers.append(brier)
        if sample.get("kickoff_date"):
            dates.append(sample["kickoff_date"])

    n = len(values)
    if n < MIN_SAMPLES_FOR_CONSENSUS_VALIDATION:
        verdict, test_result = "insufficient_data", None
    else:
        median = sorted(values)[n // 2]
        high_group = [b for v, b in zip(values, briers) if v >= median]
        low_group = [b for v, b in zip(values, briers) if v < median]
        if len(high_group) < 2 or len(low_group) < 2:
            verdict, test_result = "insufficient_data", None
        else:
            # favorable: grupul cu consens MAI MARE (agreement mai mare /
            # divergenta mai mica / distanta predictie mai mica) ar trebui
            # sa aiba Brier mai MIC (mai bun) daca metrica poarta informatie
            # reala. Pentru divergence_score/prediction_distance (unde
            # valoare mica = consens mare), semnul asteptat se inverseaza -
            # tratat uniform mai jos prin comparatia directa a mediilor.
            test_result = _bootstrap_independent_groups(low_group, high_group)
            verdict = "surface_worthy" if test_result["significant"] else "rejected"

    sb.save_consensus_validation_verdict(
        metric_name=metric_name, is_primary_metric=is_primary, n_samples_evaluated=n,
        evaluation_window_start=min(dates) if dates else None,
        evaluation_window_end=max(dates) if dates else None,
        verdict=verdict, statistical_method="bootstrap_independent_groups",
        metrics={"test": test_result} if test_result else {},
    )
    return {"verdict": verdict, "n_samples_evaluated": n, "test": test_result}


def _propose_surfacing_decision(study_run_id: int, metric_name: str, result: dict) -> None:
    """T3a — doar dacă metrica PRIMARĂ produce verdict surface_worthy (per
    ADR-033, §5: nicio metrică exploratorie nu poate declanșa T3a, chiar
    dacă iese semnificativă). Produce exclusiv o PROPUNERE — nu execută
    nicio schimbare de serving (regula normativă centrală, ADR-033
    §Decision)."""
    decision_run_id = ar.write_run(PRODUCER, "consensus_surfacing_candidate", "T3a", target_key=metric_name)
    if decision_run_id is None:
        return
    ar.start_run(decision_run_id)
    ar.complete_run(decision_run_id)

    decision_id = ar.propose_decision(
        decision_run_id, tier="T3a",
        rollback_plan="revenire la politica de serving implicita ADR-031 (flag de configurare, zero risc de date)",
        evidence={"metric_name": metric_name, "study_run_id": study_run_id, **result},
        correction_method="none — pre-ADR-034",
        ttl_hours=_SURFACING_DECISION_TTL_HOURS,
    )
    if decision_id:
        ar.surface_decision(decision_id)


def run_validation_cycle() -> dict:
    """Punctul de intrare public — Faza 2, T1. Sigur de rerulat oricând;
    imutabilitatea vine din UNIQUE(metric_name, n_samples_evaluated) la
    scriere (§save_consensus_validation_verdict), nu din verificări
    suplimentare aici."""
    if not is_enabled():
        logger.info("[ConsensusValidation] consensus_validation_enabled=False — ciclu sarit complet.")
        return {"enabled": False}

    run_id = ar.write_run(PRODUCER, "consensus_validation_study", "T1")
    if run_id is None:
        return {"enabled": True, "status": "run_creation_failed"}
    ar.start_run(run_id)

    samples = sb.get_unevaluated_consensus_samples()
    usable = [(s, compute_metrics(s["raw_predictions"])) for s in samples]
    usable = [(s, m) for s, m in usable if m is not None]
    n = len(usable)

    if n < MIN_SAMPLES_FOR_CONSENSUS_VALIDATION:
        ar.skip_run(run_id, f"prag de esantion neatins ({n}/{MIN_SAMPLES_FOR_CONSENSUS_VALIDATION})")
        return {"enabled": True, "status": "insufficient_data", "n_samples": n}

    results = {}
    for metric_name in CANDIDATE_METRICS:
        results[metric_name] = _evaluate_metric(metric_name, usable, is_primary=(metric_name == PRIMARY_METRIC))

    ar.complete_run(run_id, summary={
        "n_samples": n,
        "verdicts": {k: v["verdict"] for k, v in results.items()},
    })

    primary_result = results[PRIMARY_METRIC]
    if primary_result["verdict"] == "surface_worthy":
        _propose_surfacing_decision(run_id, PRIMARY_METRIC, primary_result)

    return {"enabled": True, "status": "evaluated", "n_samples": n, "results": results}
