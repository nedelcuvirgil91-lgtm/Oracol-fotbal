"""
TEMPORAR -- P2 din ML_EVOLUTION_ROADMAP.md: Probability Calibration.

Compara trei variante, contra acelorasi date reale, aceleasi 5 folduri
walk-forward (identice ca granite cu MLPredictorEngine._walk_forward_validate):
  1. baseline  -- XGBoost de productie, fara nicio calibrare.
  2. platt     -- CalibratedClassifierCV(method="sigmoid"), fit fold-local.
  3. isotonic  -- CalibratedClassifierCV(method="isotonic"), fit fold-local.

Disciplina fold-local, zero leakage (cerinta explicita a Chief Architect):
in fiecare fold, segmentul de TRAIN (tot ce e cronologic inainte de VALIDATION)
e impartit mai departe, tot cronologic, in doua sub-segmente:
  - clf-fit (~85% din train, partea mai veche)   -> antreneaza XGBoost.
  - calib   (~15% din train, partea mai recenta) -> antreneaza calibratorul.
VALIDATION ramane complet neatinsa de orice antrenare (XGBoost sau calibrare).

De ce nu se calibreaza pe predictiile XGBoost chiar pe train (in-sample)?
Isotonic Regression e suficient de flexibila incat, fitata pe aceleasi date
pe care clasificatorul le-a vazut la antrenare, ar produce o calibrare
artificial de buna (clasificatorul e deja "prea sigur" pe propriile date de
antrenare) -- exact tipul de optimism pe care sklearn.CalibratedClassifierCV
il evita explicit cerand un set de calibrare disjunct de antrenarea de bază.
Split-ul clf/calib de mai sus respecta asta, ramanand STRICT cronologic
(nicio informatie din calib "vede" date ulterioare fata de clf-fit, si
nimic din train "vede" validation) -- deci ramane fold-local, zero leakage.

Consecinta secundara, raportata explicit: clasificatorul XGBoost de aici
antreneaza pe ~85% din segmentul de train (nu 100%, ca la productie/benchmark-ul
oficial), deci varianta "baseline" din acest experiment poate diferi usor de
benchmark-ul oficial (ADR-020) doar din cauza volumului de date, nu a
calibrarii. Comparatia corecta si principala e baseline-din-acest-experiment
vs Platt vs Isotonic (acelasi clasificator, exact aceleasi date, singura
diferenta fiind calibrarea) -- comparatia cu benchmark-ul oficial ramane
secundara, doar pentru context.

Raporteaza si Expected Calibration Error (ECE, Guo et al. 2017) + un
reliability diagram (10 bin-uri de incredere), calculate pe predictiile
concatenate din toate cele 5 folduri de validare (esantion mult mai mare
si mai stabil decat orice fold individual).

Criteriul OFICIAL de succes (P2, ML_EVOLUTION_ROADMAP.md, neschimbat):
Log Loss SAU Brier imbunatatite >=0,5% relativ fata de baseline-ul din
acest experiment, FARA degradare de Accuracy peste +/-0,001.

100% read-only fata de Supabase (doar SELECT, get_training_data). Zero
scriere, zero artefact persistat, zero cod de productie modificat.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import accuracy_score, log_loss as sk_log_loss
from xgboost import XGBClassifier

from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, RESULT_TO_LABEL

try:
    from sklearn.frozen import FrozenEstimator
    _HAS_FROZEN_ESTIMATOR = True
except ImportError:
    _HAS_FROZEN_ESTIMATOR = False

N_FOLDS = 5
CALIB_HOLDOUT_FRACTION = 0.15  # partea cea mai recenta din train, rezervata calibrarii
MIN_CLF_SIZE = 20
MIN_CALIB_SIZE = 20
N_ECE_BINS = 10

# Hiperparametrii de productie -- neschimbati (P1/P1.1 REJECTED, ADR/roadmap).
PRODUCTION_PARAMS = dict(
    n_estimators=150, max_depth=4, learning_rate=0.08,
    subsample=0.85, colsample_bytree=0.85,
    objective="multi:softprob", num_class=3,
    eval_metric="mlogloss", random_state=42,
)

OFFICIAL_BENCHMARK = {"accuracy": 0.4868, "log_loss": 1.0253, "brier_score": 0.6145}
SUCCESS_REL_IMPROVEMENT = 0.005   # >=0.5% relativ, pe Log Loss SAU Brier
DEGRADATION_ACC = 0.001

VARIANTS = ["baseline", "platt", "isotonic"]


def multiclass_brier(y_true: np.ndarray, probs: np.ndarray, n_classes: int = 3) -> float:
    one_hot = np.eye(n_classes)[y_true]
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


def expected_calibration_error(y_true: np.ndarray, probs: np.ndarray, n_bins: int = N_ECE_BINS):
    """ECE standard (Guo et al. 2017): pe increderea (probabilitatea maxima)
    atasata clasei prezise, grupata in n_bins de latime egala, ponderata cu
    fractia de esantioane din fiecare bin."""
    preds = np.argmax(probs, axis=1)
    confidences = np.max(probs, axis=1)
    correct = (preds == y_true).astype(float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    n = len(y_true)
    ece = 0.0
    bins = []
    for i in range(n_bins):
        lo, hi = edges[i], edges[i + 1]
        mask = (confidences >= lo) & (confidences < hi) if i < n_bins - 1 else (confidences >= lo) & (confidences <= hi)
        count = int(mask.sum())
        if count == 0:
            bins.append({"range": f"[{lo:.1f},{hi:.1f})", "count": 0, "avg_confidence": None, "accuracy": None})
            continue
        avg_conf = float(confidences[mask].mean())
        acc = float(correct[mask].mean())
        ece += (count / n) * abs(avg_conf - acc)
        bins.append({"range": f"[{lo:.1f},{hi:.1f})", "count": count,
                      "avg_confidence": round(avg_conf, 4), "accuracy": round(acc, 4)})
    return float(ece), bins


def calibrated_classifier(fitted_model, method: str) -> CalibratedClassifierCV:
    if _HAS_FROZEN_ESTIMATOR:
        return CalibratedClassifierCV(estimator=FrozenEstimator(fitted_model), method=method)
    return CalibratedClassifierCV(estimator=fitted_model, method=method, cv="prefit")


def main() -> int:
    t0 = time.time()
    engine = MLPredictorEngine()
    df = engine._fetch_training_dataframe()
    if df is None or df.empty:
        print("Fara date de antrenare disponibile din Supabase.")
        return 1

    if "kickoff_date" in df.columns:
        df = df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)
    else:
        print("ATENTIE: kickoff_date absent -- ordinea nu e garantat cronologica.")

    X_all = df[FEATURE_COLUMNS].astype(float)
    y_all = df["actual_result"].map(RESULT_TO_LABEL).astype(int)
    n = len(X_all)

    print(f"Total meciuri folosite: {n}")
    print(f"Benchmark oficial (ADR-020): Accuracy={OFFICIAL_BENCHMARK['accuracy']}, "
          f"Log Loss={OFFICIAL_BENCHMARK['log_loss']}, Brier={OFFICIAL_BENCHMARK['brier_score']}")
    print("P2 -- Probability Calibration: baseline vs Platt (sigmoid) vs Isotonic, "
          f"fit fold-local strict, split clf/calib {int((1 - CALIB_HOLDOUT_FRACTION) * 100)}/"
          f"{int(CALIB_HOLDOUT_FRACTION * 100)} cronologic in interiorul fiecarui segment de train.")
    print(f"FrozenEstimator disponibil: {_HAS_FROZEN_ESTIMATOR} (fallback: cv='prefit')")
    print()

    boundaries = np.linspace(0, n, N_FOLDS + 2, dtype=int)
    fold_results = {v: [] for v in VARIANTS}
    pooled_probs = {v: [] for v in VARIANTS}
    pooled_y = []
    folds_used = 0

    for k in range(1, N_FOLDS + 1):
        val_start, val_end = boundaries[k], boundaries[k + 1]
        X_tr, y_tr = X_all.iloc[:val_start], y_all.iloc[:val_start]
        X_val, y_val = X_all.iloc[val_start:val_end], y_all.iloc[val_start:val_end]

        if len(X_tr) < 20 or len(X_val) == 0 or y_tr.nunique() < 2:
            print(f"Fold {k}: sarit (segment de train/validare insuficient).")
            continue

        clf_end = int(len(X_tr) * (1 - CALIB_HOLDOUT_FRACTION))
        X_clf, y_clf = X_tr.iloc[:clf_end], y_tr.iloc[:clf_end]
        X_calib, y_calib = X_tr.iloc[clf_end:], y_tr.iloc[clf_end:]

        if len(X_clf) < MIN_CLF_SIZE or len(X_calib) < MIN_CALIB_SIZE or y_clf.nunique() < 2:
            print(f"Fold {k}: sarit (split clf/calib insuficient: clf={len(X_clf)}, calib={len(X_calib)}).")
            continue

        model = XGBClassifier(**PRODUCTION_PARAMS)
        model.fit(X_clf, y_clf)

        probs_by_variant = {"baseline": model.predict_proba(X_val)}
        for method, key in [("sigmoid", "platt"), ("isotonic", "isotonic")]:
            calibrated = calibrated_classifier(model, method)
            calibrated.fit(X_calib, y_calib)
            probs_by_variant[key] = calibrated.predict_proba(X_val)

        y_val_arr = y_val.to_numpy()
        pooled_y.append(y_val_arr)
        folds_used += 1

        for v in VARIANTS:
            probs = probs_by_variant[v]
            preds = np.argmax(probs, axis=1)
            acc = float(accuracy_score(y_val_arr, preds))
            try:
                ll = float(sk_log_loss(y_val_arr, probs, labels=[0, 1, 2]))
            except Exception:
                ll = None
            brier = multiclass_brier(y_val_arr, probs)
            fold_results[v].append({
                "fold": k, "clf_size": len(X_clf), "calib_size": len(X_calib), "val_size": len(X_val),
                "accuracy": round(acc, 4), "log_loss": round(ll, 4) if ll is not None else None,
                "brier_score": round(brier, 4),
            })
            pooled_probs[v].append(probs)

    if folds_used == 0:
        print("Niciun fold valid -- experiment intrerupt.")
        return 1

    pooled_y_arr = np.concatenate(pooled_y)
    for v in VARIANTS:
        pooled_probs[v] = np.concatenate(pooled_probs[v], axis=0)

    print()
    print("=" * 116)
    print(f"REZULTATE PER FOLD ({folds_used} folduri walk-forward)")
    print("=" * 116)

    summary = {}
    for v in VARIANTS:
        rows = fold_results[v]
        accs = [r["accuracy"] for r in rows]
        lls = [r["log_loss"] for r in rows if r["log_loss"] is not None]
        briers = [r["brier_score"] for r in rows]
        avg_acc, std_acc = float(np.mean(accs)), float(np.std(accs))
        avg_ll, std_ll = float(np.mean(lls)), float(np.std(lls))
        avg_brier, std_brier = float(np.mean(briers)), float(np.std(briers))
        summary[v] = {
            "avg_accuracy": round(avg_acc, 4), "std_accuracy": round(std_acc, 4),
            "avg_log_loss": round(avg_ll, 4), "std_log_loss": round(std_ll, 4),
            "avg_brier_score": round(avg_brier, 4), "std_brier_score": round(std_brier, 4),
        }
        print(f"\n--- Varianta: {v} ---")
        for r in rows:
            print(f"  fold {r['fold']}: clf={r['clf_size']} calib={r['calib_size']} val={r['val_size']} "
                  f"| acc={r['accuracy']} log_loss={r['log_loss']} brier={r['brier_score']}")
        print(f"  MEDIE: accuracy={summary[v]['avg_accuracy']} (std={summary[v]['std_accuracy']}), "
              f"log_loss={summary[v]['avg_log_loss']} (std={summary[v]['std_log_loss']}), "
              f"brier={summary[v]['avg_brier_score']} (std={summary[v]['std_brier_score']})")

    print()
    print("=" * 116)
    print("COMPARATIE -- baseline (din acest experiment) vs Platt vs Isotonic")
    print("=" * 116)
    base = summary["baseline"]
    for v in ["platt", "isotonic"]:
        s = summary[v]
        d_ll = base["avg_log_loss"] - s["avg_log_loss"]
        d_ll_rel = d_ll / base["avg_log_loss"] * 100 if base["avg_log_loss"] else 0.0
        d_brier = base["avg_brier_score"] - s["avg_brier_score"]
        d_brier_rel = d_brier / base["avg_brier_score"] * 100 if base["avg_brier_score"] else 0.0
        d_acc = s["avg_accuracy"] - base["avg_accuracy"]
        print(f"\n{v}:")
        print(f"  Log Loss : {base['avg_log_loss']} -> {s['avg_log_loss']}  ({-d_ll:+.4f}, {-d_ll_rel:+.4f}% relativ)")
        print(f"  Brier    : {base['avg_brier_score']} -> {s['avg_brier_score']}  ({-d_brier:+.4f}, {-d_brier_rel:+.4f}% relativ)")
        print(f"  Accuracy : {base['avg_accuracy']} -> {s['avg_accuracy']}  ({d_acc:+.4f})")

    print()
    print("=" * 116)
    print("CONTEXT -- comparatie cu benchmark-ul oficial (ADR-020, poate diferi usor din cauza split-ului clf/calib)")
    print("=" * 116)
    for v in VARIANTS:
        s = summary[v]
        print(f"  {v}: Accuracy={s['avg_accuracy']} (oficial {OFFICIAL_BENCHMARK['accuracy']}), "
              f"Log Loss={s['avg_log_loss']} (oficial {OFFICIAL_BENCHMARK['log_loss']}), "
              f"Brier={s['avg_brier_score']} (oficial {OFFICIAL_BENCHMARK['brier_score']})")

    print()
    print("=" * 116)
    print(f"CALIBRARE -- Expected Calibration Error (ECE, {N_ECE_BINS} bin-uri) + reliability diagram, pe predictiile "
          f"concatenate din toate cele {folds_used} folduri de validare ({len(pooled_y_arr)} meciuri)")
    print("=" * 116)
    ece_results = {}
    for v in VARIANTS:
        ece, bins = expected_calibration_error(pooled_y_arr, pooled_probs[v], n_bins=N_ECE_BINS)
        ece_results[v] = ece
        print(f"\n--- {v}: ECE = {ece:.4f} ---")
        print(f"  {'bin':<12}{'count':>8}{'avg_confidence':>16}{'accuracy':>12}{'semnal':>16}")
        for b in bins:
            if b["count"] == 0:
                print(f"  {b['range']:<12}{0:>8}{'--':>16}{'--':>12}{'gol':>16}")
                continue
            gap = b["avg_confidence"] - b["accuracy"]
            semnal = "overconfident" if gap > 0.02 else ("underconfident" if gap < -0.02 else "calibrat")
            print(f"  {b['range']:<12}{b['count']:>8}{b['avg_confidence']:>16}{b['accuracy']:>12}{semnal:>16}")

    print()
    print("=" * 116)
    print("VERDICT OFICIAL (criteriul P2, ML_EVOLUTION_ROADMAP.md, neschimbat)")
    print("=" * 116)
    candidates = []
    for v in ["platt", "isotonic"]:
        s = summary[v]
        ll_rel = (base["avg_log_loss"] - s["avg_log_loss"]) / base["avg_log_loss"]
        brier_rel = (base["avg_brier_score"] - s["avg_brier_score"]) / base["avg_brier_score"]
        acc_delta = s["avg_accuracy"] - base["avg_accuracy"]
        meets_metric = (ll_rel >= SUCCESS_REL_IMPROVEMENT) or (brier_rel >= SUCCESS_REL_IMPROVEMENT)
        no_degradation = abs(acc_delta) <= DEGRADATION_ACC
        candidates.append({
            "variant": v, "ll_rel": ll_rel, "brier_rel": brier_rel, "acc_delta": acc_delta,
            "meets_metric": meets_metric, "no_degradation": no_degradation,
            "success": meets_metric and no_degradation,
            "ece": ece_results[v],
        })
        print(f"\n{v}: Log Loss {ll_rel*100:+.4f}% relativ, Brier {brier_rel*100:+.4f}% relativ, "
              f"Accuracy delta {acc_delta:+.4f}, ECE={ece_results[v]:.4f} "
              f"(baseline ECE={ece_results['baseline']:.4f}) "
              f"-> {'CRITERIU INDEPLINIT' if candidates[-1]['success'] else 'criteriu neindeplinit'}")

    winners = [c for c in candidates if c["success"]]
    if winners:
        best = max(winners, key=lambda c: max(c["ll_rel"], c["brier_rel"]))
        print(f"\nRECOMANDARE FINALA: ACCEPTED -- varianta '{best['variant']}' indeplineste criteriul oficial de succes.")
        print("Inainte de promovarea in productie: validare separata asupra motorului de Value Betting "
              "(risc: calibrarea comprima probabilitatile si reduce numarul de value bets identificate) "
              "-- cerinta explicita, pas separat, neinclus in acest script.")
    else:
        print("\nRECOMANDARE FINALA: REJECTED -- nicio varianta (Platt/Isotonic) nu indeplineste criteriul "
              "oficial de succes din ML_EVOLUTION_ROADMAP.md P2 in aceasta runda.")

    print(f"\nTimp total: {time.time() - t0:.1f}s")
    print("Nicio scriere efectuata -- doar citire (get_training_data) + calcul local (XGBoost/sklearn, in memorie).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
