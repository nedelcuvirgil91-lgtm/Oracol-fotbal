"""
TEMPORAR -- P3 REVALIDATION (2026-07-15), dupa P3.5 Faza 3 (consolidare
identitate echipe, executata si verificata pe productie in aceeasi zi).

Directiva Chief Architect: "Consolidarea identitatii echipelor schimba
suficient fidelitatea ELO incat Margin of Victory (MOV) sa devina acum un
experiment Accepted?" -- raspuns pe date masurate, nu presupus.

REGULA EXPLICITA: metodologia P3/P3.1 NU se modifica fara eroare
demonstrabila. Acest script e o extensie ADITIVA a scripts/_p3_elo_mov_
replay_temp.py original (commit 5fea9b9, sters in 84dd96f dupa inchiderea
P3 ca Inconclusive) -- recuperat integral din git history, nemodificat in
partea centrala (ELOTracker/ELOTrackerMOV, formula MOV, walk_forward,
fidelitate, stabilitate sezon-cu-sezon). Singurele adaugiri:

  1. MOV_VARIANTS extins de la 3 (V1/V2/V3, runda 1) la toate cele 5
     constante folosite in P3 + P3.1 (V4/V5 recuperate din log-urile
     GitHub Actions ale rularii P3.1 originale, scripts/_p3_elo_mov_
     replay_temp.py fusese editat local, necomis, intre runde -- constantele
     exacte sunt confirmate acolo, nu presupuse). Rulate intr-o singura
     trecere (nu 2 runde separate ca originalul) -- acelasi Replay A
     control pentru toate 5, comparabilitate mai buna, nu mai putina.
  2. Tabelul complet per-echipa (16 echipe) pentru fidelitate -- datele
     erau deja calculate (compare_to_reference() returna `rows`), doar
     neprintate in scriptul original.
  3. Expected Calibration Error (ECE, 10 bin-uri, pe predictiile agregate
     din toate cele 5 folduri) -- functie IDENTICA, copiata verbatim din
     scripts/_calibration_study_p2_temp.py (commit c84c84b, P2), pentru
     consistenta exacta de definitie cu experimentul de calibrare deja
     inchis.
  4. Feature importance (XGBoost .feature_importances_, mediat pe cele 5
     folduri walk-forward) per varianta -- extras din modelele deja
     antrenate de walk_forward(), fara niciun antrenament suplimentar.

Niciuna din aceste 4 adaugiri nu schimba: formula MOV, constantele c/d,
INITIAL_ELO/HOME_ADVANTAGE/K_FACTOR_BASE/K_FACTOR_NEW, imparteala
walk-forward (5 folduri, expanding window, random_state=42), hiperparametrii
XGBoost de productie, sau criteriul de succes/abandon din P3_0_DESIGN_
REVIEW_ELO_MOV_2026-07-15.md. Scopul e comparabilitate cu P3/P3.1, nu
reinventare.

Rulat DUPA P3.5 Faza 3 (docs/03_ENGINE/P3_5_FAZA3_POST_MIGRATION_REPORT_
2026-07-15.md) -- match_history are acum 137 echipe consolidate, 19.797
randuri cu toate cele 18 FEATURE_COLUMNS recalculate pe istoricul unificat.
fetch_all_matches() si MLPredictorEngine._fetch_training_dataframe() citesc
automat starea curenta (nu exista cache/snapshot intermediar) -- Replay A
din aceasta rulare foloseste deci ELOTracker-ul de productie REPLAYAT pe
datele consolidate, nu pe datele fragmentate din P3/P3.1 original.

100% read-only fata de Supabase (doar SELECT, exact ca originalul). Zero
scriere, zero promovare, zero atingere a ELOTracker-ului de productie sau
a match_history/elo_history.
"""
import math
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import accuracy_score, log_loss as sk_log_loss
from xgboost import XGBClassifier

from mappings import ELO_RATINGS_FALLBACK
from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine, RESULT_TO_LABEL
from sync.backfill_features import (
    ELOTracker, HOME_ADVANTAGE, fetch_all_matches, _expected_score, _k_factor,
)

MIN_MATCHES_PER_TEAM_YEAR = 5
N_FOLDS = 5
N_ECE_BINS = 10

PRODUCTION_PARAMS = dict(
    n_estimators=150, max_depth=4, learning_rate=0.08,
    subsample=0.85, colsample_bytree=0.85,
    objective="multi:softprob", num_class=3,
    eval_metric="mlogloss", random_state=42,
)

OFFICIAL_BENCHMARK = {"accuracy": 0.4868, "log_loss": 1.0253, "brier_score": 0.6145}
ACCURACY_SUCCESS_DELTA = 0.003   # >=+0.3pp

# [NESCHIMBAT fata de original] V1/V2/V3 -- runda 1, ML_EVOLUTION_ROADMAP.md.
# [RECUPERAT, nu reinventat] V4/V5 -- runda 2 (P3.1), constante confirmate
# in log-urile GitHub Actions ale rularii originale (job elo-mov-replay,
# 2026-07-15 05:52 UTC) -- editate local intre runde, niciodata comise separat.
MOV_VARIANTS = {
    "V1_baseline":       (2.2, 0.001),
    "V2_damped":         (4.4, 0.0005),
    "V3_amplified":      (1.1, 0.002),
    "V4_more_amplified": (0.8, 0.0025),
    "V5_mild_amplified": (1.5, 0.0015),
}


class ELOTrackerMOV:
    """Identic structural cu ELOTracker (productie), diferit doar prin
    multiplicatorul MOV aplicat termenului de actualizare."""

    def __init__(self, c: float, d: float):
        self.ratings: dict[str, float] = {}
        self.match_counts: dict[str, int] = {}
        self.c = c
        self.d = d

    def get_elo(self, team: str) -> float:
        return self.ratings.get(team, 1500.0)

    def get_count(self, team: str) -> int:
        return self.match_counts.get(team, 0)

    def get_elos_before_match(self, home: str, away: str) -> tuple[int, int]:
        return round(self.get_elo(home)), round(self.get_elo(away))

    def _mov_multiplier(self, gd: int, elo_diff_signed: float) -> float:
        if gd <= 0:
            return 1.0
        return math.log(gd + 1) * (self.c / (self.d * elo_diff_signed + self.c))

    def process_match(self, home: str, away: str, home_goals: int, away_goals: int, result: str) -> None:
        r_home = self.get_elo(home) + HOME_ADVANTAGE
        r_away = self.get_elo(away)
        exp_home = _expected_score(r_home, r_away)
        exp_away = 1.0 - exp_home

        if result == "H":
            score_home, score_away = 1.0, 0.0
            elo_diff = r_home - r_away
        elif result == "A":
            score_home, score_away = 0.0, 1.0
            elo_diff = r_away - r_home
        else:
            score_home, score_away = 0.5, 0.5
            elo_diff = 0.0

        gd = abs(int(home_goals) - int(away_goals))
        multiplier = self._mov_multiplier(gd, elo_diff)

        k_home = _k_factor(self.get_count(home))
        k_away = _k_factor(self.get_count(away))

        self.ratings[home] = self.get_elo(home) + k_home * multiplier * (score_home - exp_home)
        self.ratings[away] = self.get_elo(away) + k_away * multiplier * (score_away - exp_away)
        self.match_counts[home] = self.get_count(home) + 1
        self.match_counts[away] = self.get_count(away) + 1


def _kickoff_year(raw) -> int | None:
    if not raw:
        return None
    try:
        return int(str(raw)[:4])
    except Exception:
        return None


def run_replay(matches: list[dict], tracker, use_goals: bool):
    pre_elo_by_id: dict[int, tuple[int, int]] = {}
    season_end: dict[int, dict[str, float]] = {}
    season_count: dict[int, dict[str, int]] = {}

    for m in matches:
        result = m.get("actual_result")
        if result not in ("H", "D", "A"):
            continue
        home, away = m["home_team"], m["away_team"]
        h_elo, a_elo = tracker.get_elos_before_match(home, away)
        pre_elo_by_id[m["id"]] = (h_elo, a_elo)

        if use_goals:
            hg, ag = m.get("actual_home_goals"), m.get("actual_away_goals")
            if hg is None or ag is None:
                hg, ag = 0, 0  # gd=0 -> multiplicator neutru 1.0, nu eroare
            tracker.process_match(home, away, hg, ag, result)
        else:
            tracker.process_match(home, away, result)

        year = _kickoff_year(m.get("kickoff_date"))
        if year is not None:
            season_end.setdefault(year, {})
            season_count.setdefault(year, {})
            for team in (home, away):
                season_end[year][team] = tracker.get_elo(team)
                season_count[year][team] = season_count[year].get(team, 0) + 1

    return pre_elo_by_id, dict(tracker.ratings), season_end, season_count


def compare_to_reference(final_ratings: dict, label: str) -> dict:
    common = sorted(set(final_ratings) & set(ELO_RATINGS_FALLBACK))
    rows = []
    for team in common:
        r, ref = final_ratings[team], ELO_RATINGS_FALLBACK[team]
        diff = r - ref
        rows.append({"team": team, "replay": round(r, 1), "reference": ref,
                      "diff": round(diff, 1), "abs_pct_diff": round(abs(diff) / ref * 100, 2)})
    abs_pcts = [r["abs_pct_diff"] for r in rows]
    diffs = [r["diff"] for r in rows]
    rho = None
    if len(common) >= 3:
        rho_val, _ = spearmanr([final_ratings[t] for t in common], [ELO_RATINGS_FALLBACK[t] for t in common])
        rho = round(float(rho_val), 4)
    return {
        "label": label, "n_teams": len(common), "rows": rows,
        "mean_abs_pct_diff": round(float(np.mean(abs_pcts)), 2) if abs_pcts else None,
        "median_abs_pct_diff": round(float(np.median(abs_pcts)), 2) if abs_pcts else None,
        "max_abs_pct_diff": round(float(np.max(abs_pcts)), 2) if abs_pcts else None,
        "n_positive": sum(1 for d in diffs if d > 0), "n_negative": sum(1 for d in diffs if d < 0),
        "spearman_rho": rho,
    }


def print_reference_table(ref: dict) -> None:
    """[ADAUGAT] Tabelul complet per-echipa -- datele existau deja in
    compare_to_reference()['rows'], doar neprintate in scriptul original."""
    print(f"  Tabel complet ({ref['n_teams']} echipe):")
    print(f"  {'Echipa':<22}{'Replay':>10}{'Referinta':>12}{'Diff':>10}{'Diff %':>10}")
    for row in sorted(ref["rows"], key=lambda r: -r["abs_pct_diff"]):
        print(f"  {row['team']:<22}{row['replay']:>10}{row['reference']:>12}{row['diff']:>10}{row['abs_pct_diff']:>9}%")


def season_stability(season_end: dict, season_count: dict, min_matches: int = MIN_MATCHES_PER_TEAM_YEAR) -> dict:
    years = sorted(season_end.keys())
    yoy_changes, rho_list = [], []
    for y1, y2 in zip(years, years[1:]):
        teams1 = {t for t, c in season_count.get(y1, {}).items() if c >= min_matches}
        teams2 = {t for t, c in season_count.get(y2, {}).items() if c >= min_matches}
        common = sorted(teams1 & teams2)
        if len(common) < 3:
            continue
        r1 = [season_end[y1][t] for t in common]
        r2 = [season_end[y2][t] for t in common]
        yoy_changes.extend(b - a for a, b in zip(r1, r2))
        rho_val, _ = spearmanr(r1, r2)
        rho_list.append(float(rho_val))
    return {
        "n_year_pairs": len(rho_list),
        "yoy_std": round(float(np.std(yoy_changes)), 2) if yoy_changes else None,
        "yoy_mean_abs": round(float(np.mean(np.abs(yoy_changes))), 2) if yoy_changes else None,
        "mean_spearman_consecutive_years": round(float(np.mean(rho_list)), 4) if rho_list else None,
    }


def diff_distribution(final_a: dict, final_b: dict) -> dict:
    common = sorted(set(final_a) & set(final_b))
    diffs = [final_b[t] - final_a[t] for t in common]
    return {
        "n_teams": len(common),
        "mean_diff": round(float(np.mean(diffs)), 2) if diffs else None,
        "std_diff": round(float(np.std(diffs)), 2) if diffs else None,
        "n_positive": sum(1 for d in diffs if d > 0), "n_negative": sum(1 for d in diffs if d < 0),
        "n_zero": sum(1 for d in diffs if d == 0),
    }


def multiclass_brier(y_true: np.ndarray, probs: np.ndarray, n_classes: int = 3) -> float:
    one_hot = np.eye(n_classes)[y_true]
    return float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))


def expected_calibration_error(y_true: np.ndarray, probs: np.ndarray, n_bins: int = N_ECE_BINS):
    """[ADAUGAT, copiat verbatim din scripts/_calibration_study_p2_temp.py,
    commit c84c84b -- ECE standard (Guo et al. 2017), aceeasi definitie ca P2,
    pentru comparabilitate directa cu 'baseline ECE=0.0161' deja raportat."""
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


def build_feature_df_with_elo_override(base_df, pre_elo_by_id: dict):
    df = base_df.copy()
    df["home_elo"] = df["id"].map(lambda i: pre_elo_by_id.get(i, (np.nan, np.nan))[0]).astype(float)
    df["away_elo"] = df["id"].map(lambda i: pre_elo_by_id.get(i, (np.nan, np.nan))[1]).astype(float)
    missing = int(df["home_elo"].isna().sum())
    return df, missing


def walk_forward(df, n_folds: int = N_FOLDS):
    """[EXTINS, neschimbat in partea centrala] Aceeasi impartire expanding-
    window, aceiasi hiperparametri. Adaugiri: colecteaza (y_val, probs)
    pooled din toate fold-urile (pentru ECE) si feature_importances_ per
    fold (mediate la final) -- fara niciun antrenament suplimentar, doar
    citire din modelele deja antrenate."""
    X = df[FEATURE_COLUMNS].astype(float)
    y = df["actual_result"].map(RESULT_TO_LABEL).astype(int)
    n = len(X)
    boundaries = np.linspace(0, n, n_folds + 2, dtype=int)
    folds = []
    pooled_y, pooled_probs = [], []
    importances = []
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
        pooled_y.append(y_val.to_numpy())
        pooled_probs.append(probs)
        importances.append(model.feature_importances_)
    summary = {
        "avg_accuracy": round(float(np.mean([f["accuracy"] for f in folds])), 4),
        "avg_log_loss": round(float(np.mean([f["log_loss"] for f in folds])), 4),
        "avg_brier_score": round(float(np.mean([f["brier_score"] for f in folds])), 4),
    }
    pooled_y_arr = np.concatenate(pooled_y) if pooled_y else np.array([])
    pooled_probs_arr = np.concatenate(pooled_probs) if pooled_probs else np.empty((0, 3))
    avg_importance = (np.mean(np.vstack(importances), axis=0) if importances
                       else np.zeros(len(FEATURE_COLUMNS)))
    return folds, summary, pooled_y_arr, pooled_probs_arr, avg_importance


def print_feature_importance(avg_importance: np.ndarray, top_n: int = 10) -> None:
    pairs = sorted(zip(FEATURE_COLUMNS, avg_importance), key=lambda p: -p[1])
    print(f"  Feature importance (XGBoost, mediat pe {N_FOLDS} folduri, top {top_n}):")
    for name, val in pairs[:top_n]:
        print(f"    {name:<28}{val:.4f}")


def main() -> int:
    t0 = time.time()
    print("Se incarca meciurile complete pentru replay (fetch_all_matches, ordine kickoff_date, id) ...")
    matches = fetch_all_matches()
    if not matches:
        print("Fara date disponibile din Supabase.")
        return 1
    print(f"{len(matches)} meciuri incarcate.\n")

    # ── Replay A (control, productie neschimbata) ───────────────────────
    tracker_a = ELOTracker()
    pre_a, final_a, season_a, count_a = run_replay(matches, tracker_a, use_goals=False)

    replay_b = {}
    for name, (c, d) in MOV_VARIANTS.items():
        tracker_b = ELOTrackerMOV(c=c, d=d)
        pre_b, final_b, season_b, count_b = run_replay(matches, tracker_b, use_goals=True)
        replay_b[name] = {"pre": pre_b, "final": final_b, "season": season_b, "count": count_b, "c": c, "d": d}

    print(f"{1 + len(MOV_VARIANTS)} replay-uri complete (A + {len(MOV_VARIANTS)} variante B), {time.time()-t0:.1f}s.\n")

    # ── Fidelitate ────────────────────────────────────────────────────
    print("=" * 116)
    print("FIDELITATE ELO -- comparatie RELATIVA vs. ELO_RATINGS_FALLBACK (referinta deja auditata, "
          "NU date ClubElo reale) + Spearman rank correlation")
    print("=" * 116)

    ref_a = compare_to_reference(final_a, "Replay A")
    stab_a = season_stability(season_a, count_a)
    print(f"\n--- Replay A (control, pe date consolidate P3.5) ---")
    print(f"  vs. referinta: n_echipe={ref_a['n_teams']}, mean_abs_pct_diff={ref_a['mean_abs_pct_diff']}%, "
          f"median={ref_a['median_abs_pct_diff']}%, max={ref_a['max_abs_pct_diff']}%, "
          f"directie: {ref_a['n_positive']} pozitive / {ref_a['n_negative']} negative, "
          f"Spearman rho={ref_a['spearman_rho']}")
    print(f"  stabilitate sezon-cu-sezon: {stab_a['n_year_pairs']} perechi de ani, "
          f"yoy_std={stab_a['yoy_std']}, yoy_mean_abs={stab_a['yoy_mean_abs']}, "
          f"Spearman mediu intre ani consecutivi={stab_a['mean_spearman_consecutive_years']}")
    print_reference_table(ref_a)

    fidelity_results = {}
    for name, data in replay_b.items():
        ref_b = compare_to_reference(data["final"], name)
        stab_b = season_stability(data["season"], data["count"])
        dist = diff_distribution(final_a, data["final"])
        fidelity_results[name] = {"ref": ref_b, "stab": stab_b, "dist": dist}
        print(f"\n--- {name} (c={data['c']}, d={data['d']}) ---")
        print(f"  vs. referinta: mean_abs_pct_diff={ref_b['mean_abs_pct_diff']}% "
              f"(A={ref_a['mean_abs_pct_diff']}%), median={ref_b['median_abs_pct_diff']}%, "
              f"Spearman rho={ref_b['spearman_rho']} (A={ref_a['spearman_rho']})")
        print(f"  stabilitate sezon-cu-sezon: yoy_std={stab_b['yoy_std']} (A={stab_a['yoy_std']}), "
              f"Spearman mediu intre ani={stab_b['mean_spearman_consecutive_years']} "
              f"(A={stab_a['mean_spearman_consecutive_years']})")
        print(f"  distributie B-vs-A (rating final, {dist['n_teams']} echipe comune): "
              f"medie={dist['mean_diff']}, std={dist['std_diff']}, "
              f"{dist['n_positive']} crescute / {dist['n_negative']} scazute / {dist['n_zero']} neschimbate")
        print_reference_table(ref_b)

    # ── Predictor ─────────────────────────────────────────────────────
    print()
    print("=" * 116)
    print("CALITATEA PREDICTORULUI -- walk-forward, hiperparametri de productie neschimbati, "
          "DOAR home_elo/away_elo inlocuite")
    print("=" * 116)

    engine = MLPredictorEngine()
    base_df = engine._fetch_training_dataframe()
    if base_df is None or base_df.empty:
        print("Fara date de antrenare disponibile.")
        return 1
    if "kickoff_date" in base_df.columns:
        base_df = base_df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)

    df_a, missing_a = build_feature_df_with_elo_override(base_df, pre_a)
    folds_a, summary_a, pooled_y_a, pooled_probs_a, importance_a = walk_forward(df_a)
    ece_a, bins_a = expected_calibration_error(pooled_y_a, pooled_probs_a)
    print(f"\n--- Replay A (control) --- (elo lipsa pentru {missing_a} randuri, ar trebui sa fie 0)")
    for f in folds_a:
        print(f"  fold {f['fold']}: train={f['train']} val={f['val']} "
              f"acc={f['accuracy']} log_loss={f['log_loss']} brier={f['brier_score']}")
    print(f"  MEDIE: {summary_a}")
    print(f"  context, benchmark oficial ADR-020: {OFFICIAL_BENCHMARK}")
    print(f"  ECE (10 bin-uri, {len(pooled_y_a)} predictii pooled): {round(ece_a, 4)}")
    print_feature_importance(importance_a)

    predictor_results = {}
    ece_results = {"Replay A": ece_a}
    for name, data in replay_b.items():
        df_b, missing_b = build_feature_df_with_elo_override(base_df, data["pre"])
        folds_b, summary_b, pooled_y_b, pooled_probs_b, importance_b = walk_forward(df_b)
        ece_b, bins_b = expected_calibration_error(pooled_y_b, pooled_probs_b)
        predictor_results[name] = summary_b
        ece_results[name] = ece_b
        d_acc = summary_b["avg_accuracy"] - summary_a["avg_accuracy"]
        d_ll = summary_a["avg_log_loss"] - summary_b["avg_log_loss"]
        d_brier = summary_a["avg_brier_score"] - summary_b["avg_brier_score"]
        d_ece = ece_a - ece_b
        print(f"\n--- {name} --- (elo lipsa pentru {missing_b} randuri)")
        for f in folds_b:
            print(f"  fold {f['fold']}: acc={f['accuracy']} log_loss={f['log_loss']} brier={f['brier_score']}")
        print(f"  MEDIE: {summary_b}")
        print(f"  vs Replay A: Accuracy {d_acc:+.4f}, Log Loss {d_ll:+.4f} "
              f"({'mai bun' if d_ll>0 else 'mai slab' if d_ll<0 else 'egal'}), "
              f"Brier {d_brier:+.4f} ({'mai bun' if d_brier>0 else 'mai slab' if d_brier<0 else 'egal'})")
        print(f"  ECE (10 bin-uri, {len(pooled_y_b)} predictii pooled): {round(ece_b, 4)} "
              f"(A={round(ece_a, 4)}, delta={d_ece:+.4f} {'mai bun' if d_ece>0 else 'mai slab' if d_ece<0 else 'egal'})")
        print_feature_importance(importance_b)

    # ── Verdict per variantă (suport pentru decizie, nu automat definitiv) ──
    print()
    print("=" * 116)
    print("SEMNALE PENTRU DECIZIE (criteriul din P3_0 + extensia Chief Architect: fidelitate crescuta SAU "
          "predictor clar mai bun, fara regres major pe celalalt)")
    print("=" * 116)
    for name, data in replay_b.items():
        fid = fidelity_results[name]
        pred = predictor_results[name]
        d_acc = pred["avg_accuracy"] - summary_a["avg_accuracy"]
        d_ll = summary_a["avg_log_loss"] - pred["avg_log_loss"]
        d_brier = summary_a["avg_brier_score"] - pred["avg_brier_score"]
        fidelity_error_improved = (fid["ref"]["mean_abs_pct_diff"] is not None and
                                    fid["ref"]["mean_abs_pct_diff"] < ref_a["mean_abs_pct_diff"])
        fidelity_rank_improved = (fid["ref"]["spearman_rho"] is not None and ref_a["spearman_rho"] is not None and
                                   fid["ref"]["spearman_rho"] > ref_a["spearman_rho"])
        fidelity_improved = fidelity_error_improved or fidelity_rank_improved
        predictor_clear_win = d_acc >= ACCURACY_SUCCESS_DELTA and not (d_ll < 0 and d_brier < 0)
        print(f"\n{name}: fidelitate_eroare_mai_buna={fidelity_error_improved}, "
              f"fidelitate_rang_mai_buna={fidelity_rank_improved}, "
              f"predictor_castig_clar(Acc>=+0.3pp fara regres dublu)={predictor_clear_win}")
        print(f"  -> {'SEMNAL POZITIV (candidat pentru promovare)' if (fidelity_improved or predictor_clear_win) else 'SEMNAL NEGATIV (nu indeplineste niciun brat al criteriului)'}")

    print(f"\nTimp total: {time.time() - t0:.1f}s")
    print("Nicio scriere efectuata -- doar citire (fetch_all_matches, get_training_data) + calcul local, in memorie.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
