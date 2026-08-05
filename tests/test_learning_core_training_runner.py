"""Teste pentru learning_core.training_runner — fără rețea, fără Supabase live."""
from pathlib import Path

import pytest

from learning_core import model_registry, storage
from learning_core.training_runner import run_training


class _DummyAlgorithm:
    name = "dummy_runner_test"
    version = "1"
    league_scope = "all"

    def fit(self, training_data):
        return model_registry.TrainingRunResult(
            training_run_id="dummy-run-id", status="trained", samples_used=5,
        )

    def predict(self, features):
        return (0.4, 0.3, 0.3, {})

    def describe(self):
        return {}


class _FailingAlgorithm:
    name = "failing_runner_test"
    version = "1"
    league_scope = "all"

    def fit(self, training_data):
        raise RuntimeError("antrenare eșuată intenționat, pentru test")

    def predict(self, features):
        return (0.0, 0.0, 0.0, {})

    def describe(self):
        return {}


@pytest.fixture(autouse=True)
def _reset_registry():
    model_registry._clear_registry_for_tests()
    yield
    model_registry._clear_registry_for_tests()


def test_run_training_success(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    model_registry.register(_DummyAlgorithm())

    report = run_training("dummy_runner_test", "1")

    assert report.algorithm_name == "dummy_runner_test"
    assert report.result.status == "trained"
    assert Path(report.saved_to).exists()


def test_run_training_unknown_algorithm_raises():
    with pytest.raises(KeyError):
        run_training("nu-exista", "1")


def test_run_training_propagates_fit_exception():
    model_registry.register(_FailingAlgorithm())
    with pytest.raises(RuntimeError):
        run_training("failing_runner_test", "1")


# ── Integrare xgboost_v1 — dovadă directă a golului închis (audit final) ───
# XGBoostV1Algorithm.fit() apelează MLPredictorEngine.train(), care se
# auto-persistă intern (ml_predictor._record_training_run()). Înainte de
# fix, training_runner.run_training() persista un AL DOILEA rând, cu un
# training_run_id diferit (uuid.uuid4() generat separat în fit()), pentru
# aceeași tentativă reală de antrenare. Testul de mai jos rulează fluxul
# complet CLI (learning_core/train.py -> run_training -> fit() ->
# MLPredictorEngine.train() real, date sintetice) și verifică direct în
# storage că a rezultat UN SINGUR rând, nu două.

def test_run_training_xgboost_v1_writes_exactly_one_training_run_row(tmp_path, monkeypatch):
    import ml_predictor
    from learning_core import champion_comparison
    from learning_core.algorithms.xgboost_v1 import XGBoostV1Algorithm

    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion", lambda *a, **kw: None)
    monkeypatch.setattr(ml_predictor.sb, "is_available", lambda: True)

    def _synthetic_rows(n=40):
        template = {
            "home_offensive_rating": 1.1, "home_defensive_rating": 0.9,
            "away_offensive_rating": 1.0, "away_defensive_rating": 1.0,
            "home_form_score": 0.5, "away_form_score": 0.5,
            "h2h_modifier": 0.0, "h2h_meetings": 0,
            "home_corner_avg_recent": 5.0, "away_corner_avg_recent": 4.5,
            "home_card_avg_recent": 1.5, "away_card_avg_recent": 2.0,
            "home_foul_avg_recent": 11.0, "away_foul_avg_recent": 10.0,
        }
        rows = []
        for i in range(n):
            row = dict(template)
            row["home_elo"] = 1500 + (i % 5) * 10
            row["away_elo"] = 1500 - (i % 5) * 10
            row["actual_result"] = ["H", "D", "A"][i % 3]
            row["kickoff_date"] = f"2026-01-{(i % 28) + 1:02d}"
            rows.append(row)
        return rows

    monkeypatch.setattr(ml_predictor.sb, "get_training_data", lambda only_with_results=True: _synthetic_rows())
    monkeypatch.setattr(ml_predictor.sb, "save_ml_status", lambda **kw: True)

    model_registry.register(XGBoostV1Algorithm())

    report = run_training("xgboost_v1", "1")

    assert report.result.status == "trained"
    rows = storage.list_training_runs()
    matching = [r for r in rows if r["training_run_id"] == report.result.training_run_id]
    assert len(rows) == 1, f"așteptat exact 1 rând training_runs, găsit {len(rows)}: {rows}"
    assert len(matching) == 1
