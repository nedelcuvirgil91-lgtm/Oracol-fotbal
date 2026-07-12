"""Teste pentru learning_core.storage — fără rețea, scriere doar în tmp_path."""
from learning_core import storage
from learning_core.model_registry import TrainingRunResult


def test_save_and_list_training_run(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    result = TrainingRunResult(
        training_run_id="test-run-123", status="trained", samples_used=42,
        walk_forward_metrics={"accuracy": 0.5}, message="ok",
    )

    path = storage.save_training_run(
        result, algorithm_name="dummy", algorithm_version="1", league_scope="all",
    )

    assert path.exists()
    rows = storage.list_training_runs()
    assert len(rows) == 1
    assert rows[0]["training_run_id"] == "test-run-123"
    assert rows[0]["algorithm_name"] == "dummy"
    assert rows[0]["walk_forward_metrics"] == {"accuracy": 0.5}


def test_list_training_runs_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    assert storage.list_training_runs() == []


def test_list_training_runs_most_recent_first(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    storage.save_training_run(
        TrainingRunResult(training_run_id="run-a", status="trained"),
        algorithm_name="dummy", algorithm_version="1", league_scope="all",
    )
    storage.save_training_run(
        TrainingRunResult(training_run_id="run-b", status="trained"),
        algorithm_name="dummy", algorithm_version="1", league_scope="all",
    )
    rows = storage.list_training_runs()
    assert len(rows) == 2
    assert rows[0]["created_at"] >= rows[1]["created_at"]
