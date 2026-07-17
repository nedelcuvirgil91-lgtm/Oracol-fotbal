"""
TEMPORAR -- verificare de convergenta post-activare V2_damped (Migration Plan
§3.5.3, docs/03_ENGINE/P3_MOV_ACTIVATION_DESIGN_REVIEW_MIGRATION_PLAN_2026-07-15.md).

Ruleaza walk-forward READ-ONLY pe match_history-ul de PRODUCTIE, deja
actualizat (home_elo/away_elo/home_offensive_rating/home_defensive_rating/
away_offensive_rating/away_defensive_rating scrise de run_backfill() cu
formula MOV V2_damped, ADR-022) -- FARA niciun override, se folosesc direct
valorile deja stocate in DB, spre deosebire de scripts/_p3_revalidation_
replay_temp.py (care calcula in memorie, fara scriere).

Compara cu cifrele deja publicate in P3_REVALIDATION_POST_P3_5_2026-07-15.md
pentru V2_damped: Accuracy 0.4992, Log Loss 1.0121, Brier 0.6051 -- trebuie
apropiate (nu identice, dat fiind rotunjirea la scriere in DB vs. calcul
in-memory), nu grav divergente.

100% read-only fata de Supabase (doar SELECT, prin MLPredictorEngine).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
from sklearn.metrics import accuracy_score, log_loss as sk_log_loss
from xgboost import XGBClassifier

from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, RESULT_TO_LABEL

N_FOLDS = 5
PRODUCTION_PARAMS = dict(
    n_estimators=150, max_depth=4, learning_rate=0.08,
    subsample=0.85, colsample_bytree=0.85,
    objective="multi:softprob", num_class=3,
    eval_metric="mlogloss", random_state=42,
)
EXPECTED_V2_DAMPED = {"accuracy": 0.4992, "log_loss": 1.0121, "brier_score": 0.6051}


def multiclass_brier(y_true, probs, n_classes=3):
    one_hot = np.eye(n_classes)[y_true]
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


def walk_forward(df, n_folds=N_FOLDS):
    X = df[FEATURE_COLUMNS].astype(float)
    y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)
    n = len(X)
    boundaries = np.linspace(0, n, n_folds + 2, dtype=int)
    folds = []
    for k in range(1, n_folds + 1):
        val_start, val_end = boundaries[k], boundaries[k + 1]
        X_tr, y_tr = X.iloc[:val_start], y.iloc[:val_start]
        X_val, y_val = X.iloc[val_start:val_end], y.iloc[val_start:val_end]
        if len(X_tr) < 20 or len(X_val) == 0 or y_tr.nunique() < 2:
            continue
        model = XGBClassifier(**PRODUCTION_PARAMS)
        model.fit(X_tr, y_tr)
        probs = model.predict_proba(X_val)
        preds = np.argmax(probs, axis=1)
        acc = float(accuracy_score(y_val, preds))
        ll = float(sk_log_loss(y_val, probs, labels=[0, 1, 2]))
        brier = multiclass_brier(y_val.to_numpy(), probs)
        folds.append({"fold": k, "train": len(X_tr), "val": len(X_val),
                       "accuracy": round(acc, 4), "log_loss": round(ll, 4), "brier_score": round(brier, 4)})
    summary = {
        "avg_accuracy": round(float(np.mean([f["accuracy"] for f in folds])), 4),
        "avg_log_loss": round(float(np.mean([f["log_loss"] for f in folds])), 4),
        "avg_brier_score": round(float(np.mean([f["brier_score"] for f in folds])), 4),
    }
    return folds, summary


def main() -> int:
    print("Se incarca datele de antrenare din productie (match_history, deja actualizat cu V2_damped) ...")
    engine = MLPredictorEngine()
    base_df = engine._fetch_training_dataframe()
    if base_df is None or base_df.empty:
        print("Fara date de antrenare disponibile.")
        return 1
    if "kickoff_date" in base_df.columns:
        base_df = base_df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)

    missing_elo = int(base_df["home_elo"].isna().sum())
    print(f"{len(base_df)} randuri incarcate. elo lipsa pentru {missing_elo} randuri (ar trebui 0).\n")

    folds, summary = walk_forward(base_df)
    print("=" * 80)
    print("WALK-FORWARD PE match_history DE PRODUCTIE (V2_damped, deja scris in DB)")
    print("=" * 80)
    for f in folds:
        print(f"  fold {f['fold']}: train={f['train']} val={f['val']} "
              f"acc={f['accuracy']} log_loss={f['log_loss']} brier={f['brier_score']}")
    print(f"\nMEDIE: {summary}")
    print(f"AȘTEPTAT (P3_REVALIDATION_POST_P3_5, V2_damped, calcul in-memory): {EXPECTED_V2_DAMPED}")

    d_acc = abs(summary["avg_accuracy"] - EXPECTED_V2_DAMPED["accuracy"])
    d_ll = abs(summary["avg_log_loss"] - EXPECTED_V2_DAMPED["log_loss"])
    d_brier = abs(summary["avg_brier_score"] - EXPECTED_V2_DAMPED["brier_score"])
    print(f"\nDiferente absolute: Accuracy={d_acc:.4f}, Log Loss={d_ll:.4f}, Brier={d_brier:.4f}")

    # Prag de convergenta: 0.01 absolut (1pp Accuracy, 0.01 Log Loss/Brier) --
    # tolereaza rotunjire DB + fixture-uri noi aparute intre timp (ex. World
    # Cup 2026 in desfasurare), nu tolereaza o discrepanta structurala.
    threshold = 0.01
    converges = d_acc <= threshold and d_ll <= threshold and d_brier <= threshold
    print(f"\nCONVERGE (prag {threshold} absolut pe toate 3 metrici): {converges}")
    print("\nNicio scriere efectuata -- doar citire (get_training_data) + calcul local, in memorie.")
    return 0 if converges else 2


if __name__ == "__main__":
    sys.exit(main())
