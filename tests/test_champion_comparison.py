"""
Teste pentru learning_core.champion_comparison — fără rețea, Supabase
fabricat (monkeypatch pe funcțiile din supabase_client folosite intern).
"""
from learning_core import champion_comparison


def test_no_champion_reported_explicitly_not_as_error(monkeypatch):
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion", lambda *a, **kw: None)
    report = champion_comparison.compare_to_champion(
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
        new_training_run_id="run-new", new_metrics={"accuracy": 0.5},
    )
    assert report.champion_exists is False
    assert report.comparable is False
    assert "Niciun campion" in report.message


def test_champion_exists_but_training_run_missing(monkeypatch):
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion",
                         lambda *a, **kw: {"training_run_id": "run-champ"})
    monkeypatch.setattr(champion_comparison.sb, "get_training_run", lambda *a, **kw: None)
    report = champion_comparison.compare_to_champion(
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
        new_training_run_id="run-new", new_metrics={"accuracy": 0.5},
    )
    assert report.champion_exists is True
    assert report.comparable is False
    assert report.champion_training_run_id == "run-champ"


def test_comparison_computes_deltas_and_simultaneous_improvement_true(monkeypatch):
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion",
                         lambda *a, **kw: {"training_run_id": "run-champ"})
    monkeypatch.setattr(champion_comparison.sb, "get_training_run", lambda *a, **kw: {
        "training_run_id": "run-champ",
        "walk_forward_metrics": {"accuracy": 0.46, "log_loss": 1.08, "brier_score": 0.64},
    })
    report = champion_comparison.compare_to_champion(
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
        new_training_run_id="run-new",
        new_metrics={"accuracy": 0.47, "log_loss": 1.07, "brier_score": 0.63},
    )
    assert report.comparable is True
    assert report.delta["accuracy"] == 0.01
    assert report.delta["log_loss"] == -0.01
    assert report.delta["brier_score"] == -0.01
    assert report.improved == {"accuracy": True, "log_loss": True, "brier_score": True}
    assert report.simultaneous_improvement is True


def test_comparison_simultaneous_improvement_false_when_mixed(monkeypatch):
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion",
                         lambda *a, **kw: {"training_run_id": "run-champ"})
    monkeypatch.setattr(champion_comparison.sb, "get_training_run", lambda *a, **kw: {
        "training_run_id": "run-champ",
        "walk_forward_metrics": {"accuracy": 0.46, "log_loss": 1.08},
    })
    report = champion_comparison.compare_to_champion(
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
        new_training_run_id="run-new",
        new_metrics={"accuracy": 0.47, "log_loss": 1.10},  # accuracy mai buna, log_loss mai slab
    )
    assert report.improved == {"accuracy": True, "log_loss": False}
    assert report.simultaneous_improvement is False


def test_comparison_missing_common_metrics_not_comparable(monkeypatch):
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion",
                         lambda *a, **kw: {"training_run_id": "run-champ"})
    monkeypatch.setattr(champion_comparison.sb, "get_training_run", lambda *a, **kw: {
        "training_run_id": "run-champ",
        "walk_forward_metrics": {},
    })
    report = champion_comparison.compare_to_champion(
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
        new_training_run_id="run-new", new_metrics={"accuracy": 0.5},
    )
    assert report.comparable is False
    assert report.delta == {}
    assert report.simultaneous_improvement is None
