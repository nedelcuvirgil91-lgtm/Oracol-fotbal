"""
================================================================================
FOOTBALL ORACLE — Validation Analysis (ADR-052 §2.4)
================================================================================
Module: validation_analysis.py

Analize periodice (zilnice/săptămânale) care compară Oracle/ML/Blend pe o
fereastră de timp, folosind exact metodologia deja stabilită de proiect —
Brier + Log-loss + Accuracy, simultan, North Star #2 (Brier reutilizat direct
din shadow_testing._brier(), aceeași formulă, nicio reinventare).

Scop exclusiv descriptiv — acest modul NU ia decizii, NU optimizează, NU
promovează nimic (ADR-052 §2.3/§2.5): produce rapoarte persistate în
validation_analysis_reports, pentru analiza ulterioară (Claude analizează și
recomandă, decizia rămâne a proprietarului produsului).

Sursă: JOIN engine_comparison_snapshots (validation_framework.py, ADR-052)
cu match_history.actual_result (Canonical Feature Ownership, ADR-036/D3.5 —
sync_results.py e singurul scriitor, acest modul doar citește).

Fiecare motor raportat pe PROPRIUL subset disponibil (n propriu per motor)
— un motor absent dintr-o fereastră nu produce o metrică aproximată
(Regula #8, CLAUDE.md), doar n=0/metrici None.

Decuplat de continuous_learning.py (ADR-030) și de consensus_validation.py
(ADR-033) — flag propriu (validation_analysis_enabled), cadență proprie
(workflow GitHub Actions propriu), fără nicio interacțiune.
================================================================================
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta, timezone

import automation_runs as ar
import supabase_client as sb
from shadow_testing import _brier

logger = logging.getLogger("FootballOracle.ValidationAnalysis")

PRODUCER = "ADR-052"

_DEFAULT_CONFIG = {"validation_analysis_enabled": False}

_OUTCOME_INDEX = {"H": 0, "D": 1, "A": 2}

_ENGINES = ("oracle", "ml", "blend")


def is_enabled() -> bool:
    """Implicit False (North Star #3). Independent de
    validation_framework_enabled (colectarea per-meci) — flag DEDICAT pentru
    analiza periodică, decuplat, ca să poată fi pornit/oprit separat."""
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("validation_analysis_enabled", False))


def _logloss(ph: float, pd: float, pa: float, outcome: str) -> float:
    """Aceeași formulă deja folosită de shadow_testing.evaluate_experiment()
    — clamp la 1e-10, nicio metodologie nouă."""
    p_true = (ph, pd, pa)[_OUTCOME_INDEX[outcome]]
    return -math.log(max(p_true, 1e-10))


def _correct(ph: float, pd: float, pa: float, outcome: str) -> float:
    """Idem — argmax pe (H, D, A), aceeași convenție ca
    shadow_testing.evaluate_experiment()."""
    predicted = ["H", "D", "A"][max(range(3), key=lambda i: (ph, pd, pa)[i])]
    return 1.0 if predicted == outcome else 0.0


def _engine_metrics(rows: list[dict], engine: str) -> dict:
    """Agregă Brier/logloss/accuracy pentru `engine` ("oracle"/"ml"/"blend")
    peste rândurile unde acel motor era disponibil ȘI rezultatul real e
    cunoscut (deja filtrat de apelant). n=0 -> toate metricile None (stare
    necunoscută explicită, nu aproximată — Regula #8)."""
    briers, loglosses, corrects = [], [], []
    for r in rows:
        if engine != "oracle" and not r.get(f"{engine}_available"):
            continue
        ph, pd, pa = r.get(f"{engine}_prob_home"), r.get(f"{engine}_prob_draw"), r.get(f"{engine}_prob_away")
        if ph is None or pd is None or pa is None:
            continue
        outcome = r["actual_result"]
        briers.append(_brier(ph, pd, pa, outcome))
        loglosses.append(_logloss(ph, pd, pa, outcome))
        corrects.append(_correct(ph, pd, pa, outcome))

    n = len(briers)
    if n == 0:
        return {"n": 0, "brier": None, "logloss": None, "accuracy": None}
    return {
        "n": n,
        "brier": sum(briers) / n,
        "logloss": sum(loglosses) / n,
        "accuracy": sum(corrects) / n,
    }


def _empty_report(cadence: str, period_start: date, period_end: date) -> dict:
    return {
        "cadence": cadence,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "n_matches_total": 0,
        "oracle": {"n": 0, "brier": None, "logloss": None, "accuracy": None},
        "ml": {"n": 0, "brier": None, "logloss": None, "accuracy": None},
        "blend": {"n": 0, "brier": None, "logloss": None, "accuracy": None},
    }


def compute_period_report(cadence: str, period_start: date, period_end: date) -> dict | None:
    """Calculează raportul descriptiv Oracle/ML/Blend pentru fereastra
    [period_start, period_end] (inclusiv, pe kickoff_date) — JOIN
    engine_comparison_snapshots + match_history.actual_result. None dacă
    Supabase indisponibil sau interogarea eșuează (niciodată excepție
    propagată către apelant)."""
    client = sb.get_client()
    if client is None:
        return None

    try:
        snap_res = (
            client.table("engine_comparison_snapshots")
            .select(
                "fixture_id,oracle_prob_home,oracle_prob_draw,oracle_prob_away,"
                "ml_available,ml_prob_home,ml_prob_draw,ml_prob_away,"
                "blend_available,blend_prob_home,blend_prob_draw,blend_prob_away"
            )
            .gte("kickoff_date", period_start.isoformat())
            .lte("kickoff_date", period_end.isoformat())
            .execute()
        )
        snapshots = snap_res.data or []
        if not snapshots:
            return _empty_report(cadence, period_start, period_end)

        fixture_ids = [s["fixture_id"] for s in snapshots]
        mh_res = (
            client.table("match_history")
            .select("fixture_id,actual_result")
            .in_("fixture_id", fixture_ids)
            .execute()
        )
        outcomes = {r["fixture_id"]: r["actual_result"] for r in (mh_res.data or []) if r.get("actual_result")}
    except Exception as exc:
        logger.warning("[ValidationAnalysis] compute_period_report — citire eșuată: %s", exc)
        return None

    rows = []
    for snap in snapshots:
        outcome = outcomes.get(snap["fixture_id"])
        if not outcome:
            continue  # meci fara rezultat cunoscut inca - exclus, nu aproximat
        row = dict(snap)
        row["actual_result"] = outcome
        rows.append(row)

    return {
        "cadence": cadence,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "n_matches_total": len(rows),
        "oracle": _engine_metrics(rows, "oracle"),
        "ml": _engine_metrics(rows, "ml"),
        "blend": _engine_metrics(rows, "blend"),
    }


def _flatten_report(report: dict) -> dict:
    """Aplatizează raportul (dict-uri imbricate per motor) în forma
    tabelară cerută de validation_analysis_reports (migrația 008)."""
    row = {
        "cadence": report["cadence"],
        "period_start": report["period_start"],
        "period_end": report["period_end"],
        "n_matches_total": report["n_matches_total"],
    }
    for engine in _ENGINES:
        m = report[engine]
        row[f"{engine}_n"] = m["n"]
        row[f"{engine}_brier"] = m["brier"]
        row[f"{engine}_logloss"] = m["logloss"]
        row[f"{engine}_accuracy"] = m["accuracy"]
    return row


def save_report(report: dict) -> bool:
    """Persistă raportul — upsert pe (cadence, period_end), o rerulare a
    aceleiași ferestre actualizează rândul, nu creează duplicate."""
    try:
        row = _flatten_report(report)
    except Exception as exc:
        logger.debug("[ValidationAnalysis] aplatizare raport eșuată: %s", exc)
        return False
    try:
        return sb.save_validation_analysis_report(row)
    except Exception as exc:
        logger.debug("[ValidationAnalysis] save_report eșuat: %s", exc)
        return False


def _window_for_cadence(cadence: str, as_of: date) -> tuple[date, date] | None:
    """Fereastra ferm ÎNCHEIATĂ (fără ziua curentă, care poate avea încă
    meciuri fără rezultat final la momentul rulării)."""
    period_end = as_of - timedelta(days=1)
    if cadence == "daily":
        return period_end, period_end
    if cadence == "weekly":
        return period_end - timedelta(days=6), period_end
    return None


def run_report_cycle(cadence: str, as_of: date | None = None) -> dict:
    """Punctul de intrare public — calculează + persistă raportul pentru
    `cadence` ("daily"/"weekly"), cu urmărire prin automation_runs.py
    (același tipar ca learning_core.consensus_validation.run_validation_cycle()).
    Sigur de rerulat oricând — idempotent prin UNIQUE(cadence, period_end)
    la scriere."""
    if not is_enabled():
        logger.info("[ValidationAnalysis] validation_analysis_enabled=False — ciclu sarit complet.")
        return {"enabled": False}

    as_of = as_of or datetime.now(timezone.utc).date()
    window = _window_for_cadence(cadence, as_of)
    if window is None:
        return {"enabled": True, "status": "invalid_cadence", "cadence": cadence}
    period_start, period_end = window

    run_id = ar.write_run(PRODUCER, f"validation_analysis_{cadence}", "T1")
    if run_id is None:
        return {"enabled": True, "status": "run_creation_failed"}
    ar.start_run(run_id)

    report = compute_period_report(cadence, period_start, period_end)
    if report is None:
        ar.fail_run(run_id, "compute_period_report esuat (Supabase indisponibil sau interogare esuata)")
        return {"enabled": True, "status": "compute_failed"}

    if report["n_matches_total"] == 0:
        ar.skip_run(run_id, "0 meciuri cu rezultat cunoscut in fereastra")
        return {"enabled": True, "status": "no_data", "report": report}

    saved = save_report(report)
    ar.complete_run(run_id, summary={
        "n_matches_total": report["n_matches_total"],
        "oracle_n": report["oracle"]["n"],
        "ml_n": report["ml"]["n"],
        "blend_n": report["blend"]["n"],
        "saved": saved,
    })
    return {"enabled": True, "status": "computed", "saved": saved, "report": report}
