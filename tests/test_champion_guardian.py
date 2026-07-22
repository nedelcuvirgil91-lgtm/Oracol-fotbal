"""
Teste pentru learning_core.champion_guardian (Stage R2.5, ADR-037) — fără
rețea. Acoperă cerințele de audit:
  1. toate cele 5 stări (insufficient_data/healthy/watch/degrading/critical);
  2. prioritatea clasificatorului (Critical peste orice alt semnal);
  3. cazul F1 (re-rulare fără meciuri noi) — regresie viitoare;
  4. persistență vs non-persistență (n==0 nu persistă, n>=1 persistă o dată);
  5. erori de infrastructură tratate best-effort (None, niciodată excepție).

Dimensiunile statistice sunt exercitate cu rânduri REALE (Brier prin
shadow_testing._brier) unde e posibil; monkeypatch minim doar acolo unde e
mai clar (ex. instability izolată).
"""
import numpy as np
import pytest

import ml_predictor
import learning_core.champion_guardian as g

_ALGO_V = ml_predictor._ALGORITHM_VERSION


class _FakeModel:
    def __init__(self, fail: bool = False):
        self.fail = fail

    def predict_proba(self, X):
        if self.fail:
            raise RuntimeError("inferenta a esuat")
        return np.zeros((len(X), 3))


def _champion(trid="run-1", version=None):
    return {"training_run_id": trid, "algorithm_version": version or _ALGO_V,
            "promoted_at": "2026-01-01T00:00:00+00:00"}


def _row(kickoff, ph=0.5, pd=0.3, pa=0.2, outcome="H", fid=None):
    return {"fixture_id": fid or f"fx-{kickoff}", "kickoff_date": kickoff,
            "prob_home_pred": ph, "prob_draw_pred": pd, "prob_away_pred": pa,
            "actual_result": outcome}


def _uniform_rows(n, outcome="H"):
    """n rânduri identice, predicție corectă (H, ph=0.5) → Brier constant,
    fără trend, confidence constant (stabil)."""
    return [_row(f"2026-02-{(i % 28) + 1:02d}", outcome=outcome, fid=f"fx-{i}") for i in range(n)]


def _trend_degraded_rows(n=30):
    """Prima jumătate corectă (H), a doua greșită (A) → Brier recent >> anterior
    → _trend_degradation = True (semnal real, fără monkeypatch)."""
    half = n // 2
    rows = []
    for i in range(n):
        outcome = "H" if i < half else "A"
        rows.append(_row(f"2026-02-{(i % 28) + 1:02d}", outcome=outcome, fid=f"fx-{i}"))
    return rows


@pytest.fixture
def wired(monkeypatch):
    """Cablaj de bază: campion activ, artefact bun, versiune compatibilă, fără
    baseline, fără istoric, record capturat. Testele suprascriu ce au nevoie."""
    state = {"record_calls": []}
    monkeypatch.setattr("supabase_client.get_active_champion", lambda f, l: _champion())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes", lambda f, l, s=None: [])
    monkeypatch.setattr("supabase_client.get_latest_challenger_evaluation", lambda tid: None)
    monkeypatch.setattr("supabase_client.get_recent_champion_health_evaluations", lambda tid, limit=5: [])

    def _rec(**kw):
        state["record_calls"].append(kw)
        return True

    monkeypatch.setattr("supabase_client.record_champion_health_evaluation", _rec)
    return state


# ── 1+4. Cele 5 stări + persistență ─────────────────────────────────────────

def test_no_active_champion_returns_none(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_active_champion", lambda f, l: None)
    assert g.evaluate_champion_health("xgboost_v1", "all") is None


def test_state_critical_structural_artifact_missing(wired, monkeypatch):
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: None)
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _uniform_rows(40))
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.health_state == "critical"
    assert r.structural_flag is True
    assert "artifact_missing" in r.reason
    assert r.recommends_rollback is True
    # n>=1 → persistat o dată
    assert len(wired["record_calls"]) == 1


def test_state_critical_structural_model_error(wired, monkeypatch):
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact",
                        lambda tid: _FakeModel(fail=True))
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _uniform_rows(40))
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.health_state == "critical"
    assert "model_error" in r.reason


def test_state_insufficient_data_below_min(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _uniform_rows(5))  # < MIN=30
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.health_state == "insufficient_data"
    assert r.n_matches_evaluated == 5
    # 0 < n < MIN → persistă
    assert len(wired["record_calls"]) == 1


def test_state_healthy(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _uniform_rows(40))  # constant, fără trend/instab
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.health_state == "healthy"
    assert r.recommends_rollback is False
    assert len(wired["record_calls"]) == 1


def test_state_watch_single_trend_signal(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _trend_degraded_rows(30))
    # recent gol → o singură fereastră degradată → Watch
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.trend_flag is True
    assert r.health_state == "watch"
    assert r.recommends_rollback is False


def test_state_watch_instability_only(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _uniform_rows(40))
    monkeypatch.setattr("learning_core.champion_guardian._stability",
                        lambda rows: (0.9, True))  # instabil, dar fără degradare
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.stability_flag is True
    assert r.health_state == "watch"


def test_state_degrading_two_consecutive(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _trend_degraded_rows(30))  # current n=30, degradat
    # fereastră anterioară DISTINCTĂ (n=20 < 30) degradată → 2 consecutive
    monkeypatch.setattr("supabase_client.get_recent_champion_health_evaluations",
                        lambda tid, limit=5: [{"n_matches_evaluated": 20, "trend_flag": True,
                                               "baseline_deviation_flag": None}])
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.health_state == "degrading"
    assert r.recommends_rollback is True
    assert "regression" in r.reason


def test_n_zero_returns_without_persisting(wired):
    # served_outcomes = [] (default în fixture) → n==0
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.n_matches_evaluated == 0
    assert r.health_state == "insufficient_data"
    assert r.persisted is False
    assert wired["record_calls"] == []  # NU persistă


# ── 2. Prioritatea clasificatorului (unit) ──────────────────────────────────

def test_classifier_priority_order():
    c = g._classify_champion_health
    # Critical (structural) peste TOT (chiar n mic + degradat + instabil)
    assert c(structural_failed=True, n_matches=5, consecutive_degraded=9,
             this_degraded=True, instability=True) == "critical"
    # InsufficientData peste degrading/watch
    assert c(structural_failed=False, n_matches=5, consecutive_degraded=9,
             this_degraded=True, instability=True) == "insufficient_data"
    # Degrading peste watch
    assert c(structural_failed=False, n_matches=50, consecutive_degraded=2,
             this_degraded=True, instability=True) == "degrading"
    # Watch (un semnal) peste healthy
    assert c(structural_failed=False, n_matches=50, consecutive_degraded=1,
             this_degraded=True, instability=False) == "watch"
    # Watch (instability singură)
    assert c(structural_failed=False, n_matches=50, consecutive_degraded=0,
             this_degraded=False, instability=True) == "watch"
    # Healthy
    assert c(structural_failed=False, n_matches=50, consecutive_degraded=0,
             this_degraded=False, instability=False) == "healthy"


# ── 3. Regresia F1 (re-rulare fără meciuri noi) ─────────────────────────────

def test_f1_rerun_does_not_inflate_to_degrading():
    """Fereastra curentă (n==current) în `recent` NU se numără → o singură
    fereastră degradată rămâne 1 (Watch), nu 2 (Degrading)."""
    deg = {"baseline_deviation_flag": True, "trend_flag": None}
    # re-rulare: recent conține fereastra curentă (n=50 == current)
    assert g._count_consecutive_degraded([{"n_matches_evaluated": 50, **deg}], True, 50) == 1
    # caz legitim: fereastră anterioară distinctă (n=40 < 50)
    assert g._count_consecutive_degraded([{"n_matches_evaluated": 40, **deg}], True, 50) == 2
    # mix: curent (skip) + prior distinct → 2, nu 3
    assert g._count_consecutive_degraded(
        [{"n_matches_evaluated": 50, **deg}, {"n_matches_evaluated": 40, **deg}], True, 50) == 2
    # prior nedegradat întrerupe seria → 1
    assert g._count_consecutive_degraded(
        [{"n_matches_evaluated": 40, "baseline_deviation_flag": False, "trend_flag": False}], True, 50) == 1
    # nedegradat curent → 0
    assert g._count_consecutive_degraded([{"n_matches_evaluated": 40, **deg}], False, 50) == 0


def test_f1_rerun_end_to_end_stays_watch(wired, monkeypatch):
    """End-to-end: aceeași fereastră re-evaluată (recent conține n==current)
    rămâne Watch, NU escaladează la Degrading."""
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _trend_degraded_rows(30))  # current n=30, degradat
    # recent = fereastra curentă însăși (n=30), degradată (re-rulare)
    monkeypatch.setattr("supabase_client.get_recent_champion_health_evaluations",
                        lambda tid, limit=5: [{"n_matches_evaluated": 30, "trend_flag": True,
                                               "baseline_deviation_flag": None}])
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.health_state == "watch"  # NU degrading


# ── 5. Erori de infrastructură (best-effort) ────────────────────────────────

def test_served_outcomes_exception_returns_none(wired, monkeypatch):
    def _boom(f, l, s=None):
        raise RuntimeError("Supabase down")
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes", _boom)
    assert g.evaluate_champion_health("xgboost_v1", "all") is None


def test_record_failure_does_not_raise(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _uniform_rows(40))
    monkeypatch.setattr("supabase_client.record_champion_health_evaluation",
                        lambda **kw: False)  # eșec de scriere
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r is not None
    assert r.persisted is False


def test_baseline_source_trend_only_without_verdict(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _uniform_rows(40))
    # get_latest_challenger_evaluation = None (default fixture) → trend_only
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.baseline_source == "trend_only"


def test_baseline_source_promotion_evaluation_with_verdict(wired, monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_served_outcomes",
                        lambda f, l, s=None: _uniform_rows(40))
    monkeypatch.setattr("supabase_client.get_latest_challenger_evaluation",
                        lambda tid: {"brier_experiment": 0.30, "logloss_experiment": 0.9,
                                     "accuracy_experiment": 0.5})
    r = g.evaluate_champion_health("xgboost_v1", "all")
    assert r.baseline_source == "promotion_evaluation"
    assert r.brier_baseline == 0.30


# ── Unități: dimensiuni + utilitare ─────────────────────────────────────────

def test_live_metrics_all_correct():
    rows = _uniform_rows(10)  # toate H, ph=0.5 → predict H → accuracy 1.0
    brier, logloss, acc = g._live_metrics(rows)
    assert acc == 1.0
    assert brier == pytest.approx(0.38, abs=1e-9)  # (0.5-1)^2+0.3^2+0.2^2


def test_trend_degradation_detects_worse_recent():
    assert g._trend_degradation(_trend_degraded_rows(30)) is True
    assert g._trend_degradation(_uniform_rows(30)) is False  # constant → nu


def test_stability_dispersion():
    ind, flag = g._stability(_uniform_rows(10))  # confidence constant → std 0
    assert ind == pytest.approx(0.0)
    assert flag is False


def test_f2_f_guards_non_finite():
    assert g._f(float("nan")) is None
    assert g._f(float("inf")) is None
    assert g._f(0.5) == 0.5
    assert g._f(None) is None
    assert g._f("x") is None


def test_date_only():
    assert g._date_only("2026-07-20T12:16:03+00:00") == "2026-07-20"
    assert g._date_only(None) is None
