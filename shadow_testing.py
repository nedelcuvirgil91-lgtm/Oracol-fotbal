"""
================================================================================
FOOTBALL ORACLE — Shadow Testing (v1.0)
================================================================================
Module: shadow_testing.py

Infrastructură GENERICĂ de shadow testing — vezi
architecture/ADR-002-shadow-testing.md pentru raționamentul complet.

Nu importă oracle_engine.py — evită dependința circulară (oracle_engine.py
importă din acest modul, nu invers). Singura dependință reală e
supabase_client.py, deja fără nicio dependință către oracle_engine.py.

Compatibil cu arhitectura deja existentă:
  - api_cache / api_provider_status / provider_metrics — independente,
    niciun overlap (acelea țin de request-uri HTTP, nu de predicții).
  - LEAGUE_PROVIDERS (mappings.py) — NU e importat aici; `league_scope`
    e doar un string liber (numele canonic al ligii sau "all"), fără
    nicio validare încrucișată în acest modul (validarea numelui de ligă
    e responsabilitatea apelantului, nu a infrastructurii de shadow testing).

Reguli obligatorii respectate:
  - NU modifică pipeline-ul de producție — funcțiile de logging sunt
    pur aditive, apelate DOAR dacă `shadow_mode_enabled` e True (verificat
    de apelant, oracle_engine.py — acest modul nu citește el însuși config,
    ca să rămână complet independent de restul aplicației).
  - shadow_predictions e complet generic — orice experiment nou (injuries,
    coaches, player stats, SofaScore etc.) folosește exact aceleași
    funcții, fără nicio adaptare de schemă sau cod.
  - experiment_registry e SINGURA sursă de adevăr pentru status — nu există
    nicio altă locație în cod care calculează sau stochează statusul unui
    experiment.
================================================================================
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable, NamedTuple

import supabase_client as sb
from mappings import normalize_team_name

logger = logging.getLogger("FootballOracle.ShadowTesting")

_OUTCOME_INDEX = {"H": 0, "D": 1, "A": 2}
_OUTCOME_VECTOR = {"H": (1, 0, 0), "D": (0, 1, 0), "A": (0, 0, 1)}


# ════════════════════════════════════════════════════════════════════════════
# LOGGING — shadow_predictions (log brut, per meci, per etapă de procesare)
# ════════════════════════════════════════════════════════════════════════════

def log_shadow_prediction(
    fixture_id: str,
    experiment_name: str,
    experiment_version: str,
    home_xg: float,
    away_xg: float,
    prob_home: float,
    prob_draw: float,
    prob_away: float,
    feature_metadata: dict | None = None,
    experiment_group: str = "treatment",
    baseline_model_version: str | None = None,
    model_version: str | None = None,
    provider_version: str | None = None,
    processing_stage: str = "final",
    league: str | None = None,
    home_team: str | None = None,
    away_team: str | None = None,
    kickoff_date: str | None = None,
    latency_ms: float | None = None,
    error_message: str | None = None,
) -> bool:
    """
    Salvează o predicție experimentală. Apelul e complet aditiv — niciodată
    nu atinge match_history sau weights.json.

    `processing_stage`: 'baseline' | 'after_<feature>' | ... | 'final' —
    permite să vezi cât a mutat fiecare etapă predicția, nu doar rezultatul
    final (vezi ADR-002).
    """
    client = sb.get_client()
    if client is None:
        return False
    predicted_outcome = ["H", "D", "A"][
        max(range(3), key=lambda i: (prob_home, prob_draw, prob_away)[i])
    ]
    confidence = max(prob_home, prob_draw, prob_away)
    # [ADR-058 F2] Normalizare la writer — apelantul (oracle_engine.py:2068)
    # transmite `pred.home_team`/`pred.away_team`, adica numele venit din
    # dictionarul de meci, NU trecut explicit prin normalize_team_name() la
    # acel punct. Aparare in adancime, nu fix: un nume necunoscut lui
    # ALIAS_TO_CANONICAL trece neschimbat, prin design (ADR-058 §1.2) —
    # cele 218 randuri cu sufix de tara gasite azi in shadow_predictions
    # exista din cauza vocabularului, nu a lipsei acestui apel.
    home_team = normalize_team_name(home_team) if home_team else home_team
    away_team = normalize_team_name(away_team) if away_team else away_team
    try:
        client.table("shadow_predictions").upsert({
            "fixture_id": fixture_id,
            "league": league, "home_team": home_team, "away_team": away_team,
            "kickoff_date": kickoff_date,
            "experiment_name": experiment_name, "experiment_version": experiment_version,
            "experiment_group": experiment_group,
            "baseline_model_version": baseline_model_version,
            "model_version": model_version, "provider_version": provider_version,
            "processing_stage": processing_stage,
            "home_xg": home_xg, "away_xg": away_xg,
            "prob_home": prob_home, "prob_draw": prob_draw, "prob_away": prob_away,
            "predicted_outcome": predicted_outcome, "confidence": confidence,
            "feature_metadata": feature_metadata or {},
            "latency_ms": latency_ms, "error_message": error_message,
            "prediction_time": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="fixture_id,experiment_name,experiment_version,experiment_group,processing_stage").execute()
        return True
    except Exception as exc:
        logger.warning("[ShadowTesting] log_shadow_prediction failed: %s", exc)
        return False


def get_shadow_predictions(
    experiment_name: str, experiment_version: str | None = None,
    league_scope: str | None = None, processing_stage: str | None = None,
    include_invalidated: bool = False,
) -> list[dict]:
    """[ADR-064] Randurile INVALIDATE sunt excluse implicit.

    O predictie facuta sub o identitate gresita (ex. gazda si oaspetele
    inversate) nu e o predictie despre meciul real — punctata contra
    rezultatului adevarat, produce semnal fals SISTEMATIC, nu zgomot: un
    "gazda castiga" ar iesi corect exact cand castiga cealalta echipa.

    `include_invalidated=True` doar pentru audit/inspectie, niciodata pentru
    evaluare."""
    client = sb.get_client()
    if client is None:
        return []
    try:
        q = client.table("shadow_predictions").select("*").eq("experiment_name", experiment_name)
        if experiment_version is not None:
            q = q.eq("experiment_version", experiment_version)
        if league_scope is not None and league_scope != "all":
            q = q.eq("league", league_scope)
        if processing_stage is not None:
            q = q.eq("processing_stage", processing_stage)
        if not include_invalidated:
            q = q.is_("invalidated_at", "null")
        res = q.execute()
        return res.data or []
    except Exception as exc:
        logger.warning("[ShadowTesting] get_shadow_predictions failed: %s", exc)
        return []


def invalidate_shadow_predictions(fixture_id: str, reason: str) -> int:
    """[ADR-064] Scoate din evaluare predicțiile shadow ale unui meci, păstrându-le
    în tabelă. Întoarce numărul de rânduri invalidate.

    ACȚIUNE SUPRAVEGHEATĂ. Nu se apelează automat dintr-un `hard_conflict`:
    a decide că o predicție e invalidă înseamnă a decide că identitatea sub
    care a fost făcută e greșită — exact judecata pe care ADR-002 o ține în
    mâna omului, și pe care migrarea 049 refuză deliberat să o automatizeze.

    De ce invalidare și nu corecție: probabilitățile NU se permută
    (`prob_home ↔ prob_away`) — modelul aplică avantajul terenului propriu,
    deci permutarea ar fabrica o predicție care nu a fost făcută niciodată.
    Nici recalcularea retroactivă nu e validă: ar folosi feature-uri de azi
    pentru un moment din trecut (scurgere temporală, North Star #7).

    De ce nu ștergere: sistemul chiar a produs acele predicții, iar faptul
    rămâne parte din istoric (trasabilitate completă, North Star #9).

    Rândurile deja invalidate nu se re-marchează — motivul original se
    păstrează, ca prima decizie să rămână cea trasabilă."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError(
            "invalidate_shadow_predictions(): `reason` obligatoriu — o "
            "invalidare fără motiv nu e trasabilă (ADR-064)."
        )
    if not fixture_id:
        raise ValueError("invalidate_shadow_predictions(): `fixture_id` obligatoriu.")

    client = sb.get_client()
    if client is None:
        logger.warning("[ShadowTesting] invalidate_shadow_predictions: Supabase indisponibil.")
        return 0
    try:
        res = (
            client.table("shadow_predictions")
            .update({
                "invalidated_at": datetime.now(timezone.utc).isoformat(),
                "invalidation_reason": reason,
            })
            .eq("fixture_id", fixture_id)
            .is_("invalidated_at", "null")
            .execute()
        )
        n = len(res.data or [])
        logger.warning(
            "[ShadowTesting] ADR-064: %d predicții shadow invalidate pentru "
            "fixture_id=%s — motiv: %s", n, fixture_id, reason,
        )
        return n
    except Exception as exc:
        logger.error(
            "[ShadowTesting] invalidate_shadow_predictions eșuat pentru %s: %s",
            fixture_id, exc,
        )
        return 0


# ════════════════════════════════════════════════════════════════════════════
# STATISTICS ENGINE — interfață uniformă, testul concret e înlocuibil
# ════════════════════════════════════════════════════════════════════════════

class TestResult(NamedTuple):
    delta: float
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    significant: bool
    method: str


def _paired_bootstrap(baseline: list[float], experiment: list[float],
                       favorable_direction: int, n_iterations: int = 2000) -> TestResult:
    """favorable_direction: -1 daca valori mai mici sunt mai bune (Brier/Log-loss),
    +1 daca valori mai mari sunt mai bune (Accuracy)."""
    n = len(baseline)
    diffs = [e - b for b, e in zip(baseline, experiment)]
    observed_delta = sum(diffs) / n
    boot_deltas = []
    for _ in range(n_iterations):
        sample = [diffs[random.randrange(n)] for _ in range(n)]
        boot_deltas.append(sum(sample) / n)
    boot_deltas.sort()
    ci_low = boot_deltas[int(0.025 * n_iterations)]
    ci_high = boot_deltas[int(0.975 * n_iterations)]
    significant = (ci_high < 0) if favorable_direction == -1 else (ci_low > 0)
    return TestResult(observed_delta, ci_low, ci_high, None, significant, "paired_bootstrap")


def _paired_permutation(baseline: list[float], experiment: list[float],
                         favorable_direction: int, n_iterations: int = 2000) -> TestResult:
    n = len(baseline)
    diffs = [e - b for b, e in zip(baseline, experiment)]
    observed_delta = sum(diffs) / n
    count_extreme = 0
    for _ in range(n_iterations):
        signs = [1 if random.random() < 0.5 else -1 for _ in range(n)]
        permuted = [d * s for d, s in zip(diffs, signs)]
        permuted_delta = sum(permuted) / n
        if favorable_direction == -1 and permuted_delta <= observed_delta:
            count_extreme += 1
        elif favorable_direction == 1 and permuted_delta >= observed_delta:
            count_extreme += 1
    p_value = count_extreme / n_iterations
    significant = p_value < 0.05
    return TestResult(observed_delta, None, None, p_value, significant, "paired_permutation")


def _wilcoxon(baseline: list[float], experiment: list[float],
              favorable_direction: int, n_iterations: int = 2000) -> TestResult:
    try:
        from scipy.stats import wilcoxon
    except ImportError:
        logger.warning("[ShadowTesting] scipy indisponibil — fallback pe paired_bootstrap")
        return _paired_bootstrap(baseline, experiment, favorable_direction, n_iterations)
    diffs = [e - b for b, e in zip(baseline, experiment)]
    observed_delta = sum(diffs) / len(diffs)
    try:
        stat, p_value = wilcoxon(baseline, experiment)
    except ValueError:
        # toate diferentele 0, sau alt caz degenerat - wilcoxon nu poate rula
        return TestResult(observed_delta, None, None, 1.0, False, "wilcoxon")
    directionally_favorable = (observed_delta < 0) if favorable_direction == -1 else (observed_delta > 0)
    significant = bool(p_value < 0.05 and directionally_favorable)
    return TestResult(observed_delta, None, None, float(p_value), significant, "wilcoxon")


StatisticalTest = Callable[..., TestResult]

STATISTICAL_TESTS: dict[str, StatisticalTest] = {
    "paired_bootstrap": _paired_bootstrap,
    "paired_permutation": _paired_permutation,
    "wilcoxon": _wilcoxon,
    # viitor: "mcnemar" (potrivit pt Accuracy, categorial pereche),
    # "diebold_mariano" (comparare serii de prognoza), "bayesian" —
    # se adauga aici, fara nicio schimbare in evaluate_experiment().
}


# ════════════════════════════════════════════════════════════════════════════
# EVALUARE — experiment_registry, SINGURA sursă de adevăr pt status
# ════════════════════════════════════════════════════════════════════════════

def _brier(ph: float, pd: float, pa: float, outcome: str) -> float:
    y = _OUTCOME_VECTOR[outcome]
    p = (ph, pd, pa)
    return sum((p[i] - y[i]) ** 2 for i in range(3))


def _baseline_is_neutral(match_row: dict) -> bool:
    """[ADR-065] Baseline-ul Oracle a fost complet ORB pentru acest meci —
    FUNCȚIE PURĂ, fără I/O.

    „Orb" înseamnă `data_quality == 'neutral'` pe AMBELE părți. Cu toate
    intrările la valori neutre, `feature_engine.calibrate_xg()` produce
    aceeași valoare pentru orice meci din acea competiție — verificat live:
    Champions League 18 rânduri / o singură valoare, Europa League 26 / una.

    Deliberat strict pe „ambele": dacă o singură echipă e neutrală, baseline-ul
    tot are informație parțială și meciul rămâne în subsetul informat. Un prag
    mai larg ar exclude mai mult decât justifică dovada."""
    return (match_row.get("home_data_quality") == "neutral"
            and match_row.get("away_data_quality") == "neutral")


def evaluate_experiment(
    experiment_name: str,
    experiment_version: str,
    league_scope: str = "all",
    min_matches: int = 200,
    statistical_method: str = "paired_bootstrap",
) -> dict | None:
    """
    Evaluează un experiment pe fereastra de meciuri deja acumulate în
    shadow_predictions (processing_stage='final', experiment_group='treatment')
    care AU deja rezultat real în match_history. Actualizează
    experiment_registry (singura sursă de adevăr pt status) și întoarce
    rezultatul.

    Nu modifică NICIODATĂ weights.json/model_config — doar raportează.
    """
    client = sb.get_client()
    if client is None:
        return None

    shadow_rows = [
        r for r in get_shadow_predictions(experiment_name, experiment_version, league_scope)
        if r.get("processing_stage") == "final" and r.get("experiment_group") == "treatment"
    ]
    fixture_ids = [r["fixture_id"] for r in shadow_rows]
    if not fixture_ids:
        _update_registry(experiment_name, experiment_version, league_scope,
                          status="insufficient_data", n_matches_evaluated=0,
                          statistical_method=statistical_method)
        return {"status": "insufficient_data", "n_matches_evaluated": 0}

    try:
        res = (
            client.table("match_history")
            .select("fixture_id,actual_result,prob_home_pred,prob_draw_pred,prob_away_pred,"
                    "home_data_quality,away_data_quality")
            .in_("fixture_id", fixture_ids)
            .execute()
        )
        mh_by_fixture = {
            r["fixture_id"]: r for r in (res.data or [])
            if r.get("actual_result") and r.get("prob_home_pred") is not None
        }
    except Exception as exc:
        logger.warning("[ShadowTesting] evaluate_experiment — citire match_history eșuată: %s", exc)
        return None

    eligible = [(r, mh_by_fixture[r["fixture_id"]]) for r in shadow_rows if r["fixture_id"] in mh_by_fixture]
    n = len(eligible)

    if n < min_matches:
        _update_registry(experiment_name, experiment_version, league_scope,
                          status="insufficient_data", n_matches_evaluated=n,
                          statistical_method=statistical_method)
        return {"status": "insufficient_data", "n_matches_evaluated": n}

    baseline_brier, exp_brier = [], []
    baseline_logloss, exp_logloss = [], []
    baseline_correct, exp_correct = [], []
    informed_brier_base, informed_brier_exp = [], []
    informed_ll_base, informed_ll_exp = [], []
    informed_acc_base, informed_acc_exp = [], []
    dates = []

    for shadow, mh in eligible:
        outcome = mh["actual_result"]
        bp = (mh["prob_home_pred"], mh["prob_draw_pred"], mh["prob_away_pred"])
        ep = (shadow["prob_home"], shadow["prob_draw"], shadow["prob_away"])

        baseline_brier.append(_brier(*bp, outcome))
        exp_brier.append(_brier(*ep, outcome))

        b_true = max(bp[_OUTCOME_INDEX[outcome]], 1e-10)
        e_true = max(ep[_OUTCOME_INDEX[outcome]], 1e-10)
        baseline_logloss.append(-math.log(b_true))
        exp_logloss.append(-math.log(e_true))

        b_pred = ["H", "D", "A"][max(range(3), key=lambda i: bp[i])]
        baseline_correct.append(1.0 if b_pred == outcome else 0.0)
        exp_correct.append(1.0 if shadow.get("predicted_outcome") == outcome else 0.0)

        if shadow.get("kickoff_date"):
            dates.append(shadow["kickoff_date"])

        # [ADR-065] Subsetul INFORMAT — meciurile în care baseline-ul Oracle a
        # avut date reale. Pentru un meci complet neutru, Oracle emite aceeași
        # constantă indiferent de echipe, în timp ce experimentul poate avea
        # ELO și alte feature-uri reale: comparația nu e „ambii orbi".
        if not _baseline_is_neutral(mh):
            informed_brier_base.append(baseline_brier[-1])
            informed_brier_exp.append(exp_brier[-1])
            informed_ll_base.append(baseline_logloss[-1])
            informed_ll_exp.append(exp_logloss[-1])
            informed_acc_base.append(baseline_correct[-1])
            informed_acc_exp.append(exp_correct[-1])

    test_fn = STATISTICAL_TESTS.get(statistical_method, _paired_bootstrap)
    brier_result = test_fn(baseline_brier, exp_brier, favorable_direction=-1)
    logloss_result = test_fn(baseline_logloss, exp_logloss, favorable_direction=-1)
    accuracy_result = test_fn(baseline_correct, exp_correct, favorable_direction=1)

    if brier_result.significant and logloss_result.significant and accuracy_result.significant:
        status = "candidate_for_promotion"
    elif brier_result.delta > 0 and logloss_result.delta > 0 and (
        brier_result.significant is False and logloss_result.significant is False
    ) and accuracy_result.delta < 0:
        # toate trei se mișcă in directia gresita simultan - respingere clara
        status = "rejected"
    else:
        status = "monitoring"

    result = {
        "status": status,
        "n_matches_evaluated": n,
        "evaluation_window_start": min(dates) if dates else None,
        "evaluation_window_end": max(dates) if dates else None,
        "brier_baseline": sum(baseline_brier) / n, "brier_experiment": sum(exp_brier) / n,
        "delta_brier": brier_result.delta, "brier_significant": brier_result.significant,
        "logloss_baseline": sum(baseline_logloss) / n, "logloss_experiment": sum(exp_logloss) / n,
        "delta_logloss": logloss_result.delta, "logloss_significant": logloss_result.significant,
        "accuracy_baseline": sum(baseline_correct) / n, "accuracy_experiment": sum(exp_correct) / n,
        "delta_accuracy": accuracy_result.delta, "accuracy_significant": accuracy_result.significant,
        "statistical_method": statistical_method,
    }
    # Registry-ul primeste DOAR campurile de verdict, INAINTE de imbogatire:
    # `experiment_registry` nu are coloanele de diagnostic ADR-065, iar o
    # scriere cu campuri necunoscute ar esua. Diagnosticul apartine tabelei
    # `challenger_evaluations`, nu registrului de status.
    _update_registry(experiment_name, experiment_version, league_scope, **result)

    # [ADR-065] Diagnostic, NU un al doilea verdict: aceleași trei delte,
    # recalculate doar pe meciurile cu baseline informat. Criteriul de
    # promovare rămâne definit pe populația completă (North Star #2) — asta
    # doar arată omului care aprobă DE UNDE vine avantajul.
    #
    # Se raportează DELTE, nu semnificație: subsetul poate fi prea mic pentru
    # un test concludent, iar o deltă rămâne citibilă. `n_matches_informed`
    # merge alături tocmai ca delta să nu fie citită fără context.
    n_inf = len(informed_brier_base)
    result["n_matches_informed"] = n_inf
    if n_inf > 0:
        result["delta_brier_informed"] = test_fn(
            informed_brier_base, informed_brier_exp, favorable_direction=-1).delta
        result["delta_logloss_informed"] = test_fn(
            informed_ll_base, informed_ll_exp, favorable_direction=-1).delta
        result["delta_accuracy_informed"] = test_fn(
            informed_acc_base, informed_acc_exp, favorable_direction=1).delta
    else:
        # Niciun meci informat: necunoscut, nu zero (Regula #8).
        result["delta_brier_informed"] = None
        result["delta_logloss_informed"] = None
        result["delta_accuracy_informed"] = None
    return result


def _update_registry(experiment_name: str, experiment_version: str, league_scope: str, **fields) -> bool:
    client = sb.get_client()
    if client is None:
        return False
    try:
        row = {
            "experiment_name": experiment_name, "experiment_version": experiment_version,
            "league_scope": league_scope, "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        client.table("experiment_registry").upsert(
            row, on_conflict="experiment_name,experiment_version,league_scope"
        ).execute()
        return True
    except Exception as exc:
        logger.error("[ShadowTesting] _update_registry failed: %s", exc)
        return False


def promote_experiment(experiment_name: str, experiment_version: str, league_scope: str,
                        promoted_by: str) -> bool:
    """Promovare — DOAR manuală, apelată explicit de un om, niciodată automat."""
    return _update_registry(
        experiment_name, experiment_version, league_scope,
        status="promoted", promoted_at=datetime.now(timezone.utc).isoformat(),
        promoted_by=promoted_by,
    )


def deprecate_experiment(experiment_name: str, experiment_version: str, league_scope: str,
                          superseded_by: str | None = None) -> bool:
    return _update_registry(
        experiment_name, experiment_version, league_scope,
        status="deprecated", deprecated_at=datetime.now(timezone.utc).isoformat(),
        superseded_by=superseded_by,
    )


def get_experiment_registry(experiment_name: str | None = None) -> list[dict]:
    client = sb.get_client()
    if client is None:
        return []
    try:
        q = client.table("experiment_registry").select("*")
        if experiment_name is not None:
            q = q.eq("experiment_name", experiment_name)
        res = q.execute()
        return res.data or []
    except Exception as exc:
        logger.warning("[ShadowTesting] get_experiment_registry failed: %s", exc)
        return []


# ════════════════════════════════════════════════════════════════════════════
# ORCHESTRARE — parte din bucla de învățare continuă (vezi ADR-004)
# ════════════════════════════════════════════════════════════════════════════

def get_distinct_experiments() -> list[tuple[str, str]]:
    """Toate perechile (experiment_name, experiment_version) care au cel
    puțin o predicție shadow logată — indiferent de feature, indiferent
    câte experimente vor exista în viitor (injuries, coaches, SofaScore etc.)."""
    client = sb.get_client()
    if client is None:
        return []
    try:
        res = client.table("shadow_predictions").select("experiment_name,experiment_version").execute()
        rows = res.data or []
        return sorted({(r["experiment_name"], r["experiment_version"]) for r in rows})
    except Exception as exc:
        logger.warning("[ShadowTesting] get_distinct_experiments failed: %s", exc)
        return []


def evaluate_all_active_experiments(
    min_matches: int = 200, statistical_method: str = "paired_bootstrap",
    league_scope: str = "all",
) -> list[dict]:
    """
    Apelată din bucla de învățare continuă (sync/run_daily.py), DUPĂ ce
    rezultatele noi au fost sincronizate în match_history — vezi ADR-004.
    Nu modifică NICIODATĂ weights.json/model_config — doar actualizează
    experiment_registry (singura sursă de adevăr pt status).
    """
    results = []
    for name, version in get_distinct_experiments():
        r = evaluate_experiment(
            name, version, league_scope=league_scope,
            min_matches=min_matches, statistical_method=statistical_method,
        )
        if r is not None:
            r = {**r, "experiment_name": name, "experiment_version": version}
            results.append(r)
    return results
