"""
================================================================================
FOOTBALL ORACLE — Prediction Evaluation (Sprint 0 — Stabilizare, Etapa 3)
================================================================================
Module: prediction_evaluation.py

Măsoară dacă predicțiile emise sunt bune sau rele, pe date REALE —
Accuracy, Log-loss, Brier Score, Calibrare, defalcate per ligă. Citește
STRICT din Supabase (`match_history` — rânduri cu ATÂT predicție
(prob_*_pred) CÂT ȘI rezultat real (actual_result); identitatea canonică e
deja garantată de rândul unic din match_history, ADR-036), niciun apel
live către vreun provider.

Nu antrenează nimic, nu scrie nimic, nu modifică Selection Engine — raport
pur, citire + calcul. Brier score multi-clasă calculat identic cu
`ml_predictor.MLPredictorEngine._multiclass_brier()` (aceeași formulă,
Brier 1950): media pătratelor diferențelor între probabilitatea prezisă și
eticheta one-hot reală, peste toate clasele — o singură formulă de Brier
în tot proiectul, nu o a doua implementare divergentă.
================================================================================
"""
from __future__ import annotations

import math
from dataclasses import dataclass

_RESULT_TO_INDEX = {"H": 0, "D": 1, "A": 2}
_INDEX_TO_RESULT = {v: k for k, v in _RESULT_TO_INDEX.items()}


@dataclass(frozen=True)
class EvaluationMetrics:
    n: int
    accuracy: float | None
    log_loss: float | None
    brier_score: float | None


@dataclass(frozen=True)
class CalibrationBin:
    outcome: str          # "H" | "D" | "A"
    bin_index: int
    bin_low: float
    bin_high: float
    n: int
    mean_predicted: float | None
    observed_frequency: float | None


def compute_metrics(rows: list[dict]) -> EvaluationMetrics:
    """
    Funcție pură — fiecare element din `rows` trebuie să aibă
    `prob_home_pred`, `prob_draw_pred`, `prob_away_pred`, `actual_result`
    (H/D/A). Rânduri incomplete sunt excluse aici (Regula #8 — nicio stare
    necunoscută nu se aproximează, un rând incomplet nu poate contribui la
    o metrică).
    """
    n_correct = 0
    ll_terms: list[float] = []
    brier_terms: list[float] = []
    n = 0
    eps = 1e-15

    for r in rows:
        ph = r.get("prob_home_pred")
        pd_ = r.get("prob_draw_pred")
        pa = r.get("prob_away_pred")
        actual = r.get("actual_result")
        if ph is None or pd_ is None or pa is None or actual not in _RESULT_TO_INDEX:
            continue

        probs = [float(ph), float(pd_), float(pa)]
        idx = _RESULT_TO_INDEX[actual]
        n += 1

        predicted_idx = max(range(3), key=lambda i: probs[i])
        if predicted_idx == idx:
            n_correct += 1

        p_true = min(max(probs[idx], eps), 1.0 - eps)
        ll_terms.append(-math.log(p_true))

        one_hot = [1.0 if i == idx else 0.0 for i in range(3)]
        brier_terms.append(sum((p - o) ** 2 for p, o in zip(probs, one_hot)))

    if n == 0:
        return EvaluationMetrics(n=0, accuracy=None, log_loss=None, brier_score=None)

    return EvaluationMetrics(
        n=n,
        accuracy=round(n_correct / n, 4),
        log_loss=round(sum(ll_terms) / n, 4),
        brier_score=round(sum(brier_terms) / n, 4),
    )


def compute_calibration(rows: list[dict], n_bins: int = 10) -> list[CalibrationBin]:
    """
    Calibrare per clasă (H/D/A) — reliability diagram standard. Pentru
    fiecare clasă, grupează predicțiile în `n_bins` intervale egale [0,1]
    după probabilitatea prezisă pentru acea clasă, compară media prezisă
    (mean_predicted) cu frecvența reală observată (observed_frequency) în
    acel interval. Un model perfect calibrat are mean_predicted ≈
    observed_frequency în fiecare interval populat.
    """
    bins: list[CalibrationBin] = []
    for outcome, key in (("H", "prob_home_pred"), ("D", "prob_draw_pred"), ("A", "prob_away_pred")):
        buckets: list[list[tuple[float, bool]]] = [[] for _ in range(n_bins)]
        for r in rows:
            p = r.get(key)
            actual = r.get("actual_result")
            if p is None or actual not in _RESULT_TO_INDEX:
                continue
            p = float(p)
            bin_idx = min(max(int(p * n_bins), 0), n_bins - 1)
            buckets[bin_idx].append((p, actual == outcome))

        for i, bucket in enumerate(buckets):
            low, high = i / n_bins, (i + 1) / n_bins
            if not bucket:
                bins.append(CalibrationBin(outcome, i, low, high, 0, None, None))
                continue
            mean_pred = sum(p for p, _ in bucket) / len(bucket)
            observed = sum(1 for _, hit in bucket if hit) / len(bucket)
            bins.append(CalibrationBin(outcome, i, low, high, len(bucket),
                                        round(mean_pred, 4), round(observed, 4)))
    return bins


def get_predictions_with_results(days_back: int | None = None) -> list[dict]:
    """Citire STRICT din Supabase (database.queries.get_predictions_with_results,
    read-only) — fără fereastră (days_back=None) acoperă tot istoricul
    disponibil."""
    from database.queries import get_predictions_with_results as _q
    return _q(days_back=days_back)


def build_evaluation_report(days_back: int | None = None) -> dict:
    """
    Raportul complet — overall + per ligă + calibrare. Livrabilul Sprint 0,
    Etapa 3 ("Football Oracle să poată demonstra, cu date reale, dacă
    predicțiile sunt bune sau rele").
    """
    rows = get_predictions_with_results(days_back=days_back)

    overall = compute_metrics(rows)
    calibration = compute_calibration(rows)

    by_league: dict[str, list[dict]] = {}
    for r in rows:
        by_league.setdefault(r.get("league") or "necunoscut", []).append(r)

    per_league = {
        league: compute_metrics(league_rows)
        for league, league_rows in sorted(by_league.items())
    }

    return {
        "n_total_rows": len(rows),
        "overall": overall,
        "per_league": per_league,
        "calibration": calibration,
    }


def _print_report(report: dict) -> None:
    overall = report["overall"]
    print("=" * 60)
    print("  FOOTBALL ORACLE — Raport de evaluare predicții")
    print("=" * 60)
    print(f"  Rânduri cu predicție + rezultat real: {report['n_total_rows']}")
    print()
    if overall.n == 0:
        print("  Încă nicio predicție cu rezultat real asociat.")
        return
    print(f"  OVERALL — n={overall.n}")
    print(f"    Accuracy    : {overall.accuracy * 100:.1f}%")
    print(f"    Log-loss    : {overall.log_loss:.4f}")
    print(f"    Brier Score : {overall.brier_score:.4f}")
    print()
    print("  PER LIGĂ:")
    for league, m in report["per_league"].items():
        if m.n == 0:
            continue
        print(f"    {league:<25} n={m.n:<4} acc={m.accuracy * 100:5.1f}%  "
              f"log_loss={m.log_loss:.4f}  brier={m.brier_score:.4f}")
    print("=" * 60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="prediction_evaluation",
        description="Raport Accuracy/Log-loss/Brier/Calibrare pe predicții reale (Sprint 0, Stabilizare).",
    )
    parser.add_argument("--days-back", type=int, default=None,
                         help="Limitează la ultimele N zile (implicit: tot istoricul).")
    args = parser.parse_args()

    _print_report(build_evaluation_report(days_back=args.days_back))
