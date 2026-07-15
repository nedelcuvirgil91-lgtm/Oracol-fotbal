"""
TEMPORAR — P1.1 din ML_EVOLUTION_ROADMAP.md: Hyperparameter Tuning
focalizat, urmare directă a P1 (120 trial-uri, REJECTED oficial — cel mai
bun candidat: Log Loss -0,46% relativ, sub pragul de succes de -0,5%, dar
convergență clară, nu zgomot).

NU e o repetare a P1 — e un experiment nou, cu 3 diferențe deliberate:
  1. Spațiu de căutare restrâns la regiunea unde Optuna a convers natural
     în P1 (max_depth mic, learning_rate mic, n_estimators mare,
     regularizare pozitivă).
  2. Early stopping la nivel de trial — pruning Optuna (MedianPruner),
     bazat pe Log Loss cumulat mediu după fiecare fold, comparat relativ
     cu celelalte trial-uri din același studiu (corect statistic: fold-ul
     1 e sistematic mai greu decât fold-ul 5 pentru TOATE trial-urile,
     comparația relativă la același pas nu e afectată de asta).
  3. Obiectiv compus, nu doar Log Loss mediu — accent explicit pe
     stabilitate: avg_log_loss + 0.3 * std_log_loss între folduri.

Criteriul oficial de succes rămâne NESCHIMBAT față de P1 (nu se mută
pragul după rezultat): Log Loss >=0.5% relativ mai bun ȘI fără degradare
>0.001 pe Accuracy/Brier (ML_EVOLUTION_ROADMAP.md, P1). Adăugat, ca
verificare suplimentară de stabilitate cerută explicit pentru această
rundă: câte din cele 5 folduri individuale bat efectiv benchmark-ul (nu
doar media) — raportat, nu ascuns într-un singur prag compus.

Dacă niciun candidat nu trece criteriul oficial în această rundă,
Hyperparameter Tuning se închide definitiv (decizie deja luată) — nu se
mai reiau alte runde decât dacă se schimbă feature-urile, ELO-ul, sau
datele.

100% read-only față de Supabase — doar SELECT (get_training_data). Zero
scriere, zero artefact persistat.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np

import supabase_client as sb
from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, RESULT_TO_LABEL

N_FOLDS = 5
N_TRIALS = 400
STABILITY_PENALTY_WEIGHT = 0.3  # obiectiv = avg_log_loss + weight * std_log_loss

OFFICIAL_BENCHMARK = {"accuracy": 0.4868, "log_loss": 1.0253, "brier_score": 0.6145}

# Criteriul de succes P1 -- NESCHIMBAT față de runda anterioară.
SUCCESS_LOGLOSS_REL_IMPROVEMENT = 0.005  # >=0.5% relativ
DEGRADATION_ACC = 0.001
DEGRADATION_BRIER = 0.001


def _multiclass_brier(y_true, probs, n_classes: int = 3) -> float:
    one_hot = np.eye(n_classes)[y_true]
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


def _walk_forward_eval_with_pruning(X, y, params: dict, trial, n_folds: int = N_FOLDS):
    """Identică la granițe/split cu MLPredictorEngine._walk_forward_validate()
    -- adaugă raportare incrementală către Optuna (pentru pruning) după
    fiecare fold, pe baza mediei cumulate de Log Loss."""
    import optuna
    from xgboost import XGBClassifier
    from sklearn.metrics import accuracy_score, log_loss as sk_log_loss

    n = len(X)
    boundaries = np.linspace(0, n, n_folds + 2, dtype=int)
    fold_acc, fold_ll, fold_brier = [], [], []

    step = 0
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

        trial.report(float(np.mean(fold_ll)), step)
        if trial.should_prune():
            raise optuna.TrialPruned()
        step += 1

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
    print(f"P1.1 -- Optuna focalizat: {N_TRIALS} trial-uri, spațiu de căutare restrâns, "
          f"pruning activ, obiectiv = avg_log_loss + {STABILITY_PENALTY_WEIGHT}*std_log_loss")
    print()

    trial_results: list[dict] = []

    def objective(trial: "optuna.Trial") -> float:
        params = dict(
            # Spațiu restrâns la regiunea de convergență descoperită în P1
            # (top 10 din 120 trial-uri): n_estimators mare, max_depth mic,
            # learning_rate mic, regularizare pozitivă.
            n_estimators=trial.suggest_int("n_estimators", 250, 450),
            max_depth=trial.suggest_int("max_depth", 2, 3),
            learning_rate=trial.suggest_float("learning_rate", 0.02, 0.06, log=True),
            subsample=trial.suggest_float("subsample", 0.6, 0.9),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.55, 0.85),
            min_child_weight=trial.suggest_int("min_child_weight", 5, 10),
            reg_alpha=trial.suggest_float("reg_alpha", 1e-8, 1e-3, log=True),
            reg_lambda=trial.suggest_float("reg_lambda", 0.01, 10.0, log=True),
            gamma=trial.suggest_float("gamma", 0.1, 3.5, log=True),
            objective="multi:softprob", num_class=3, eval_metric="mlogloss", random_state=42,
        )

        t0 = time.time()
        fold_acc, fold_ll, fold_brier = _walk_forward_eval_with_pruning(X, y, params, trial, n_folds=N_FOLDS)
        elapsed = time.time() - t0

        if not fold_ll:
            return float("inf")

        avg_acc, avg_ll, avg_brier = float(np.mean(fold_acc)), float(np.mean(fold_ll)), float(np.mean(fold_brier))
        std_acc, std_ll, std_brier = float(np.std(fold_acc)), float(np.std(fold_ll)), float(np.std(fold_brier))
        folds_beating_benchmark = sum(1 for v in fold_ll if v <= OFFICIAL_BENCHMARK["log_loss"])

        trial_results.append({
            "number": trial.number, "params": dict(params),
            "avg_accuracy": avg_acc, "avg_log_loss": avg_ll, "avg_brier": avg_brier,
            "std_accuracy": std_acc, "std_log_loss": std_ll, "std_brier": std_brier,
            "n_folds_valid": len(fold_ll), "elapsed_s": elapsed,
            "fold_accuracy": fold_acc, "fold_log_loss": fold_ll, "fold_brier": fold_brier,
            "folds_beating_benchmark": folds_beating_benchmark,
        })
        return avg_ll + STABILITY_PENALTY_WEIGHT * std_ll

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    pruner = optuna.pruners.MedianPruner(n_startup_trials=30, n_warmup_steps=2)
    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=42), pruner=pruner)
    study_t0 = time.time()
    study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
    study_elapsed = time.time() - study_t0

    n_pruned = sum(1 for t in study.trials if t.state == optuna.trial.TrialState.PRUNED)
    print(f"Studiu Optuna încheiat: {len(trial_results)}/{N_TRIALS} trial-uri complete, "
          f"{n_pruned} întrerupte prin pruning (early stopping), {study_elapsed:.1f}s total.")
    print()

    # Top 10 după obiectivul REAL de succes (Log Loss mediu, nu obiectivul
    # compus folosit pentru căutare) -- comparabil direct cu benchmark-ul
    # și cu P1.
    ranked = sorted(trial_results, key=lambda r: r["avg_log_loss"])
    top10 = ranked[:10]

    print("=" * 116)
    print(f"TOP 10 configurații după Log Loss mediu (din {len(trial_results)} trial-uri complete)")
    print("=" * 116)
    for i, r in enumerate(top10, start=1):
        print(f"\n--- #{i} (trial {r['number']}) ---")
        print(f"Hiperparametri: {r['params']}")
        print(f"Accuracy : {r['avg_accuracy']:.4f}  (std între folduri: {r['std_accuracy']:.4f})")
        print(f"Log Loss : {r['avg_log_loss']:.4f}  (std între folduri: {r['std_log_loss']:.4f})")
        print(f"Brier    : {r['avg_brier']:.4f}  (std între folduri: {r['std_brier']:.4f})")
        print(f"Timp antrenare (5 folduri): {r['elapsed_s']:.1f}s")
        print(f"Log Loss per fold: {[round(v, 4) for v in r['fold_log_loss']]}")
        print(f"Accuracy per fold: {[round(v, 4) for v in r['fold_accuracy']]}")
        print(f"Folduri care bat benchmark-ul (Log Loss individual <= {OFFICIAL_BENCHMARK['log_loss']}): "
              f"{r['folds_beating_benchmark']}/5")

    best = top10[0]
    delta_ll = best["avg_log_loss"] - OFFICIAL_BENCHMARK["log_loss"]
    delta_ll_rel = delta_ll / OFFICIAL_BENCHMARK["log_loss"] * 100.0
    delta_acc = best["avg_accuracy"] - OFFICIAL_BENCHMARK["accuracy"]
    delta_brier = best["avg_brier"] - OFFICIAL_BENCHMARK["brier_score"]

    print()
    print("=" * 116)
    print("COMPARAȚIE cu benchmark-ul oficial (cel mai bun candidat după Log Loss mediu)")
    print("=" * 116)
    print(f"Log Loss : {OFFICIAL_BENCHMARK['log_loss']:.4f} -> {best['avg_log_loss']:.4f}  "
          f"({delta_ll:+.4f}, {delta_ll_rel:+.2f}%)")
    print(f"Accuracy : {OFFICIAL_BENCHMARK['accuracy']:.4f} -> {best['avg_accuracy']:.4f}  ({delta_acc:+.4f})")
    print(f"Brier    : {OFFICIAL_BENCHMARK['brier_score']:.4f} -> {best['avg_brier']:.4f}  ({delta_brier:+.4f})")
    print(f"Folduri individuale care bat benchmark-ul: {best['folds_beating_benchmark']}/5")

    meets_logloss = delta_ll <= -SUCCESS_LOGLOSS_REL_IMPROVEMENT * OFFICIAL_BENCHMARK["log_loss"]
    no_acc_degradation = delta_acc >= -DEGRADATION_ACC
    no_brier_degradation = delta_brier <= DEGRADATION_BRIER
    criterion_met = meets_logloss and no_acc_degradation and no_brier_degradation
    all_folds_win = best["folds_beating_benchmark"] == 5

    print()
    print(f"Criteriu OFICIAL de succes P1 (neschimbat): Log Loss >=0.5% mai bun ȘI fără degradare "
          f">0.001 pe Accuracy/Brier -> {'ÎNDEPLINIT' if criterion_met else 'NEÎNDEPLINIT'}")
    print(f"Verificare suplimentară de stabilitate (cerută explicit pentru P1.1): câștigă pe toate "
          f"cele 5 folduri individual -> {'DA' if all_folds_win else 'NU'} "
          f"({best['folds_beating_benchmark']}/5)")
    print()

    if criterion_met and all_folds_win:
        print("RECOMANDARE FINALĂ: ACCEPTED -- propun promovarea configurației de mai sus în "
              "producție. Câștigă atât în medie, cât și pe fiecare fold individual -- semnal solid, "
              "nu noroc statistic.")
    elif criterion_met and not all_folds_win:
        print("RECOMANDARE FINALĂ: ACCEPTED, cu rezervă -- criteriul oficial e îndeplinit, dar nu "
              "câștigă pe toate cele 5 folduri. Decizia de promovare rămâne a Chief Architect.")
    else:
        print("RECOMANDARE FINALĂ: REJECTED -- niciun candidat nu îndeplinește criteriul oficial de "
              "succes din ML_EVOLUTION_ROADMAP.md P1, nici în această rundă focalizată. Conform "
              "deciziei deja luate, Hyperparameter Tuning se închide definitiv -- configurația "
              "actuală de producție rămâne neschimbată.")

    print()
    print("Nicio scriere efectuată — doar citire (get_training_data) + calcul local (Optuna, în memorie).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
