"""
TEMPORAR — studiu de ablație pe cele 6 feature-uri marcate ABLATION CANDIDATE
la auditul de feature importance (2026-07-14): card_diff, h2h_meetings,
foul_diff, corner_dominance, home_form_score, h2h_modifier.

Fiecare feature e eliminată INDIVIDUAL (6 experimente independente, nu
cumulative) — X = FEATURE_COLUMNS minus acea feature — și comparată cu
benchmark-ul oficial (walk-forward, 53.409 meciuri):
  Accuracy 0.4868 / Log Loss 1.0253 / Brier Score 0.6145

Pentru fiecare experiment:
  - Accuracy/Log Loss/Brier (walk-forward, aceiași hiperparametri/granițe
    ca MLPredictorEngine._walk_forward_validate() — reutilizată direct,
    fără reimplementare).
  - Timp de antrenare (walk-forward 5 folduri + fit final pe tot istoricul).
  - Numărul de feature-uri rămase (12).
  - Redistribuirea gain importance față de rank-ul de referință (auditul
    anterior, cu toate 13 feature-uri) — semnalează orice feature rămasă
    care urcă/coboară >=2 poziții.

100% read-only față de Supabase — doar MLPredictorEngine._fetch_training_
dataframe() (SELECT). Zero scriere, zero artefact persistat. Fișier
temporar — se șterge după rulare, împreună cu workflow-ul.

Niciun REMOVE automat — doar raportare. Decizia de eliminare permanentă
din FEATURE_COLUMNS rămâne exclusiv a Chief Architect.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np

import supabase_client as sb
from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, RESULT_TO_LABEL

OFFICIAL_BENCHMARK = {"accuracy": 0.4868, "log_loss": 1.0253, "brier_score": 0.6145}

# Gain rank de referință — auditul de feature importance anterior (toate 13
# feature-uri, model final, tot istoricul, 53.409 meciuri, 2026-07-14).
BASELINE_GAIN_RANK = {
    "home_elo": 1, "away_elo": 2, "away_offensive_rating": 3, "h2h_modifier": 4,
    "home_offensive_rating": 5, "home_defensive_rating": 6, "away_defensive_rating": 7,
    "home_form_score": 8, "away_form_score": 9, "corner_dominance": 10,
    "foul_diff": 11, "h2h_meetings": 12, "card_diff": 13,
}

ABLATION_ORDER = [
    "card_diff", "h2h_meetings", "foul_diff",
    "corner_dominance", "home_form_score",
    "h2h_modifier",
]

FOLD_MODEL_KWARGS = dict(
    n_estimators=150, max_depth=4, learning_rate=0.08,
    subsample=0.85, colsample_bytree=0.85,
    objective="multi:softprob", num_class=3,
    eval_metric="mlogloss", random_state=42,
)

# Prag informativ pentru semnal de degradare (nu decizie automată) —
# aceeași granularitate ca la comparația leakage-fix anterioară.
DEGRADATION_LOGLOSS = 0.001
DEGRADATION_ACC = 0.001
RANK_SHIFT_SIGNIFICANT = 2


def main() -> int:
    from xgboost import XGBClassifier

    if not sb.is_available():
        print("Supabase indisponibil — verifică SUPABASE_URL/SUPABASE_SECRET_KEY.")
        return 1

    engine = MLPredictorEngine()
    df = engine._fetch_training_dataframe()
    if df is None:
        print("Niciun rând cu rezultat cunoscut — nu se poate rula studiul.")
        return 1

    if "kickoff_date" not in df.columns:
        print("AVERTISMENT: kickoff_date absent — studiul ar fi nesigur temporal. Opresc.")
        return 1
    df = df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)

    y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)
    X_full = df[FEATURE_COLUMNS].astype(float)

    print(f"Total meciuri folosite: {len(df)}")
    print(f"Benchmark oficial: Accuracy={OFFICIAL_BENCHMARK['accuracy']}, "
          f"Log Loss={OFFICIAL_BENCHMARK['log_loss']}, Brier={OFFICIAL_BENCHMARK['brier_score']}")
    print(f"Ordinea ablațiilor: {', '.join(ABLATION_ORDER)}")
    print()

    results = []

    for idx, feat in enumerate(ABLATION_ORDER, start=1):
        reduced_cols = [c for c in FEATURE_COLUMNS if c != feat]
        X_reduced = X_full[reduced_cols]

        print("=" * 100)
        print(f"EXPERIMENT {idx}/6 — fără '{feat}' ({len(reduced_cols)} feature-uri rămase)")
        print("=" * 100)

        t0 = time.time()
        wf = MLPredictorEngine._walk_forward_validate(X_reduced, y, n_folds=5)

        final_model = XGBClassifier(**FOLD_MODEL_KWARGS)
        final_model.fit(X_reduced, y)
        elapsed = time.time() - t0

        acc = wf["avg_accuracy"]
        ll = wf["avg_log_loss"]
        brier = wf["avg_brier_score"]

        delta_acc = None if acc is None else acc - OFFICIAL_BENCHMARK["accuracy"]
        delta_ll = None if ll is None else ll - OFFICIAL_BENCHMARK["log_loss"]
        delta_brier = None if brier is None else brier - OFFICIAL_BENCHMARK["brier_score"]

        print(f"Folduri valide: {len(wf['folds'])}/5")
        print(f"Timp antrenare (walk-forward + fit final): {elapsed:.1f}s")
        print()
        print("{:<14}{:<14}{:<16}{:<14}".format("Metric", "Benchmark", "Fără feature", "Δ"))
        print("{:<14}{:<14}{:<16}{:<+14.4f}".format(
            "Accuracy", f"{OFFICIAL_BENCHMARK['accuracy']:.4f}",
            f"{acc:.4f}" if acc is not None else "N/A", delta_acc if delta_acc is not None else 0.0))
        print("{:<14}{:<14}{:<16}{:<+14.4f}".format(
            "Log Loss", f"{OFFICIAL_BENCHMARK['log_loss']:.4f}",
            f"{ll:.4f}" if ll is not None else "N/A", delta_ll if delta_ll is not None else 0.0))
        print("{:<14}{:<14}{:<16}{:<+14.4f}".format(
            "Brier", f"{OFFICIAL_BENCHMARK['brier_score']:.4f}",
            f"{brier:.4f}" if brier is not None else "N/A", delta_brier if delta_brier is not None else 0.0))
        print()

        raw_gain = final_model.get_booster().get_score(importance_type="gain")
        gain_by_feature = {f: raw_gain.get(f, 0.0) for f in reduced_cols}
        gain_order = sorted(reduced_cols, key=lambda f: gain_by_feature[f], reverse=True)
        new_rank = {f: i + 1 for i, f in enumerate(gain_order)}

        movers = []
        for f in reduced_cols:
            old_r = BASELINE_GAIN_RANK[f]
            new_r = new_rank[f]
            shift = old_r - new_r  # pozitiv = a urcat (rank mai mic = mai important)
            if abs(shift) >= RANK_SHIFT_SIGNIFICANT:
                movers.append((f, old_r, new_r, shift))
        movers.sort(key=lambda t: -abs(t[3]))

        print(f"Redistribuire gain importance (prag semnificativ: schimbare rank >= {RANK_SHIFT_SIGNIFICANT}):")
        if movers:
            for f, old_r, new_r, shift in movers:
                direction = "URCĂ" if shift > 0 else "COBOARĂ"
                print(f"  {f}: rank {old_r} -> {new_r} ({direction} {abs(shift)} poziții)")
        else:
            print("  Nicio redistribuire semnificativă — toate feature-urile rămase își păstrează rank-ul relativ.")

        degraded = (delta_ll is not None and delta_ll > DEGRADATION_LOGLOSS) or \
                   (delta_acc is not None and delta_acc < -DEGRADATION_ACC)
        signal = "DEGRADARE SEMNALATĂ" if degraded else "FĂRĂ DEGRADARE MĂSURABILĂ"
        print()
        print(f"Semnal informativ (NU decizie automată): {signal}")
        print(f"  (prag: ΔLogLoss > {DEGRADATION_LOGLOSS} SAU ΔAccuracy < -{DEGRADATION_ACC})")
        print()

        results.append({
            "feature": feat, "accuracy": acc, "log_loss": ll, "brier": brier,
            "delta_acc": delta_acc, "delta_ll": delta_ll, "delta_brier": delta_brier,
            "elapsed_s": elapsed, "signal": signal,
        })

    # ── Sumar final ───────────────────────────────────────────────────────
    print("=" * 100)
    print("SUMAR — toate cele 6 experimente (fiecare INDEPENDENT, o singură feature eliminată)")
    print("=" * 100)
    print("{:<20}{:<12}{:<12}{:<12}{:<28}".format(
        "Feature eliminată", "ΔAccuracy", "ΔLogLoss", "ΔBrier", "Semnal"))
    for r in results:
        print("{:<20}{:<+12.4f}{:<+12.4f}{:<+12.4f}{:<28}".format(
            r["feature"], r["delta_acc"] or 0.0, r["delta_ll"] or 0.0, r["delta_brier"] or 0.0, r["signal"]))
    print("=" * 100)
    print()
    print("Nicio scriere efectuată — doar citire (get_training_data) + calcul local, în memorie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
