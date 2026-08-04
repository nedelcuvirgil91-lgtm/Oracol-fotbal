"""
================================================================================
FOOTBALL ORACLE — Pasul 11: re-rulare benchmark Etapa 3 după ADR-049
================================================================================
Module: scripts/rerun_etapa3_benchmark.py

Tooling de validare (nu cod de producție — niciun modul din app.py/
oracle_engine.py/sync/*/learning_core/* îl importă), analog cu
`prediction_evaluation.py`. Vezi docs/00_GOVERNANCE/PASUL11_IMPLEMENTATION_
PLAN.md pentru metodologia completă și criteriile de succes.

Reproduce metodologia benchmark-ului Etapa 3 (docs/00_GOVERNANCE/
ORACLE_VS_ML_REPORT.md) — cod real de producție, nicio formulă
reimplementată — și adaugă comparația ML necalibrat vs. ML calibrat
(Temperature Scaling, ADR-049), pe EXACT aceleași fold-uri/margini brute
ale unei singure rulări de antrenare (comparație perechi, izolează complet
efectul calibrării).

Acesta NU este un benchmark de reproducere a Etapei 3 (fereastra de date
diferă — vezi --help), ci un benchmark de REVALIDARE: confirmă sau
infirmă aceeași concluzie calitativă, pe date curente.

Read-only: nicio scriere în Supabase, niciun flag de producție atins.

Utilizare:
    python scripts/rerun_etapa3_benchmark.py
    python scripts/rerun_etapa3_benchmark.py --dataset-json <path>  # offline, reproductibilitate
================================================================================
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from feature_engine import calibrate_xg, poisson_model  # noqa: E402
from mappings import LEAGUE_BASELINES  # noqa: E402
from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, _softmax_with_temperature  # noqa: E402

RAW_COLUMNS = [
    "fixture_id", "kickoff_date", "league", "actual_result",
    "home_offensive_rating", "home_defensive_rating",
    "away_offensive_rating", "away_defensive_rating",
    "home_form_score", "away_form_score",
    "home_elo", "away_elo",
    "h2h_modifier", "h2h_meetings",
    "home_corner_avg_recent", "away_corner_avg_recent",
    "home_card_avg_recent", "away_card_avg_recent",
    "home_foul_avg_recent", "away_foul_avg_recent",
    "home_shot_avg_recent", "away_shot_avg_recent",
]

# Ponderi Oracle GLOBALE (nu per-ligă — mecanismul per-ligă e inert azi,
# Etapa 1, sample_count=0 pentru toate ligile) — identice Etapa 3 §2.2.
ORACLE_FORM_WEIGHT = 0.60
ORACLE_BASE_WEIGHT = 0.40
ORACLE_HOME_ADVANTAGE = 1.07
ORACLE_AWAY_PENALTY = 0.95
ORACLE_DEFENSIVE_CAP = 2.5
ORACLE_MAX_GOALS = 8

RESULT_TO_LABEL = {"H": 0, "D": 1, "A": 2}
RELIABILITY_BINS = [(0.00, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 1.01)]

ML_WEIGHT = 0.35  # valoarea implicită din cod (ml_blend_weight), identică Etapa 3


def fetch_dataset(limit: int = 1500) -> pd.DataFrame:
    """Interoghează match_history — read-only, aceeași filtrare/ordonare ca
    Etapa 3 §2.1, cu tiebreaker (fixture_id) pentru determinism, cel mai
    recent `limit` rânduri cu toate feature-urile core ne-nule.

    Paginare prin `.range()` (offset), în pagini de max. 1000 (limita
    implicită PostgREST per răspuns — vezi comentariul din
    `supabase_client.get_training_data()`). Offset-based, NU keyset —
    acceptabil aici (spre deosebire de `get_training_data()`, care iterează
    tot `match_history`, zeci de mii de rânduri): acest script cere cel mult
    `limit` rânduri (implicit 1500, deci maxim 2 pagini, offset maxim ~1499),
    cost neglijabil, nu O(offset) la scară mare."""
    import supabase_client as sb

    client = sb.get_client()
    if client is None:
        raise RuntimeError(
            "Supabase indisponibil — script-ul necesită SUPABASE_URL/SUPABASE_SECRET_KEY. "
            "Pentru rulare offline/reproductibilitate, folosește --dataset-json."
        )

    def _apply_filters(q):
        for col in RAW_COLUMNS:
            if col not in ("fixture_id", "kickoff_date", "league"):
                q = q.not_.is_(col, "null")
        return q

    page_size = 1000
    rows: list[dict] = []
    offset = 0
    while offset < limit:
        page_end = min(offset + page_size, limit) - 1
        q = _apply_filters(client.table("match_history").select(",".join(RAW_COLUMNS)))
        q = q.order("kickoff_date", desc=True).order("fixture_id", desc=True).range(offset, page_end)
        res = q.execute()
        page_rows = res.data or []
        rows.extend(page_rows)
        if len(page_rows) < (page_end - offset + 1):
            break  # mai puține rânduri disponibile decât `limit`
        offset += page_size

    if not rows:
        raise RuntimeError("Interogarea nu a întors rânduri.")
    return pd.DataFrame(rows)


def load_dataset_from_json(path: str) -> pd.DataFrame:
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    return pd.DataFrame(rows)


def add_derived_features(df: pd.DataFrame) -> pd.DataFrame:
    """Identic ml_predictor.MLPredictorEngine._fetch_training_dataframe()."""
    df = df.copy()
    for col in RAW_COLUMNS:
        if col not in ("fixture_id", "kickoff_date", "league", "actual_result"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["corner_dominance"] = df["home_corner_avg_recent"] - df["away_corner_avg_recent"]
    df["card_diff"] = df["away_card_avg_recent"] - df["home_card_avg_recent"]
    df["foul_diff"] = df["away_foul_avg_recent"] - df["home_foul_avg_recent"]
    df["shot_dominance"] = df["home_shot_avg_recent"] - df["away_shot_avg_recent"]
    df = df.sort_values(["kickoff_date", "fixture_id"], kind="stable").reset_index(drop=True)
    return df


def compute_oracle_probs(df: pd.DataFrame) -> np.ndarray:
    """Oracle — cod real (calibrate_xg/poisson_model), ponderi globale,
    identic Etapa 3 §2.2. Fără antrenare — determinist per rând."""
    probs = np.zeros((len(df), 3))
    for i, row in df.iterrows():
        baseline = float(LEAGUE_BASELINES.get(row["league"], LEAGUE_BASELINES.get("default", 1.25)))
        home_xg, away_xg = calibrate_xg(
            home_offensive_rating=row["home_offensive_rating"],
            home_defensive_rating=row["home_defensive_rating"],
            away_offensive_rating=row["away_offensive_rating"],
            away_defensive_rating=row["away_defensive_rating"],
            home_form_score=row["home_form_score"],
            away_form_score=row["away_form_score"],
            baseline=baseline,
            form_weight=ORACLE_FORM_WEIGHT,
            base_weight=ORACLE_BASE_WEIGHT,
            home_advantage=ORACLE_HOME_ADVANTAGE,
            away_penalty=ORACLE_AWAY_PENALTY,
            defensive_cap=ORACLE_DEFENSIVE_CAP,
            h2h_modifier=row["h2h_modifier"],
            h2h_meetings=int(row["h2h_meetings"]),
        )
        ph, pd_, pa, _ = poisson_model(home_xg, away_xg, max_goals=ORACLE_MAX_GOALS)
        probs[i] = [ph, pd_, pa]
    return probs


def run_walk_forward(df: pd.DataFrame, n_folds: int = 5) -> dict:
    """Identic MLPredictorEngine._walk_forward_validate(), dar capturează
    suplimentar predict_proba() (necalibrat) per fold ȘI indicii rândurilor
    validate, ca metricile Oracle/Blend să poată fi calculate pe EXACT
    același subset OOF (comparație perechi validă)."""
    X = df[FEATURE_COLUMNS].astype(float)
    y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)
    n = len(X)
    boundaries = np.linspace(0, n, n_folds + 2, dtype=int)

    oof_indices, oof_margins_parts, oof_probs_uncal_parts, oof_labels_parts = [], [], [], []
    fold_summaries = []
    last_model, last_X_val = None, None

    from xgboost import XGBClassifier

    for k in range(1, n_folds + 1):
        val_start, val_end = boundaries[k], boundaries[k + 1]
        X_tr, y_tr = X.iloc[:val_start], y.iloc[:val_start]
        X_val, y_val = X.iloc[val_start:val_end], y.iloc[val_start:val_end]
        if len(X_tr) < 20 or len(X_val) == 0 or y_tr.nunique() < 2:
            continue

        model = XGBClassifier(
            n_estimators=150, max_depth=4, learning_rate=0.08,
            subsample=0.85, colsample_bytree=0.85,
            objective="multi:softprob", num_class=3,
            eval_metric="mlogloss", random_state=42,
        )
        model.fit(X_tr, y_tr)

        margins = np.asarray(model.predict(X_val, output_margin=True), dtype=float)
        probs_uncal = model.predict_proba(X_val)

        oof_indices.append(np.arange(val_start, val_end))
        oof_margins_parts.append(margins)
        oof_probs_uncal_parts.append(probs_uncal)
        oof_labels_parts.append(y_val.to_numpy())
        fold_summaries.append({"fold": k, "train_size": len(X_tr), "val_size": len(X_val)})
        last_model, last_X_val = model, X_val

    return {
        "indices": np.concatenate(oof_indices),
        "margins": np.concatenate(oof_margins_parts, axis=0),
        "probs_uncalibrated": np.concatenate(oof_probs_uncal_parts, axis=0),
        "labels": np.concatenate(oof_labels_parts),
        "folds": fold_summaries,
        "last_model": last_model,
        "last_X_val": last_X_val,
    }


def compute_metrics(probs: np.ndarray, labels: np.ndarray) -> dict:
    from sklearn.metrics import accuracy_score, log_loss as sk_log_loss

    preds = np.argmax(probs, axis=1)
    acc = float(accuracy_score(labels, preds))
    ll = float(sk_log_loss(labels, probs, labels=[0, 1, 2]))
    brier = MLPredictorEngine._multiclass_brier(labels, probs)
    return {"accuracy": round(acc, 4), "log_loss": round(ll, 4), "brier_score": round(brier, 4), "n": len(labels)}


def compute_reliability(probs: np.ndarray, labels: np.ndarray) -> list[dict]:
    confidence = np.max(probs, axis=1)
    preds = np.argmax(probs, axis=1)
    correct = (preds == labels)
    rows = []
    for lo, hi in RELIABILITY_BINS:
        mask = (confidence >= lo) & (confidence < hi)
        n = int(mask.sum())
        if n == 0:
            rows.append({"bin": f"[{lo:.2f}, {hi:.2f})", "n": 0, "avg_confidence": None, "real_accuracy": None})
            continue
        rows.append({
            "bin": f"[{lo:.2f}, {hi:.2f})", "n": n,
            "avg_confidence": round(float(confidence[mask].mean()), 3),
            "real_accuracy": round(float(correct[mask].mean()), 3),
        })
    return rows


def compute_ece(reliability: list[dict]) -> float:
    total_n = sum(r["n"] for r in reliability)
    if total_n == 0:
        return 0.0
    weighted_gap = sum(r["n"] * abs(r["avg_confidence"] - r["real_accuracy"]) for r in reliability if r["n"] > 0)
    return round(weighted_gap / total_n, 4)


def measure_inference_overhead(model, X_sample: pd.DataFrame, temperature: float, n_repeats: int = 200) -> dict:
    row = X_sample.iloc[[0]]

    t0 = time.perf_counter()
    for _ in range(n_repeats):
        model.predict_proba(row)
    t_uncalibrated = (time.perf_counter() - t0) / n_repeats

    t0 = time.perf_counter()
    for _ in range(n_repeats):
        margins = model.predict(row, output_margin=True)
        _softmax_with_temperature(np.asarray(margins), temperature)
    t_calibrated = (time.perf_counter() - t0) / n_repeats

    overhead_pct = ((t_calibrated - t_uncalibrated) / t_uncalibrated) * 100 if t_uncalibrated > 0 else None
    return {
        "uncalibrated_ms": round(t_uncalibrated * 1000, 4),
        "calibrated_ms": round(t_calibrated * 1000, 4),
        "overhead_pct": round(overhead_pct, 2) if overhead_pct is not None else None,
    }


def blend(oracle_probs: np.ndarray, ml_probs: np.ndarray, samples_used: int, ml_weight: float = ML_WEIGHT) -> np.ndarray:
    """Identic ml_predictor.blend_predictions() — sample_factor scalează
    ponderea ML jos când eșantionul de antrenare per fold e mic."""
    sample_factor = min(samples_used / 150, 1.0)
    effective_weight = ml_weight * sample_factor
    return (1 - effective_weight) * oracle_probs + effective_weight * ml_probs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-json", default=None, help="Cale către un JSON offline (listă de rânduri), pentru reproductibilitate fără acces live Supabase.")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--output-json", default=None, help="Scrie rezultatele complete ca JSON la această cale.")
    args = parser.parse_args()

    if args.dataset_json:
        raw = load_dataset_from_json(args.dataset_json)
    else:
        raw = fetch_dataset(limit=args.limit)

    df = add_derived_features(raw)
    print(f"[Pasul 11] Eșantion: {len(df)} rânduri, {df['kickoff_date'].min()} -> {df['kickoff_date'].max()}")

    wf = run_walk_forward(df)
    oof_idx = wf["indices"]
    labels = wf["labels"]
    margins = wf["margins"]
    probs_uncal = wf["probs_uncalibrated"]

    temperature = MLPredictorEngine._fit_temperature(margins, labels)
    if temperature is None:
        print("[Pasul 11] ATENȚIE: _fit_temperature() a întors None — calibrarea a eșuat pe acest eșantion, raport neconcludent pe comparația primară.")
        temperature = 1.0
    probs_cal = _softmax_with_temperature(margins, temperature)

    oracle_all = compute_oracle_probs(df)
    oracle_oof = oracle_all[oof_idx]

    n_train_last_fold = wf["folds"][-1]["train_size"] if wf["folds"] else 0
    blend_probs_cal = blend(oracle_oof, probs_cal, n_train_last_fold)
    blend_probs_uncal = blend(oracle_oof, probs_uncal, n_train_last_fold)

    report = {
        "dataset": {"n": len(df), "oof_n": len(labels), "date_min": str(df["kickoff_date"].min()), "date_max": str(df["kickoff_date"].max())},
        "temperature": temperature,
        "primary_comparison": {
            "ml_uncalibrated": {**compute_metrics(probs_uncal, labels), "reliability": compute_reliability(probs_uncal, labels)},
            "ml_calibrated": {**compute_metrics(probs_cal, labels), "reliability": compute_reliability(probs_cal, labels)},
        },
        "secondary_comparison": {
            "oracle": {**compute_metrics(oracle_oof, labels), "reliability": compute_reliability(oracle_oof, labels)},
            "ml_calibrated": {**compute_metrics(probs_cal, labels), "reliability": compute_reliability(probs_cal, labels)},
            "blend_with_calibrated_ml": {**compute_metrics(blend_probs_cal, labels), "reliability": compute_reliability(blend_probs_cal, labels)},
            "blend_with_uncalibrated_ml_etapa3_style": {**compute_metrics(blend_probs_uncal, labels), "reliability": compute_reliability(blend_probs_uncal, labels)},
        },
    }
    report["primary_comparison"]["ml_uncalibrated"]["ece"] = compute_ece(report["primary_comparison"]["ml_uncalibrated"]["reliability"])
    report["primary_comparison"]["ml_calibrated"]["ece"] = compute_ece(report["primary_comparison"]["ml_calibrated"]["reliability"])
    report["secondary_comparison"]["oracle"]["ece"] = compute_ece(report["secondary_comparison"]["oracle"]["reliability"])

    report["inference_overhead"] = measure_inference_overhead(wf["last_model"], wf["last_X_val"], temperature)

    print(json.dumps(report, indent=2, default=str))

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"[Pasul 11] Raport scris la {args.output_json}")


if __name__ == "__main__":
    main()
