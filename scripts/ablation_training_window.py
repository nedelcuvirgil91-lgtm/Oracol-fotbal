"""
================================================================================
FOOTBALL ORACLE — Ablație: cât istoric merită folosit la antrenarea ML?
================================================================================
Module: scripts/ablation_training_window.py

STRICT read-only. Nu scrie nimic, nicăieri — nici în Supabase, nici pe disc,
nici în Storage. Nu creează Challenger, nu atinge `ml_model_status`, nu
înregistrează nicio rulare de antrenare.

ÎNTREBAREA, pusă de proprietarul produsului (2026-09-06): „meciurile/sezoanele
vechi mai sunt relevante? poate XGBoost ar trebui antrenat doar cu meciurile
din acest sezon."

E o schimbare a parametrilor de model, deci — per regula proiectului — se
demonstrează cu ablație pe date reale, niciodată din intuiție (precedente:
ADR-012/013/021, toate promovate prin ablație walk-forward măsurată).

── PROIECTAREA EXPERIMENTULUI ────────────────────────────────────────────
Ce variază: EXCLUSIV fereastra de antrenare.
Ce rămâne fix: setul de test, feature-urile, hiperparametrii, sămânța.

`rolling origin` cu blocuri consecutive de test la coada istoricului. Pentru
fiecare bloc, fiecare fereastră antrenează pe meciuri STRICT ANTERIOARE
începutului blocului și e evaluată pe ACELAȘI bloc — deci comparația e
cap-la-cap, iar scurgerea temporală e imposibilă prin construcție.

Un singur bloc de test ar fi fost la mila unei perioade norocoase. Mai multe
blocuri consecutive dau un verdict robust și respectă disciplina walk-forward.

`sezon_curent` e definit onest: de la ultimul 1 iulie dinaintea blocului —
adică exact ce înseamnă „sezonul în curs" la momentul acelei predicții, nu o
fereastră de lungime fixă.

`tot + pondere vechime` NU taie nimic: antrenează pe tot istoricul, dar cu
`sample_weight` din `recalibration.compute_recency_weight()` (decădere
exponențială, half-life din config) — formula deja existentă în proiect,
folosită azi la recalibrarea ponderilor Oracle, niciodată la antrenarea ML.

── FIDELITATE FAȚĂ DE PRODUCȚIE ──────────────────────────────────────────
Datele vin prin `supabase_client.get_training_data()`, feature-urile se
construiesc prin `ml_feature_pipeline.compute_derived_dominance_features()` și
`ml_predictor.FEATURE_COLUMNS`, Brier-ul e calculat de
`MLPredictorEngine._multiclass_brier()` — toate, funcții de producție. Singurul
lucru copiat aici sunt hiperparametrii XGBoost; un test verifică prin AST că
n-au divergit față de `ml_predictor`.

Utilizare:
    python scripts/ablation_training_window.py
    python scripts/ablation_training_window.py --blocuri 4 --marime-bloc 400
================================================================================
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

BAR = "=" * 78

# Hiperparametrii XGBoost din producție (`ml_predictor.py`, antrenarea finală
# ȘI fiecare fold walk-forward — identici în ambele locuri). Copiați aici
# deliberat, ca ablația să nu depindă de o refactorizare a motorului; garda
# `tests/test_ablation_training_window.py` citește sursa `ml_predictor` prin
# AST și cade dacă cele două se despart.
HIPERPARAMETRI = dict(
    n_estimators=150, max_depth=4, learning_rate=0.08,
    subsample=0.85, colsample_bytree=0.85,
    objective="multi:softprob", num_class=3,
    eval_metric="mlogloss", random_state=42,
)

ETICHETE = {"H": 0, "D": 1, "A": 2}

# Ferestrele comparate. `None` = tot istoricul disponibil înaintea blocului.
FERESTRE: list[tuple[str, int | None]] = [
    ("tot istoricul (azi)", None),
    ("36 luni", 1096),
    ("24 luni", 731),
    ("12 luni", 365),
    ("6 luni", 183),
    ("3 luni", 91),
]

MIN_ANTRENARE = 30  # oglindește ml_predictor.MIN_SAMPLES_TO_TRAIN


def inceput_sezon(referinta: date) -> date:
    """Ultimul 1 iulie dinaintea datei date — începutul sezonului în curs."""
    an = referinta.year if referinta.month >= 7 else referinta.year - 1
    return date(an, 7, 1)


def _ca_data(valoare) -> date | None:
    try:
        return date.fromisoformat(str(valoare).strip()[:10])
    except (ValueError, TypeError):
        return None


def evalueaza(model, X_test, y_test) -> dict:
    """Aceleași trei metrici ca peste tot în proiect (North Star #2)."""
    import numpy as np
    from sklearn.metrics import accuracy_score, log_loss as sk_log_loss

    from ml_predictor import MLPredictorEngine

    probs = model.predict_proba(X_test)
    preds = np.argmax(probs, axis=1)
    return {
        "acuratete": float(accuracy_score(y_test, preds)),
        "log_loss": float(sk_log_loss(y_test, probs, labels=[0, 1, 2])),
        "brier": MLPredictorEngine._multiclass_brier(np.asarray(y_test), probs),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ablație: cât istoric merită folosit la antrenarea ML (read-only)")
    parser.add_argument("--blocuri", type=int, default=4, help="câte blocuri de test (implicit 4)")
    parser.add_argument("--marime-bloc", type=int, default=400,
                        help="câte meciuri per bloc de test (implicit 400)")
    parser.add_argument("--half-life", type=float, default=365.0,
                        help="half-life în zile pentru varianta cu ponderare (implicit 365)")
    args = parser.parse_args()

    import numpy as np
    import pandas as pd
    from xgboost import XGBClassifier

    import supabase_client as sb
    from ml_feature_pipeline import compute_derived_dominance_features
    from ml_predictor import FEATURE_COLUMNS
    from recalibration import compute_recency_weight

    if not sb.is_available():
        print("EROARE: Supabase indisponibil (SUPABASE_URL / SUPABASE_SECRET_KEY).")
        return 1

    print(BAR)
    print("  ABLAȚIE — cât istoric merită folosit la antrenarea ML")
    print("  READ-ONLY. Zero scriere. Zero Challenger. Zero atingere de producție.")
    print(BAR)

    randuri = sb.get_training_data(only_with_results=True)
    if not randuri:
        print("EROARE: niciun meci cu rezultat.")
        return 1

    df = pd.DataFrame(randuri)
    df = compute_derived_dominance_features(df)
    for coloana in FEATURE_COLUMNS:
        if coloana not in df.columns:
            df[coloana] = np.nan
    df = df[df["actual_result"].isin(list(ETICHETE))].copy()
    df["_data"] = df["kickoff_date"].map(_ca_data)
    df = df.dropna(subset=["_data"]).sort_values("_data").reset_index(drop=True)

    n = len(df)
    total_test = args.blocuri * args.marime_bloc
    if n < total_test + MIN_ANTRENARE:
        print(f"EROARE: doar {n} meciuri, insuficiente pentru {args.blocuri}×{args.marime_bloc}.")
        return 1

    print(f"\n  Meciuri disponibile: {n}  ({df['_data'].iloc[0]} → {df['_data'].iloc[-1]})")
    print(f"  Blocuri de test: {args.blocuri} × {args.marime_bloc} meciuri, consecutive, la coadă")
    print(f"  Ferestre comparate: {len(FERESTRE) + 2}\n")

    X_tot = df[FEATURE_COLUMNS]
    y_tot = df["actual_result"].map(ETICHETE)

    variante = [n for n, _ in FERESTRE] + ["sezon curent", f"tot + pondere ({args.half_life:.0f}z)"]
    acumulat: dict[str, list[tuple[int, dict]]] = {v: [] for v in variante}
    nesuficiente: dict[str, int] = {v: 0 for v in variante}

    prim_test = n - total_test
    for b in range(args.blocuri):
        start = prim_test + b * args.marime_bloc
        stop = start + args.marime_bloc
        data_start = df["_data"].iloc[start]
        X_test, y_test = X_tot.iloc[start:stop], y_tot.iloc[start:stop]

        print(f"  Bloc {b + 1}/{args.blocuri} — test pe {len(X_test)} meciuri "
              f"({data_start} → {df['_data'].iloc[stop - 1]})")

        for nume, zile in FERESTRE + [("sezon curent", -1)]:
            if zile is None:
                masca = df.index < start
            elif zile == -1:
                prag = inceput_sezon(data_start)
                masca = (df.index < start) & (df["_data"] >= prag)
            else:
                prag = data_start - timedelta(days=zile)
                masca = (df.index < start) & (df["_data"] >= prag)

            X_tr, y_tr = X_tot[masca], y_tot[masca]
            if len(X_tr) < MIN_ANTRENARE or y_tr.nunique() < 2:
                nesuficiente[nume] += 1
                print(f"      {nume:<24s}  {len(X_tr):>6d} antrenare  — INSUFICIENT, sărit")
                continue

            model = XGBClassifier(**HIPERPARAMETRI)
            model.fit(X_tr, y_tr)
            m = evalueaza(model, X_test, y_test)
            acumulat[nume].append((len(X_test), m))
            print(f"      {nume:<24s}  {len(X_tr):>6d} antrenare  "
                  f"acc={m['acuratete']:.4f}  ll={m['log_loss']:.4f}  brier={m['brier']:.4f}")

        # Varianta cu ponderare: tot istoricul, dar meciurile vechi cântăresc mai puțin.
        nume_p = f"tot + pondere ({args.half_life:.0f}z)"
        masca = df.index < start
        X_tr, y_tr = X_tot[masca], y_tot[masca]
        if len(X_tr) >= MIN_ANTRENARE and y_tr.nunique() >= 2:
            greutati = np.array([
                compute_recency_weight(d, args.half_life, reference_date=data_start)
                for d in df.loc[masca, "_data"]
            ])
            model = XGBClassifier(**HIPERPARAMETRI)
            model.fit(X_tr, y_tr, sample_weight=greutati)
            m = evalueaza(model, X_test, y_test)
            acumulat[nume_p].append((len(X_test), m))
            print(f"      {nume_p:<24s}  {len(X_tr):>6d} antrenare  "
                  f"acc={m['acuratete']:.4f}  ll={m['log_loss']:.4f}  brier={m['brier']:.4f}")
        else:
            nesuficiente[nume_p] += 1
        print()

    print(BAR)
    print("  AGREGAT pe toate blocurile (medie ponderată după mărimea blocului)")
    print(BAR)
    print(f"  {'Fereastră de antrenare':<26s} {'Acuratețe':>10s} {'Log-loss':>10s} {'Brier':>10s}   Blocuri")

    referinta = None
    rezumat: list[tuple[str, dict, int]] = []
    for nume in variante:
        parti = acumulat[nume]
        if not parti:
            print(f"  {nume:<26s} {'—':>10s} {'—':>10s} {'—':>10s}   0 (insuficiente date)")
            continue
        total = sum(w for w, _ in parti)
        agg = {
            cheie: sum(w * m[cheie] for w, m in parti) / total
            for cheie in ("acuratete", "log_loss", "brier")
        }
        rezumat.append((nume, agg, len(parti)))
        if nume == "tot istoricul (azi)":
            referinta = agg
        print(f"  {nume:<26s} {agg['acuratete']:>10.4f} {agg['log_loss']:>10.4f} "
              f"{agg['brier']:>10.4f}   {len(parti)}/{args.blocuri}")

    if referinta:
        print("\n" + BAR)
        print("  DELTE față de „tot istoricul" + '"' + " (referința = ce se face azi)")
        print("  acuratețe: + e mai bine · log-loss și Brier: − e mai bine")
        print(BAR)
        for nume, agg, _ in rezumat:
            if nume == "tot istoricul (azi)":
                continue
            print(f"  {nume:<26s} "
                  f"acc {agg['acuratete'] - referinta['acuratete']:+.4f}   "
                  f"ll {agg['log_loss'] - referinta['log_loss']:+.4f}   "
                  f"brier {agg['brier'] - referinta['brier']:+.4f}")

    print("\n" + BAR)
    print("  Ablație încheiată. ZERO scriere efectuată.")
    print("  Un câștig aici NU e o decizie — e o ipoteză care trece mai departe")
    print("  ca experiment Challenger, judecat pe trafic real (North Star #2).")
    print(BAR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
