"""
================================================================================
FOOTBALL ORACLE — Learning Core: Champion Guardian (Stage R2.4, ADR-037)
================================================================================
Module: learning_core/champion_guardian.py

Evaluează sănătatea campionului ACTIV și persistă un fapt imuabil în
`champion_health_evaluations`. READ-ONLY față de `model_champions` (îl citește
doar prin `get_active_champion`); scrie EXCLUSIV `champion_health_evaluations`.
NU promovează, NU face rollback, NU scrie `automation_runs` (propunerea T3a e
R3). Doar produce evaluări și recomandări (starea de sănătate).

── Ownership / layering ────────────────────────────────────────────────────
Owner unic al evaluării de sănătate. Import lazy al dependințelor (ca
rollback_service). NU importă oracle_engine, promotion_service, rollback_service,
continuous_learning. Best-effort: orice eșec → None / degradare grațioasă,
niciodată excepție propagată (Regula #8).

── Cele patru dimensiuni (design settled R2.4) ─────────────────────────────
1. Structural  — sondă de utilizabilitate: artifact_missing / model_error.
                 Un artefact mort → Critical, indiferent de date.
2. Baseline    — Brier live (fereastra scorabilă) vs baseline-ul de promovare
                 (challenger_evaluations.*_experiment); degradare relativă >
                 BASELINE_DEGRADATION_MARGIN. Sărită dacă nu există baseline
                 (baseline_source = trend_only).
3. Trend       — split 50/50 al ferestrei; media Brier recent vs anterior;
                 recent > anterior * (1 + TREND_DEGRADATION_MARGIN). Explicabil,
                 determinist, fără bootstrap (bootstrap = eventual R4).
4. Stability   — dispersia încrederii (max prob) pe fereastră. INFORMATIV:
                 contribuie cel mult la Watch, NICIODATĂ Degrading/Critical.

── Prioritatea clasificării (punct unic, _classify_champion_health) ────────
    Critical (structural)  >  InsufficientData (n<MIN)  >  Degrading
    (ferestre degradate consecutive)  >  Watch (un semnal sau instability)
    >  Healthy

── Persistare ──────────────────────────────────────────────────────────────
n == 0  → întoarce starea FĂRĂ a persista (nu există fereastră; cazul R-A azi).
n >= 1  → persistă (window_end = ultimul kickoff scorat), idempotent prin
          record_champion_health_evaluation (ON CONFLICT DO NOTHING).
================================================================================
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

logger = logging.getLogger("FootballOracle.LearningCore.ChampionGuardian")

# ── Parametri (constante numite, tunabile — praguri = parametri de
# implementare, ADR-037; valori aprobate la settle-ul de design R2.4). ──────
MIN_MATCHES_FOR_HEALTH = 30           # sub prag → insufficient_data
BASELINE_DEGRADATION_MARGIN = 0.10    # Brier live vs baseline (relativ)
TREND_DEGRADATION_MARGIN = 0.10       # Brier recent vs anterior (relativ)
CONSECUTIVE_DEGRADED_WINDOWS = 2      # ferestre consecutive → Degrading
STABILITY_DISPERSION_THRESHOLD = 0.20 # dispersia max-prob → instability (informativ)

_EPS = 1e-12  # garda domeniului log

_VALID_OUTCOMES = ("H", "D", "A")


@dataclass
class ChampionHealthResult:
    health_state: str
    baseline_source: str
    n_matches_evaluated: int
    window_end: str | None = None
    brier_live: float | None = None
    logloss_live: float | None = None
    accuracy_live: float | None = None
    brier_baseline: float | None = None
    logloss_baseline: float | None = None
    accuracy_baseline: float | None = None
    stability_indicator: float | None = None
    baseline_deviation_flag: bool | None = None
    trend_flag: bool | None = None
    structural_flag: bool | None = None
    stability_flag: bool | None = None
    recommends_rollback: bool = False
    reason: str | None = None
    persisted: bool = False


def evaluate_champion_health(algorithm_family: str, league_scope: str) -> ChampionHealthResult | None:
    """Evaluează sănătatea campionului activ pentru (algorithm_family,
    league_scope). None dacă nu există campion activ, sau la orice eșec
    (degradare grațioasă, niciodată excepție propagată — Regula #8)."""
    try:
        import supabase_client as sb

        champion = sb.get_active_champion(algorithm_family, league_scope)
        if champion is None:
            return None
        training_run_id = champion["training_run_id"]

        # Dimensiunea 1: sondă structurală (întâi — un artefact mort e Critical
        # indiferent de date). (reason_code, msg) sau None.
        structural = _structural_probe(training_run_id, champion.get("algorithm_version"))

        # Fereastra scorabilă (predicții servite rezolvate, cronologic determinist).
        since_date = _date_only(champion.get("promoted_at"))
        rows = sb.get_champion_served_outcomes(algorithm_family, league_scope, since_date)
        n = len(rows)
        window_end = rows[-1].get("kickoff_date") if n else None

        # Baseline (din verdictul de promovare, dacă există).
        baseline = _load_baseline(sb, training_run_id)
        baseline_source = "promotion_evaluation" if baseline else "trend_only"

        brier_live = logloss_live = accuracy_live = None
        stability_indicator = None
        baseline_deviation_flag = trend_flag = stability_flag = None
        this_degraded = False
        consecutive = 0

        # Dimensiunile statistice doar când avem suficiente meciuri.
        if n >= MIN_MATCHES_FOR_HEALTH:
            brier_live, logloss_live, accuracy_live = _live_metrics(rows)
            if baseline is not None:
                baseline_deviation_flag = _baseline_deviation(brier_live, baseline)
            trend_flag = _trend_degradation(rows)
            stability_indicator, stability_flag = _stability(rows)
            this_degraded = bool(baseline_deviation_flag) or bool(trend_flag)
            recent = sb.get_recent_champion_health_evaluations(
                training_run_id, limit=CONSECUTIVE_DEGRADED_WINDOWS + 1,
            )
            consecutive = _count_consecutive_degraded(recent, this_degraded, n)

        health_state = _classify_champion_health(
            structural_failed=structural is not None,
            n_matches=n,
            consecutive_degraded=consecutive,
            this_degraded=this_degraded,
            instability=bool(stability_flag),
        )

        reason = None
        if structural is not None:
            reason = f"{structural[0]}: {structural[1]}"
        elif health_state == "degrading":
            reason = "regression: ferestre degradate consecutive (baseline/trend)"

        result = ChampionHealthResult(
            health_state=health_state, baseline_source=baseline_source,
            n_matches_evaluated=n, window_end=window_end,
            brier_live=brier_live, logloss_live=logloss_live, accuracy_live=accuracy_live,
            brier_baseline=(baseline or {}).get("brier"),
            logloss_baseline=(baseline or {}).get("logloss"),
            accuracy_baseline=(baseline or {}).get("accuracy"),
            stability_indicator=stability_indicator,
            baseline_deviation_flag=baseline_deviation_flag, trend_flag=trend_flag,
            structural_flag=(structural is not None), stability_flag=stability_flag,
            recommends_rollback=health_state in ("degrading", "critical"),
            reason=reason,
        )

        # Persistare DOAR când n >= 1 (window_end există). n == 0 → return-only.
        if n >= 1:
            result.persisted = bool(sb.record_champion_health_evaluation(
                training_run_id=training_run_id, algorithm_family=algorithm_family,
                league_scope=league_scope, window_end=window_end, n_matches_evaluated=n,
                health_state=health_state, baseline_source=baseline_source,
                brier_live=brier_live, logloss_live=logloss_live, accuracy_live=accuracy_live,
                brier_baseline=result.brier_baseline, logloss_baseline=result.logloss_baseline,
                accuracy_baseline=result.accuracy_baseline,
                stability_indicator=stability_indicator,
                baseline_deviation_flag=baseline_deviation_flag, trend_flag=trend_flag,
                structural_flag=(structural is not None), stability_flag=stability_flag,
            ))
        return result
    except Exception as exc:
        logger.warning("[ChampionGuardian] evaluate_champion_health eșuat pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return None


# ── Clasificator: PUNCT UNIC de decizie (tipar _classify_data_quality, D4) ──

def _classify_champion_health(
    structural_failed: bool, n_matches: int,
    consecutive_degraded: int, this_degraded: bool, instability: bool,
) -> str:
    """Prioritate (R2.4, aprobată):
        Critical (structural) > InsufficientData (n<MIN) > Degrading
        (ferestre degradate consecutive) > Watch (un semnal sau instability)
        > Healthy.
    Structural bate InsufficientData: un artefact mort e Critical chiar și cu
    puține date. Instability (informativ) poate produce cel mult Watch."""
    if structural_failed:
        return "critical"
    if n_matches < MIN_MATCHES_FOR_HEALTH:
        return "insufficient_data"
    if consecutive_degraded >= CONSECUTIVE_DEGRADED_WINDOWS:
        return "degrading"
    if this_degraded or instability:
        return "watch"
    return "healthy"


# ── Dimensiunea 1: structural ───────────────────────────────────────────────

def _structural_probe(training_run_id: str, algorithm_version) -> tuple[str, str] | None:
    """Clasifică utilizabilitatea artefactului campionului: None dacă e ok,
    ('artifact_missing'|'model_error', mesaj) altfel. Erorile de infrastructură
    (ex. import eșuat) NU sunt prinse aici — propagă la apelant (→ None,
    evaluare degradată grațios), ca să NU marcheze fals un campion sănătos ca
    'model_error'. NU modifică champion_loader (sondă separată, clasificatoare)."""
    from learning_core import model_artifact_storage

    model = model_artifact_storage.load_model_artifact(training_run_id)  # nu ridică
    if model is None:
        return ("artifact_missing", f"artefactul {training_run_id!r} nu a putut fi încărcat")

    import numpy as np
    from ml_predictor import FEATURE_COLUMNS, _ALGORITHM_VERSION

    try:
        model.predict_proba(np.zeros((1, len(FEATURE_COLUMNS))))
    except Exception as exc:
        return ("model_error", f"predict_proba invalid: {exc}")

    if algorithm_version is not None and algorithm_version != _ALGORITHM_VERSION:
        return ("model_error",
                f"algorithm_version incompatibil: {algorithm_version!r} vs {_ALGORITHM_VERSION!r}")
    return None


# ── Baseline + metrici live ─────────────────────────────────────────────────

def _load_baseline(sb, training_run_id: str) -> dict | None:
    """Baseline-ul de promovare = metricile *_experiment ale campionului din
    verdictul de promovare (challenger_evaluations, măsurat live). None dacă nu
    există verdict (campion bootstrapat → trend_only)."""
    ev = sb.get_latest_challenger_evaluation(training_run_id)
    if ev is None:
        return None
    b, ll, a = _f(ev.get("brier_experiment")), _f(ev.get("logloss_experiment")), _f(ev.get("accuracy_experiment"))
    if b is None and ll is None and a is None:
        return None
    return {"brier": b, "logloss": ll, "accuracy": a}


def _live_metrics(rows: list[dict]) -> tuple[float | None, float | None, float | None]:
    """Brier (reutilizat din shadow_testing._brier) + log-loss + accuracy pe
    fereastra scorabilă. (None, None, None) dacă niciun rând valid."""
    from shadow_testing import _brier

    brier = logloss = correct = 0.0
    valid = 0
    for r in rows:
        ph, pd, pa = _f(r.get("prob_home_pred")), _f(r.get("prob_draw_pred")), _f(r.get("prob_away_pred"))
        outcome = r.get("actual_result")
        if ph is None or pd is None or pa is None or outcome not in _VALID_OUTCOMES:
            continue
        valid += 1
        brier += _brier(ph, pd, pa, outcome)
        true_p = {"H": ph, "D": pd, "A": pa}[outcome]
        logloss += -math.log(max(true_p, _EPS))
        predicted = _VALID_OUTCOMES[max(range(3), key=lambda i: (ph, pd, pa)[i])]
        correct += 1.0 if predicted == outcome else 0.0
    if valid == 0:
        return None, None, None
    return brier / valid, logloss / valid, correct / valid


# ── Dimensiunea 2: baseline deviation ───────────────────────────────────────

def _baseline_deviation(brier_live: float | None, baseline: dict) -> bool | None:
    """Brier live semnificativ mai slab decât baseline-ul (relativ). Brier e
    metrica primară (regulă proprie de scoring — calibrare + ascuțime). None
    dacă nu se poate compara."""
    b = baseline.get("brier")
    if b is None or b <= 0 or brier_live is None:
        return None
    return brier_live > b * (1 + BASELINE_DEGRADATION_MARGIN)


# ── Dimensiunea 3: trend (split 50/50, medii Brier — explicabil, determinist) ──

def _trend_degradation(rows: list[dict]) -> bool | None:
    """Media Brier pe jumătatea recentă vs cea anterioară a ferestrei (ordonată
    cronologic). recent > anterior * (1 + margin) → drift. Fără bootstrap
    (explicabil; bootstrap = eventual R4). None dacă nu se poate calcula."""
    n = len(rows)
    if n < 2:
        return None
    mid = n // 2
    earlier = _mean_brier(rows[:mid])
    recent = _mean_brier(rows[mid:])
    if earlier is None or recent is None or earlier <= 0:
        return None
    return recent > earlier * (1 + TREND_DEGRADATION_MARGIN)


def _mean_brier(rows: list[dict]) -> float | None:
    from shadow_testing import _brier

    vals = []
    for r in rows:
        ph, pd, pa = _f(r.get("prob_home_pred")), _f(r.get("prob_draw_pred")), _f(r.get("prob_away_pred"))
        outcome = r.get("actual_result")
        if ph is None or pd is None or pa is None or outcome not in _VALID_OUTCOMES:
            continue
        vals.append(_brier(ph, pd, pa, outcome))
    return sum(vals) / len(vals) if vals else None


# ── Dimensiunea 4: stability (INFORMATIV — maxim Watch, niciodată rollback) ──

def _stability(rows: list[dict]) -> tuple[float | None, bool | None]:
    """Dispersia (std) încrederii (max prob) pe fereastră. Un model „nervos"
    oscilează. INFORMATIV: (indicator, flag) unde flag=True doar contribuie la
    Watch, niciodată la Degrading/Critical."""
    conf = []
    for r in rows:
        ph, pd, pa = _f(r.get("prob_home_pred")), _f(r.get("prob_draw_pred")), _f(r.get("prob_away_pred"))
        if ph is None or pd is None or pa is None:
            continue
        conf.append(max(ph, pd, pa))
    if len(conf) < 2:
        return None, None
    mean = sum(conf) / len(conf)
    std = (sum((x - mean) ** 2 for x in conf) / len(conf)) ** 0.5
    return std, std > STABILITY_DISPERSION_THRESHOLD


# ── Ferestre consecutive degradate ──────────────────────────────────────────

def _count_consecutive_degraded(recent: list[dict], this_degraded: bool, current_n: int) -> int:
    """Numărul de ferestre degradate consecutive, incluzând fereastra CURENTĂ.
    `recent` = ferestre persistate, ordonate descrescător după
    n_matches_evaluated. Se numără cât timp sunt degradate consecutiv de la
    vârf; un gol întrerupe seria.

    [F1 audit R2.4] Se numără DOAR ferestre STRICT anterioare
    (n_matches_evaluated < current_n). O re-rulare fără meciuri noi persistă
    (idempotent) fereastra curentă cu ACELAȘI n; dacă ar fi numărată, un singur
    spike degradat (Watch) ar deveni fals Degrading la următoarea rulare
    identică. Rândurile cu n >= current_n (fereastra curentă însăși) sunt
    ignorate — nu se numără și nu întrerup seria."""
    if not this_degraded:
        return 0
    count = 1  # fereastra curentă
    for row in recent:
        if row.get("n_matches_evaluated", 0) >= current_n:
            continue  # fereastra curentă (re-rulare, același n) — nu se numără
        if _row_degraded(row):
            count += 1
        else:
            break
    return count


def _row_degraded(row: dict) -> bool:
    return bool(row.get("baseline_deviation_flag")) or bool(row.get("trend_flag"))


# ── Utilitare ───────────────────────────────────────────────────────────────

def _date_only(value) -> str | None:
    """Dată-only `YYYY-MM-DD` (F-C R2.3): comparabilă lexicografic cu
    match_history.kickoff_date (TEXT dată-only)."""
    if not value:
        return None
    return str(value)[:10]


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):  # [F2 audit R2.4] nu persistăm niciodată NaN/inf
        return None
    return x
