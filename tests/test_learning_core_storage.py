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


def test_save_training_run_idempotent_on_same_id(tmp_path, monkeypatch):
    """[ADAUGAT — audit final ADR-051/052] O a doua scriere cu ACELAȘI
    training_run_id trebuie să fie no-op — nu suprascrie fișierul local, nu
    reîncearcă scrierea remote. Necesar de când XGBoostV1Algorithm.fit()
    refolosește training_run_id-ul deja persistat de MLPredictorEngine.
    train() intern — fără idempotență, al doilea apel (din
    training_runner.run_training()) ar suprascrie un rând mai complet cu
    unul mai sărac, plus un INSERT remote redundant care ar eșua oricum pe
    constraint UNIQUE."""
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)
    remote_calls = []
    monkeypatch.setattr("supabase_client.save_training_run", lambda **kw: remote_calls.append(kw) or True)

    first = TrainingRunResult(
        training_run_id="dup-run", status="trained", samples_used=100,
        walk_forward_metrics={"accuracy": 0.5, "brier_score": 0.6}, message="complet",
    )
    storage.save_training_run(first, algorithm_name="xgboost_v1", algorithm_version="1", league_scope="all")
    assert len(remote_calls) == 1

    poorer = TrainingRunResult(
        training_run_id="dup-run", status="trained", samples_used=1,
        walk_forward_metrics={}, message="ar-fi-suprascris",
    )
    storage.save_training_run(poorer, algorithm_name="xgboost_v1", algorithm_version="1", league_scope="all")

    rows = storage.list_training_runs()
    assert len(rows) == 1
    assert rows[0]["samples_used"] == 100, "rândul original (mai complet) nu trebuie suprascris"
    assert rows[0]["message"] == "complet"
    assert len(remote_calls) == 1, "a doua scriere nu trebuie să reîncerce apelul remote"


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
