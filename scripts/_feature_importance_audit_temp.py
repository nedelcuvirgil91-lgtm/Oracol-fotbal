"""
TEMPORAR — audit de feature importance (gain + permutation) și corelații
Pearson pentru cele 13 coloane din ml_predictor.FEATURE_COLUMNS, pe datele
reale de producție (match_history), contra benchmark-ului oficial curat
(Accuracy 0.4868 / Log Loss 1.0253 / Brier 0.6145, 53.409 meciuri).

100% read-only față de Supabase — doar MLPredictorEngine._fetch_training_
dataframe() (SELECT). Zero scriere, zero artefact persistat. Fișier
temporar — se șterge după rulare, împreună cu workflow-ul.

Metodologie:
  1. Gain importance — modelul final XGBoost, antrenat pe tot istoricul
     (identic cu MLPredictorEngine.train(), hiperparametrii reutilizați
     exact), citit din get_booster().get_score(importance_type="gain").
  2. Permutation importance — calculată STRICT pe segmentul de validare
     al fiecărui fold walk-forward (nu pe train), cu modelul antrenat
     doar pe segmentul de train al acelui fold (aceiași hiperparametri,
     aceleași granițe ca MLPredictorEngine._walk_forward_validate()).
     10 repetiții per fold per feature, medie + deviație standard
     RAPORTATE ÎNTRE FOLDURI (nu între repetiții).
  3. Corelații Pearson — pe cele 13 coloane brute (NaN gestionat pairwise
     de pandas.DataFrame.corr()), perechile cu |r| > 0.90 raportate
     separat.

Verdict (KEEP / ABLATION CANDIDATE / CRITICAL) — praguri explicite,
niciun REMOVE — decizia de eliminare rămâne exclusiv a unui test de
ablație dedicat, separat de acest audit.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import supabase_client as sb
from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, RESULT_TO_LABEL

N_FOLDS = 5
N_REPEATS = 10
FOLD_MODEL_KWARGS = dict(
    n_estimators=150, max_depth=4, learning_rate=0.08,
    subsample=0.85, colsample_bytree=0.85,
    objective="multi:softprob", num_class=3,
    eval_metric="mlogloss", random_state=42,
)

# Praguri explicite pentru verdict — relative la benchmark-ul oficial
# (Log Loss 1.0253): >=0.5% degradare la permutare = semnal real.
CRITICAL_DELTA_LL = 0.005
CRITICAL_DELTA_ACC = 0.005
NEGLIGIBLE_DELTA_LL = 0.001
NEGLIGIBLE_DELTA_ACC = 0.001
CRITICAL_GAIN_RANK = 3  # top 3 la gain


def main() -> int:
    from xgboost import XGBClassifier
    from sklearn.metrics import accuracy_score, log_loss as sk_log_loss

    if not sb.is_available():
        print("Supabase indisponibil — verifică SUPABASE_URL/SUPABASE_SECRET_KEY.")
        return 1

    engine = MLPredictorEngine()
    df = engine._fetch_training_dataframe()
    if df is None:
        print("Niciun rând cu rezultat cunoscut — nu se poate rula auditul.")
        return 1

    if "kickoff_date" not in df.columns:
        print("AVERTISMENT: kickoff_date absent — auditul ar fi nesigur temporal. Opresc.")
        return 1
    df = df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)

    y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)
    X = df[FEATURE_COLUMNS].astype(float)

    print(f"Total meciuri folosite: {len(df)}")
    print(f"Feature-uri auditate: {len(FEATURE_COLUMNS)}")
    print()

    # ── 1. Gain importance — modelul final, pe tot istoricul ────────────────
    final_model = XGBClassifier(**FOLD_MODEL_KWARGS)
    final_model.fit(X, y)
    raw_gain = final_model.get_booster().get_score(importance_type="gain")
    gain_by_feature = {f: raw_gain.get(f, 0.0) for f in FEATURE_COLUMNS}
    gain_order = sorted(FEATURE_COLUMNS, key=lambda f: gain_by_feature[f], reverse=True)
    gain_rank = {f: i + 1 for i, f in enumerate(gain_order)}

    print("Gain importance calculat (model final, tot istoricul).")

    # ── 2. Permutation importance — per fold, pe segmentul de validare ──────
    n = len(X)
    boundaries = np.linspace(0, n, N_FOLDS + 2, dtype=int)
    per_feature_fold_deltas_ll = {f: [] for f in FEATURE_COLUMNS}
    per_feature_fold_deltas_acc = {f: [] for f in FEATURE_COLUMNS}
    folds_used = 0

    for k in range(1, N_FOLDS + 1):
        val_start, val_end = boundaries[k], boundaries[k + 1]
        X_tr, y_tr = X.iloc[:val_start], y.iloc[:val_start]
        X_val, y_val = X.iloc[val_start:val_end], y.iloc[val_start:val_end]

        if len(X_tr) < 20 or len(X_val) == 0 or y_tr.nunique() < 2:
            continue
        folds_used += 1

        fold_model = XGBClassifier(**FOLD_MODEL_KWARGS)
        fold_model.fit(X_tr, y_tr)

        baseline_probs = fold_model.predict_proba(X_val)
        baseline_preds = np.argmax(baseline_probs, axis=1)
        baseline_ll = sk_log_loss(y_val, baseline_probs, labels=[0, 1, 2])
        baseline_acc = accuracy_score(y_val, baseline_preds)

        print(f"Fold {k}: train={len(X_tr)}, val={len(X_val)}, "
              f"baseline_logloss={baseline_ll:.4f}, baseline_acc={baseline_acc:.4f}")

        for feat in FEATURE_COLUMNS:
            repeat_deltas_ll = []
            repeat_deltas_acc = []
            for repeat in range(N_REPEATS):
                rng = np.random.RandomState(repeat)
                X_val_perm = X_val.copy()
                X_val_perm[feat] = rng.permutation(X_val_perm[feat].to_numpy())

                probs_p = fold_model.predict_proba(X_val_perm)
                preds_p = np.argmax(probs_p, axis=1)
                ll_p = sk_log_loss(y_val, probs_p, labels=[0, 1, 2])
                acc_p = accuracy_score(y_val, preds_p)

                repeat_deltas_ll.append(ll_p - baseline_ll)
                repeat_deltas_acc.append(baseline_acc - acc_p)

            per_feature_fold_deltas_ll[feat].append(float(np.mean(repeat_deltas_ll)))
            per_feature_fold_deltas_acc[feat].append(float(np.mean(repeat_deltas_acc)))

    print(f"\nFolduri valide folosite pentru permutation importance: {folds_used}/{N_FOLDS}")
    print()

    mean_delta_ll = {f: float(np.mean(v)) if v else float("nan") for f, v in per_feature_fold_deltas_ll.items()}
    std_delta_ll = {f: float(np.std(v)) if v else float("nan") for f, v in per_feature_fold_deltas_ll.items()}
    mean_delta_acc = {f: float(np.mean(v)) if v else float("nan") for f, v in per_feature_fold_deltas_acc.items()}
    std_delta_acc = {f: float(np.std(v)) if v else float("nan") for f, v in per_feature_fold_deltas_acc.items()}

    # ── Verdict — praguri explicite, niciun REMOVE ───────────────────────────
    def verdict(feat: str) -> str:
        m_ll, s_ll = mean_delta_ll[feat], std_delta_ll[feat]
        m_acc = mean_delta_acc[feat]
        rank = gain_rank[feat]

        consistently_positive = (m_ll - s_ll) > 0
        if rank <= CRITICAL_GAIN_RANK and (m_ll >= CRITICAL_DELTA_LL or m_acc >= CRITICAL_DELTA_ACC) and consistently_positive:
            return "CRITICAL"
        if m_ll <= NEGLIGIBLE_DELTA_LL and m_acc <= NEGLIGIBLE_DELTA_ACC:
            return "ABLATION CANDIDATE"
        return "KEEP"

    # ── Tabel final ───────────────────────────────────────────────────────
    print("=" * 108)
    print("AUDIT FEATURE IMPORTANCE — gain + permutation (walk-forward, validare, NU train)")
    print("=" * 108)
    header = "{:<26}{:<10}{:<24}{:<24}{:<20}".format(
        "Feature", "Gain rk", "Perm ΔLogLoss (μ±σ)", "Perm ΔAccuracy (μ±σ)", "Verdict")
    print(header)
    print("-" * 108)
    for feat in gain_order:
        ll_str = f"{mean_delta_ll[feat]:+.4f}±{std_delta_ll[feat]:.4f}"
        acc_str = f"{mean_delta_acc[feat]:+.4f}±{std_delta_acc[feat]:.4f}"
        print("{:<26}{:<10}{:<24}{:<24}{:<20}".format(
            feat, gain_rank[feat], ll_str, acc_str, verdict(feat)))
    print("=" * 108)
    print(f"Praguri folosite: CRITICAL necesită gain rank<=top{CRITICAL_GAIN_RANK} ȘI "
          f"(ΔLogLoss>={CRITICAL_DELTA_LL} SAU ΔAccuracy>={CRITICAL_DELTA_ACC}) ȘI semn constant pozitiv "
          f"între folduri; ABLATION CANDIDATE necesită ΔLogLoss<={NEGLIGIBLE_DELTA_LL} ȘI "
          f"ΔAccuracy<={NEGLIGIBLE_DELTA_ACC}.")
    print()

    # ── Corelații Pearson ─────────────────────────────────────────────────
    corr = X.corr(method="pearson")
    print("=" * 108)
    print("MATRICE CORELAȚII PEARSON")
    print("=" * 108)
    with pd.option_context("display.max_columns", None, "display.width", 220, "display.float_format", "{:.2f}".format):
        print(corr)
    print()

    print("Perechi cu |r| > 0.90:")
    high_corr_pairs = []
    cols = list(corr.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            r = corr.iloc[i, j]
            if pd.notna(r) and abs(r) > 0.90:
                high_corr_pairs.append((cols[i], cols[j], r))
    if high_corr_pairs:
        for a, b, r in high_corr_pairs:
            print(f"  {a} <-> {b}: r={r:.4f}")
    else:
        print("  Nicio pereche cu |r| > 0.90.")
    print("=" * 108)
    print()
    print("Nicio scriere efectuată — doar citire (get_training_data) + calcul local, în memorie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
