"""
TEMPORAR -- P3.1 din ML_EVOLUTION_ROADMAP.md: rafinare Goal Difference
ELO (MOV), urmare a rundei 1 (P3), marcata explicit "Inconclusive / Needs
refinement" de Chief Architect -- toate cele 3 variante testate imbunatateau
Accuracy/Log Loss/Brier simultan, dar sub pragul strict de +0.3pp Accuracy;
fidelitatea arata un trade-off real intre eroarea medie vs. referinta si
Spearman rank correlation (V3_amplified castiga pe rang + Log Loss/Brier,
pierde pe eroare medie). Decizie explicita: nu se trece la P4 fara (1) o
investigatie a discrepantei de reproductibilitate (11.23% aici vs. 9.40%
in ELO_FIDELITY_AUDIT_2026-07-13.md, aceeasi metodologie, acelasi numar de
meciuri) si (2) o singura runda de rafinare in jurul lui V3, maximum
cateva variante -- NU o cautare noua.

Executat conform P3_0_DESIGN_REVIEW_ELO_MOV_2026-07-15.md (formula A
aleasa, aprobata de Chief Architect).

Replay A = ELOTracker exact ca in productie (sync/backfill_features.py,
IMPORTAT direct, nu reimplementat -- garanteaza identitate bit-cu-bit cu
ce ruleaza azi in backfill).

Replay B (3 variante de constante -- NU e Optuna, doar verificare de
directie, cerinta explicita) = acelasi ELOTracker (aceiasi INITIAL_ELO/
HOME_ADVANTAGE/K_FACTOR_BASE/K_FACTOR_NEW, importati din acelasi modul),
dar process_match() primeste golurile si aplica multiplicatorul MOV
(FiveThirtyEight-style):

    multiplier(gd, elo_diff) = ln(gd+1) * c / (d*elo_diff + c)   daca gd>=1
    multiplier = 1.0                                              daca gd=0

gd = |goluri_acasa - goluri_deplasare|; elo_diff = rating_castigator -
rating_invins (SEMNAT, folosind ratingurile efective PRE-meci, home
advantage inclus -- consistent cu ce foloseste deja _expected_score()).

NOTA de implementare (descoperita la scriere, nu in document): gd=0 (egal)
ar produce ln(1)=0 -- ar anula complet actualizarea la egaluri daca am
aplica formula bruta. Caz special explicit: la egal, multiplicator=1.0
(comportament neschimbat fata de Replay A) -- "marja de victorie" nu are
sens pentru un rezultat fara victorie.

V1_baseline (c=2.2, d=0.001, valorile din document) / V2_damped (c=4.4,
d=0.0005, corectie de surpriza injumatatita) / V3_amplified (c=1.1,
d=0.002, corectie dublata).

Fidelitate ELO (P3_0 sectiunea 3, extinsa cu Spearman la cererea explicita
a Chief Architect):
  - comparatie RELATIVA (nu absoluta) fata de ELO_RATINGS_FALLBACK
    (mappings.py, stil eloratings.net -- singura referinta existenta,
    deja auditata in ELO_FIDELITY_AUDIT_2026-07-13.md, cu eroare
    sistematica de cold-start ~9.4% deja demonstrata ca independenta de
    formula MOV).
  - Spearman rank correlation intre clasamentul replay-ului si clasamentul
    referintei, pe aceeasi intersectie de echipe -- raspunde daca noul
    ELO pastreaza mai bine ierarhia, nu doar daca se apropie in valoare.
  - stabilitate sezon-cu-sezon (an calendaristic, consistent cu precedentul
    din ELO_FIDELITY_AUDIT): volatilitate an-la-an + Spearman intre
    clasamente consecutive, prag minim 5 meciuri/echipa/an -- 100% interna,
    raportata ca context suplimentar (nu decide singura verdictul).
  - distributia diferentelor B-vs-A (rating final, per echipa).

Calitatea predictorului: DOAR home_elo/away_elo inlocuite (celelalte 11
coloane din FEATURE_COLUMNS raman exact cele stocate in productie --
offensive/defensive_rating depind si ele de ELO in pipeline-ul live, dar
recalcularea lor in cascada e in afara scopului acestui experiment,
izoland deliberat semnalul ELO). Comparatie principala: Replay A
(control, aceeasi metodologie) vs fiecare Replay B -- nu benchmark-ul
oficial direct (ar amesteca efectul MOV cu efectul deja cunoscut
Kaggle-vs-ELOTracker-replay, vezi ELO_PERFORMANCE_EXPERIMENT_2026-07-13.md).
Benchmark-ul oficial ADR-020 raportat doar ca context.

100% read-only fata de Supabase (doar SELECT). Zero scriere, zero
promovare, zero atingere a ELOTracker-ului de productie sau a
match_history/elo_history.
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

PRODUCTION_PARAMS = dict(
    n_estimators=150, max_depth=4, learning_rate=0.08,
    subsample=0.85, colsample_bytree=0.85,
    objective="multi:softprob", num_class=3,
    eval_metric="mlogloss", random_state=42,
)

OFFICIAL_BENCHMARK = {"accuracy": 0.4868, "log_loss": 1.0253, "brier_score": 0.6145}
ACCURACY_SUCCESS_DELTA = 0.003   # >=+0.3pp

MOV_VARIANTS = {
    # P3.1 -- runda de rafinare (cerinta explicita: "maximum cateva variante
    # bine alese, nu o cautare masiva"). V3 REPETAT ca ancora/verificare de
    # reproductibilitate (ruleaza din nou identic, pe acelasi cod, aceeasi
    # sursa de date -- verificam daca numerele raman stabile intre cele doua
    # rulari). V4/V5 bracheteaza V3: mai multa, respectiv mai putina
    # corectie de surpriza fata de V3, nu o cautare exhaustiva.
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


def build_feature_df_with_elo_override(base_df, pre_elo_by_id: dict):
    df = base_df.copy()
    df["home_elo"] = df["id"].map(lambda i: pre_elo_by_id.get(i, (np.nan, np.nan))[0]).astype(float)
    df["away_elo"] = df["id"].map(lambda i: pre_elo_by_id.get(i, (np.nan, np.nan))[1]).astype(float)
    missing = int(df["home_elo"].isna().sum())
    return df, missing


def walk_forward(df, n_folds: int = N_FOLDS):
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

    print(f"4 replay-uri complete (A + {len(MOV_VARIANTS)} variante B), {time.time()-t0:.1f}s.\n")

    # ── Fidelitate ────────────────────────────────────────────────────
    print("=" * 116)
    print("FIDELITATE ELO -- comparatie RELATIVA vs. ELO_RATINGS_FALLBACK (referinta deja auditata, "
          "NU date ClubElo reale) + Spearman rank correlation")
    print("=" * 116)

    ref_a = compare_to_reference(final_a, "Replay A")
    stab_a = season_stability(season_a, count_a)
    print(f"\n--- Replay A (control) ---")
    print(f"  vs. referinta: n_echipe={ref_a['n_teams']}, mean_abs_pct_diff={ref_a['mean_abs_pct_diff']}%, "
          f"median={ref_a['median_abs_pct_diff']}%, max={ref_a['max_abs_pct_diff']}%, "
          f"directie: {ref_a['n_positive']} pozitive / {ref_a['n_negative']} negative, "
          f"Spearman rho={ref_a['spearman_rho']}")
    print(f"  stabilitate sezon-cu-sezon: {stab_a['n_year_pairs']} perechi de ani, "
          f"yoy_std={stab_a['yoy_std']}, yoy_mean_abs={stab_a['yoy_mean_abs']}, "
          f"Spearman mediu intre ani consecutivi={stab_a['mean_spearman_consecutive_years']}")

    # [ADAUGAT -- P3.1] Diagnostic de reproductibilitate: rularea anterioara
    # (2026-07-15, prima runda P3) a raportat mean_abs_pct_diff=11.23% pentru
    # Replay A, fata de 9.40% raportat cu 2 zile inainte in
    # ELO_FIDELITY_AUDIT_2026-07-13.md, cu aceeasi metodologie si acelasi
    # numar total de meciuri (53.409). Tabelul complet per-echipa de mai jos
    # permite comparatia directa, rand cu rand, cu tabelul deja publicat acolo.
    print(f"\n  Tabel complet per-echipa (Replay A, pentru diagnostic reproductibilitate vs. "
          f"ELO_FIDELITY_AUDIT_2026-07-13.md):")
    print(f"  {'echipa':<22}{'replay':>10}{'referinta':>12}{'diff':>10}{'abs_pct_diff':>15}")
    for row in sorted(ref_a["rows"], key=lambda r: -r["abs_pct_diff"]):
        print(f"  {row['team']:<22}{row['replay']:>10}{row['reference']:>12}{row['diff']:>10}{row['abs_pct_diff']:>14}%")

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
    folds_a, summary_a = walk_forward(df_a)
    print(f"\n--- Replay A (control) --- (elo lipsa pentru {missing_a} randuri, ar trebui sa fie 0)")
    for f in folds_a:
        print(f"  fold {f['fold']}: train={f['train']} val={f['val']} "
              f"acc={f['accuracy']} log_loss={f['log_loss']} brier={f['brier_score']}")
    print(f"  MEDIE: {summary_a}")
    print(f"  context, benchmark oficial ADR-020: {OFFICIAL_BENCHMARK}")

    predictor_results = {}
    for name, data in replay_b.items():
        df_b, missing_b = build_feature_df_with_elo_override(base_df, data["pre"])
        folds_b, summary_b = walk_forward(df_b)
        predictor_results[name] = summary_b
        d_acc = summary_b["avg_accuracy"] - summary_a["avg_accuracy"]
        d_ll = summary_a["avg_log_loss"] - summary_b["avg_log_loss"]
        d_brier = summary_a["avg_brier_score"] - summary_b["avg_brier_score"]
        print(f"\n--- {name} --- (elo lipsa pentru {missing_b} randuri)")
        for f in folds_b:
            print(f"  fold {f['fold']}: acc={f['accuracy']} log_loss={f['log_loss']} brier={f['brier_score']}")
        print(f"  MEDIE: {summary_b}")
        print(f"  vs Replay A: Accuracy {d_acc:+.4f}, Log Loss {d_ll:+.4f} "
              f"({'mai bun' if d_ll>0 else 'mai slab' if d_ll<0 else 'egal'}), "
              f"Brier {d_brier:+.4f} ({'mai bun' if d_brier>0 else 'mai slab' if d_brier<0 else 'egal'})")

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
