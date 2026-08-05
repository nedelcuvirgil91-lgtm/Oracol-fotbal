"""
Teste pentru ADR-015 — MLPredictorEngine.train() înregistrează fiecare
rulare într-un training_run distinct (istoric, niciodată suprascris) și
compară cu campionul activ. Fără rețea — Supabase izolat prin monkeypatch,
storage local izolat prin tmp_path.

Cerințele exacte de validare (Chief Architect):
  1. Două antrenări succesive produc două training_runs distincte.
  2. Istoricul nu mai este suprascris.
  3. Comparația dintre modelul nou și Champion funcționează.
  4. Dacă Champion lipsește, sistemul gestionează elegant situația.
  5. Predictorul din producție continuă să folosească exact același model
     ca înainte — MLTrainingResult (contractul consumat de oracle_engine.py)
     rămâne identic, indiferent dacă înregistrarea reușește sau eșuează.
"""
import pytest

import ml_predictor
from learning_core import champion_comparison, storage

FEATURE_ROW_TEMPLATE = {
    "home_offensive_rating": 1.1, "home_defensive_rating": 0.9,
    "away_offensive_rating": 1.0, "away_defensive_rating": 1.0,
    "home_form_score": 0.5, "away_form_score": 0.5,
    "home_elo": 1500, "away_elo": 1500,
    "h2h_modifier": 0.0, "h2h_meetings": 0,
    "home_corner_avg_recent": 5.0, "away_corner_avg_recent": 4.5,
    "home_card_avg_recent": 1.5, "away_card_avg_recent": 2.0,
    "home_foul_avg_recent": 11.0, "away_foul_avg_recent": 10.0,
}
RESULTS_CYCLE = ["H", "D", "A"]


def _synthetic_rows(n: int = 40) -> list[dict]:
    rows = []
    for i in range(n):
        row = dict(FEATURE_ROW_TEMPLATE)
        row["home_elo"] = 1500 + (i % 5) * 10
        row["away_elo"] = 1500 - (i % 5) * 10
        row["actual_result"] = RESULTS_CYCLE[i % 3]
        row["kickoff_date"] = f"2026-01-{(i % 28) + 1:02d}"
        rows.append(row)
    return rows


@pytest.fixture
def isolated_learning_core(tmp_path, monkeypatch):
    """Storage local izolat (tmp_path) si Supabase complet mockuit pentru
    training_runs/model_champions — deterministic, fara retea."""
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)

    remote_runs: dict[str, dict] = {}

    def fake_save_training_run(training_run_id, algorithm_name, algorithm_version,
                                league_scope, status, samples_used,
                                walk_forward_metrics, message=""):
        remote_runs[training_run_id] = {
            "training_run_id": training_run_id, "status": status,
            "walk_forward_metrics": dict(walk_forward_metrics),
        }
        return True

    monkeypatch.setattr("supabase_client.save_training_run", fake_save_training_run)
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion", lambda *a, **kw: None)
    return remote_runs


@pytest.fixture
def engine(monkeypatch):
    eng = ml_predictor.MLPredictorEngine()
    monkeypatch.setattr(ml_predictor.sb, "is_available", lambda: True)
    monkeypatch.setattr(ml_predictor.sb, "get_training_data", lambda only_with_results=True: _synthetic_rows())
    monkeypatch.setattr(ml_predictor.sb, "save_ml_status", lambda **kw: True)
    return eng


def test_two_successive_trainings_produce_two_distinct_training_runs(engine, isolated_learning_core):
    result_1 = engine.train()
    result_2 = engine.train()

    assert result_1.status == "trained"
    assert result_2.status == "trained"

    rows = storage.list_training_runs()
    assert len(rows) == 2, "fiecare antrenare trebuie sa produca propriul training_run, nu sa-l suprascrie pe primul"
    ids = {r["training_run_id"] for r in rows}
    assert len(ids) == 2, "cele doua training_run_id trebuie sa fie distincte"


def test_history_not_overwritten_local_files_persist(engine, isolated_learning_core):
    engine.train()
    first_run_ids = {r["training_run_id"] for r in storage.list_training_runs()}

    engine.train()
    second_run_ids = {r["training_run_id"] for r in storage.list_training_runs()}

    assert first_run_ids.issubset(second_run_ids), "rularile anterioare trebuie sa ramana in istoric, nu sterse/suprascrise"
    assert len(second_run_ids) == 2


def test_remote_training_runs_also_recorded_distinctly(engine, isolated_learning_core):
    engine.train()
    engine.train()
    assert len(isolated_learning_core) == 2, "Supabase (fabricat) trebuie sa primeasca 2 randuri distincte, nu 1 suprascris"


def test_champion_missing_handled_gracefully_no_crash(engine, isolated_learning_core):
    """Cerinta #4 — cand nu exista Champion, train() tot reuseste normal."""
    result = engine.train()
    assert result.status == "trained"
    assert result.accuracy is not None


def test_comparison_works_when_champion_exists(engine, isolated_learning_core, monkeypatch):
    """Cerinta #3 — cu un Champion fabricat, compare_to_champion (apelat
    intern de _record_training_run) produce o comparatie reala."""
    monkeypatch.setattr(champion_comparison.sb, "get_active_champion",
                         lambda *a, **kw: {"training_run_id": "champ-run"})
    monkeypatch.setattr(champion_comparison.sb, "get_training_run", lambda *a, **kw: {
        "training_run_id": "champ-run",
        "walk_forward_metrics": {"accuracy": 0.1, "log_loss": 5.0, "brier_score": 1.0},
    })

    captured = {}
    original = champion_comparison.compare_to_champion

    def spy(*args, **kwargs):
        report = original(*args, **kwargs)
        captured["report"] = report
        return report

    # _record_training_run face import lazy din interiorul modulului champion_comparison —
    # patch-uim direct pe modul, ca sa fie vazut de importul lazy din train().
    monkeypatch.setattr("learning_core.champion_comparison.compare_to_champion", spy)

    result = engine.train()

    assert result.status == "trained"
    assert "report" in captured
    report = captured["report"]
    assert report.champion_exists is True
    assert report.comparable is True
    assert report.simultaneous_improvement is True  # modelul fabricat "champion" e mult mai slab


def test_train_stores_last_training_run_id_on_success(engine, isolated_learning_core):
    """Trasabilitate ML (ADR-052) — self.last_training_run_id trebuie sa
    identifice EXACT rularea persistata in training_runs, nu doar sa fie
    non-None generic."""
    engine.train()
    persisted_ids = {r["training_run_id"] for r in storage.list_training_runs()}
    assert engine.last_training_run_id is not None
    assert engine.last_training_run_id in persisted_ids


def test_train_produces_distinct_last_training_run_id_each_call(engine, isolated_learning_core):
    engine.train()
    first = engine.last_training_run_id
    engine.train()
    second = engine.last_training_run_id
    assert first != second


def test_last_training_run_id_survives_recording_failure(engine, isolated_learning_core, monkeypatch):
    """Chiar daca storage.save_training_run() esueaza (Cerinta #5 - train()
    tot reuseste), run_id-ul generat tot trebuie retinut - il identifica pe
    self.ml chiar daca nu a ajuns persistat (best-effort, docstring
    _record_training_run())."""
    def boom(*a, **kw):
        raise RuntimeError("simulated failure in recording layer")

    monkeypatch.setattr("learning_core.storage.save_training_run", boom)
    result = engine.train()

    assert result.status == "trained"
    assert engine.last_training_run_id is not None


def test_predictor_result_contract_unaffected_by_recording_failure(engine, isolated_learning_core, monkeypatch):
    """Cerinta #5 — daca inregistrarea (storage/comparatie) esueaza complet,
    MLTrainingResult ramane exact acelasi contract, train() nu se opreste."""
    def boom(*a, **kw):
        raise RuntimeError("simulated failure in recording layer")

    monkeypatch.setattr("learning_core.storage.save_training_run", boom)

    result = engine.train()

    assert result.status == "trained"
    assert result.samples_used > 0
    assert result.accuracy is not None
    assert result.log_loss is not None
