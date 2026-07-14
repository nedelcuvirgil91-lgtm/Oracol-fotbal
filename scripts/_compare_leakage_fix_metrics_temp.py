"""
TEMPORAR — comparație Accuracy/Log Loss/Brier Score, cod VECHI (imputare cu
mediană globală) vs cod NOU (NaN nativ pentru XGBoost), pe datele reale de
producție (match_history). Folosit o singură dată, prin workflow-ul
_metric_validation_temp.yml, pentru a valida că eliminarea leakage-ului de
imputare (2026-07-14) nu produce un regres real de performanță.

100% read-only față de Supabase — doar sb.get_training_data() (SELECT).
Zero scriere (nu importă promotion_service/challenger_manager/
model_artifact_storage — nimic care ar putea scrie). Zero artefact
persistat. Fișier temporar — se șterge după rulare, împreună cu workflow-ul.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import supabase_client as sb
from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, RESULT_TO_LABEL


def main() -> int:
    if not sb.is_available():
        print("Supabase indisponibil — verifică SUPABASE_URL/SUPABASE_SECRET_KEY.")
        return 1

    rows = sb.get_training_data(only_with_results=True)
    if not rows:
        print("Niciun rând cu rezultat cunoscut — nu se poate compara nimic.")
        return 1
    df = pd.DataFrame(rows)

    # Replică exactă a _fetch_training_dataframe() (ml_predictor.py) —
    # aceeași derivare de coloane, aceeași ordonare cronologică.
    if "home_corner_avg_recent" in df.columns and "away_corner_avg_recent" in df.columns:
        df["corner_dominance"] = df["home_corner_avg_recent"] - df["away_corner_avg_recent"]
    else:
        df["corner_dominance"] = np.nan
    if "home_card_avg_recent" in df.columns and "away_card_avg_recent" in df.columns:
        df["card_diff"] = df["away_card_avg_recent"] - df["home_card_avg_recent"]
    else:
        df["card_diff"] = np.nan
    if "home_foul_avg_recent" in df.columns and "away_foul_avg_recent" in df.columns:
        df["foul_diff"] = df["away_foul_avg_recent"] - df["home_foul_avg_recent"]
    else:
        df["foul_diff"] = np.nan

    for c in FEATURE_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df = df.dropna(subset=["actual_result"])
    df = df[df["actual_result"].isin(["H", "D", "A"])]

    if "kickoff_date" not in df.columns:
        print("AVERTISMENT: kickoff_date absent — comparația ar fi nesigură temporal. Opresc.")
        return 1
    df = df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)

    y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)

    X_new = df[FEATURE_COLUMNS].astype(float)      # cod NOU (curent): NaN nativ, fără imputare
    X_old = X_new.fillna(X_new.median())            # cod VECHI (pre-fix): mediană globală, replicat exact

    print(f"Total meciuri folosite (actual_result cunoscut): {len(df)}")
    print("Rulez walk-forward validation (5 folduri, expanding window) — "
          "identic pentru ambele variante, singura diferență e X.")
    print()

    # Pur compute — _walk_forward_validate() nu are niciun I/O, zero
    # scriere în Supabase, zero artefact persistat.
    wf_old = MLPredictorEngine._walk_forward_validate(X_old, y, n_folds=5)
    wf_new = MLPredictorEngine._walk_forward_validate(X_new, y, n_folds=5)

    def fmt(v):
        return f"{v:.4f}" if v is not None else "N/A"

    metrics = [
        ("Accuracy", wf_old["avg_accuracy"], wf_new["avg_accuracy"]),
        ("Log Loss", wf_old["avg_log_loss"], wf_new["avg_log_loss"]),
        ("Brier Score", wf_old["avg_brier_score"], wf_new["avg_brier_score"]),
    ]

    print("=" * 78)
    print("COMPARAȚIE: cod VECHI (imputare mediană globală) vs cod NOU (NaN nativ)")
    print("=" * 78)
    print("{:<14}{:<12}{:<12}{:<18}{:<15}".format(
        "Metric", "Vechi", "Nou", "Diferență abs.", "Diferență rel."))
    for name, old_v, new_v in metrics:
        if old_v is None or new_v is None:
            print("{:<14}{:<12}{:<12}{:<18}{:<15}".format(name, fmt(old_v), fmt(new_v), "N/A", "N/A"))
            continue
        diff_abs = new_v - old_v
        diff_rel = (diff_abs / old_v * 100.0) if old_v != 0 else float("nan")
        print("{:<14}{:<12.4f}{:<12.4f}{:<+18.4f}{:+14.2f}%".format(
            name, old_v, new_v, diff_abs, diff_rel))
    print("=" * 78)
    print(f"Folduri valide — vechi: {len(wf_old['folds'])}, nou: {len(wf_new['folds'])}")
    print()
    print("Nicio scriere efectuată — doar citire (get_training_data) + calcul local (walk-forward, în memorie).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
