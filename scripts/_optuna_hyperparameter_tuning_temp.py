"""
TEMPORAR — P1 din ML_EVOLUTION_ROADMAP.md: Hyperparameter Tuning (Optuna).

Obiectiv: NU găsirea "celor mai buni hiperparametri", ci demonstrarea
experimentală dacă benchmark-ul oficial (Accuracy 0.4868 / Log Loss 1.0253
/ Brier 0.6145, walk-forward, 53.409 meciuri, ADR-020) poate fi depășit
fără nicio modificare de arhitectură sau de date.

Reguli respectate strict:
  - Același pipeline de evaluare din producție — granițele de fold, split-ul
    train/val, condițiile de skip sunt IDENTICE cu
    MLPredictorEngine._walk_forward_validate() (ml_predictor.py) — doar
    hiperparametrii modelului variază per trial (nereproductibil altfel
    prin apelul direct al metodei, care îi are hardcodați).
  - FEATURE_COLUMNS neschimbat, date obținute exact prin
    MLPredictorEngine._fetch_training_dataframe() (fără reimplementare).
  - random_state=42, objective="multi:softprob", eval_metric="mlogloss"
    fixate — NU sunt parte din spațiul de căutare (determinism, CLAUDE.md).
  - 100% read-only față de Supabase — doar SELECT (get_training_data).
    Zero scriere, zero artefact persistat.

Optimizează în primul rând Log Loss (funcția obiectiv Optuna). Accuracy și
Brier raportate pentru fiecare candidat din top 10. Stabilitatea între
folduri (deviație standard) raportată explicit — o îmbunătățire mai mică
decât zgomotul dintre folduri nu e tratată ca semnal real.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np

import supabase_client as sb
from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, RESULT_TO_LABEL

N_FOLDS = 5
N_TRIALS = 120

OFFICIAL_BENCHMARK = {"accuracy": 0.4868, "log_loss": 1.0253, "brier_score": 0.6145}

# Criteriul de succes P1, exact cum e definit în ML_EVOLUTION_ROADMAP.md.
SUCCESS_LOGLOSS_REL_IMPROVEMENT = 0.005  # >=0.5% relativ
DEGRADATION_ACC = 0.001
DEGRADATION_BRIER = 0.001


def _multiclass_brier(y_true, probs, n_classes: int = 3) -> float:
    one_hot = np.eye(n_classes)[y_true]
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


def _walk_forward_eval(X, y, params: dict, n_folds: int = N_FOLDS):
    """Replică EXACTĂ a granițelor/split-ului din
    MLPredictorEngine._walk_forward_validate() — singura diferență permisă
    e setul de hiperparametri al modelului per fold."""
    from xgboost import XGBClassifier
    from sklearn.metrics import accuracy_score, log_loss as sk_log_loss

    n = len(X)
    boundaries = np.linspace(0, n, n_folds + 2, dtype=int)
    fold_acc, fold_ll, fold_brier = [], [], []

    for k in range(1, n_folds + 1):
        val_start, val_end = boundaries[k], boundaries[k + 1]
        X_tr, y_tr = X.iloc[:val_start], y.iloc[:val_start]
        X_val, y_val = X.iloc[val_start:val_end], y.iloc[val_start:val_end]

        if len(X_tr) < 20 or len(X_val) == 0 or y_tr.nunique() < 2:
            continue

        model = XGBClassifier(**params)
        model.fit(X_tr, y_tr)
        probs = model.predict_proba(X_val)
        preds = np.argmax(probs, axis=1)

        fold_acc.append(float(accuracy_score(y_val, preds)))
        fold_ll.append(float(sk_log_loss(y_val, probs, labels=[0, 1, 2])))
        fold_brier.append(_multiclass_brier(y_val.to_numpy(), probs))

    return fold_acc, fold_ll, fold_brier


def main() -> int:
    import optuna

    if not sb.is_available():
        print("Supabase indisponibil — verifică SUPABASE_URL/SUPABASE_SECRET_KEY.")
        return 1

    engine = MLPredictorEngine()
    df = engine._fetch_training_dataframe()
    if df is None:
        print("Niciun rând cu rezultat cunoscut — nu se poate rula experimentul.")
        return 1
    if "kickoff_date" not in df.columns:
        print("AVERTISMENT: kickoff_date absent — experimentul ar fi nesigur temporal. Opresc.")
        return 1
    df = df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)

    y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)
    X = df[FEATURE_COLUMNS].astype(float)

    print(f"Total meciuri folosite: {len(df)}")
    print(f"Benchmark oficial: Accuracy={OFFICIAL_BENCHMARK['accuracy']}, "
          f"Log Loss={OFFICIAL_BENCHMARK['log_loss']}, Brier={OFFICIAL_BENCHMARK['brier_score']}")
    print(f"Optuna: {N_TRIALS} trial-uri, obiectiv = Log Loss mediu (walk-forward, {N_FOLDS} folduri)")
    print()

    trial_results: list[dict] = []

    def objective(trial: "optuna.Trial") -> float:
        params = dict(
            n_estimators=trial.suggest_int("n_estimators", 50, 400),
            max_depth=trial.suggest_int("max_depth", 2, 8),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            subsample=trial.suggest_float("subsample", 0.5, 1.0),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.5, 1.0),
            min_child_weight=trial.suggest_int("min_child_weight", 1, 10),
            reg_alpha=trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            reg_lambda=trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            gamma=trial.suggest_float("gamma", 1e-8, 5.0, log=True),
            objective="multi:softprob", num_class=3, eval_metric="mlogloss", random_state=42,
        )

        t0 = time.time()
        fold_acc, fold_ll, fold_brier = _walk_forward_eval(X, y, params, n_folds=N_FOLDS)
        elapsed = time.time() - t0

        if not fold_ll:
            return float("inf")

        avg_acc, avg_ll, avg_brier = float(np.mean(fold_acc)), float(np.mean(fold_ll)), float(np.mean(fold_brier))
        std_acc, std_ll, std_brier = float(np.std(fold_acc)), float(np.std(fold_ll)), float(np.std(fold_brier))

        trial_results.append({
            "number": trial.number, "params": dict(params),
            "avg_accuracy": avg_acc, "avg_log_loss": avg_ll, "avg_brier": avg_brier,
            "std_accuracy": std_acc, "std_log_loss": std_ll, "std_brier": std_brier,
            "n_folds_valid": len(fold_ll), "elapsed_s": elapsed,
            "fold_accuracy": fold_acc, "fold_log_loss": fold_ll, "fold_brier": fold_brier,
        })
        return avg_ll

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42))
    study_t0 = time.time()
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
    study_elapsed = time.time() - study_t0

    print(f"Studiu Optuna încheiat: {len(trial_results)}/{N_TRIALS} trial-uri valide, "
          f"{study_elapsed:.1f}s total.")
    print()

    ranked = sorted(trial_results, key=lambda r: r["avg_log_loss"])
    top10 = ranked[:10]

    print("=" * 110)
    print(f"TOP 10 configurații după Log Loss (din {len(trial_results)} trial-uri)")
    print("=" * 110)
    for i, r in enumerate(top10, start=1):
        print(f"\n--- #{i} (trial {r['number']}) ---")
        print(f"Hiperparametri: {r['params']}")
        print(f"Accuracy : {r['avg_accuracy']:.4f}  (std între folduri: {r['std_accuracy']:.4f})")
        print(f"Log Loss : {r['avg_log_loss']:.4f}  (std între folduri: {r['std_log_loss']:.4f})")
        print(f"Brier    : {r['avg_brier']:.4f}  (std între folduri: {r['std_brier']:.4f})")
        print(f"Timp antrenare (5 folduri): {r['elapsed_s']:.1f}s")
        print(f"Log Loss per fold: {[round(v, 4) for v in r['fold_log_loss']]}")
        print(f"Accuracy per fold: {[round(v, 4) for v in r['fold_accuracy']]}")

    best = top10[0]
    delta_ll = best["avg_log_loss"] - OFFICIAL_BENCHMARK["log_loss"]
    delta_ll_rel = delta_ll / OFFICIAL_BENCHMARK["log_loss"] * 100.0
    delta_acc = best["avg_accuracy"] - OFFICIAL_BENCHMARK["accuracy"]
    delta_brier = best["avg_brier"] - OFFICIAL_BENCHMARK["brier_score"]

    print()
    print("=" * 110)
    print("COMPARAȚIE cu benchmark-ul oficial (cel mai bun candidat după Log Loss)")
    print("=" * 110)
    print(f"Log Loss : {OFFICIAL_BENCHMARK['log_loss']:.4f} -> {best['avg_log_loss']:.4f}  "
          f"({delta_ll:+.4f}, {delta_ll_rel:+.2f}%)")
    print(f"Accuracy : {OFFICIAL_BENCHMARK['accuracy']:.4f} -> {best['avg_accuracy']:.4f}  ({delta_acc:+.4f})")
    print(f"Brier    : {OFFICIAL_BENCHMARK['brier_score']:.4f} -> {best['avg_brier']:.4f}  ({delta_brier:+.4f})")

    meets_logloss = delta_ll <= -SUCCESS_LOGLOSS_REL_IMPROVEMENT * OFFICIAL_BENCHMARK["log_loss"]
    no_acc_degradation = delta_acc >= -DEGRADATION_ACC
    no_brier_degradation = delta_brier <= DEGRADATION_BRIER
    criterion_met = meets_logloss and no_acc_degradation and no_brier_degradation

    # Stabilitate: îmbunătățirea absolută trebuie să depășească clar
    # zgomotul dintre folduri (std), altfel e potențial noroc statistic,
    # nu semnal real -- prag euristic explicit, nu ascuns.
    stability_ok = best["std_log_loss"] < abs(delta_ll) * 3 if delta_ll < 0 else False

    print()
    print(f"Criteriu succes P1 (ML_EVOLUTION_ROADMAP.md): Log Loss >=0.5% mai bun ȘI fără "
          f"degradare >0.001 pe Accuracy/Brier -> {'ÎNDEPLINIT' if criterion_met else 'NEÎNDEPLINIT'}")
    if delta_ll < 0:
        print(f"Stabilitate între folduri (std Log Loss={best['std_log_loss']:.4f} vs. "
              f"îmbunătățire={abs(delta_ll):.4f}): {'OK' if stability_ok else 'SUB SEMN DE ÎNTREBARE'}")
    else:
        print("Stabilitate între folduri: N/A -- cel mai bun candidat nu îmbunătățește deloc Log Loss "
              "față de benchmark.")
    print()

    if criterion_met and stability_ok:
        print("RECOMANDARE FINALĂ: ACCEPTED -- propun promovarea configurației de mai sus în producție.")
    elif criterion_met and not stability_ok:
        print("RECOMANDARE FINALĂ: REJECTED (condiționat) -- criteriul numeric e îndeplinit, dar "
              "îmbunătățirea e mai mică decât variația între folduri -- posibil noroc statistic, nu "
              "semnal real. Recomand o rulare a doua, mai amplă (300-500 trial-uri), concentrată în "
              "jurul acestei zone a spațiului de căutare, înainte de orice decizie de promovare.")
    else:
        print("RECOMANDARE FINALĂ: REJECTED -- niciun candidat nu îndeplinește criteriul de succes "
              "din ML_EVOLUTION_ROADMAP.md P1. Configurația actuală de producție rămâne neschimbată.")

    print()
    print("Nicio scriere efectuată — doar citire (get_training_data) + calcul local (Optuna, în memorie).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
