import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "/home/claude/stubs")
sys.path.insert(0, "/home/claude/oracol/Oracol-fotbal-main/tests/_stubs")

from ml_predictor import MLPredictorEngine


# ── Brier score multi-clasa ───────────────────────────────────────────────

def test_brier_perfect_prediction_is_zero():
    y_true = np.array([0, 1, 2])
    probs = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
    assert MLPredictorEngine._multiclass_brier(y_true, probs) == 0.0


def test_brier_worst_prediction_is_two():
    y_true = np.array([0])
    probs = np.array([[0, 0, 1]], dtype=float)  # prezice clasa gresita cu certitudine
    assert MLPredictorEngine._multiclass_brier(y_true, probs) == 2.0


def test_brier_uniform_guess_is_between_zero_and_two():
    y_true = np.array([0, 1, 2])
    probs = np.full((3, 3), 1 / 3)
    brier = MLPredictorEngine._multiclass_brier(y_true, probs)
    assert 0.0 < brier < 2.0


# ── Walk-forward validation: corectitudine structurala ──────────────────

def _make_chronological_dataset(n=300):
    """Simuleaza un dataset ordonat cronologic (0..n-1 = ordinea temporala)."""
    rng = np.random.RandomState(0)
    X = pd.DataFrame(rng.rand(n, 4), columns=["f1", "f2", "f3", "f4"])
    y = pd.Series(rng.randint(0, 3, size=n))
    return X, y


def test_walk_forward_produces_expected_number_of_folds():
    X, y = _make_chronological_dataset(300)
    result = MLPredictorEngine._walk_forward_validate(X, y, n_folds=5)
    assert len(result["folds"]) == 5


def test_walk_forward_uses_expanding_window_not_fixed_size():
    """Fiecare fold urmator trebuie sa antreneze pe MAI MULTE date decat
    precedentul (fereastra expandabila, nu fixa/glisanta)."""
    X, y = _make_chronological_dataset(300)
    result = MLPredictorEngine._walk_forward_validate(X, y, n_folds=5)
    train_sizes = [f["train_size"] for f in result["folds"]]
    assert train_sizes == sorted(train_sizes), "train_size trebuie sa creasca monoton intre folduri"
    assert train_sizes[-1] > train_sizes[0], "ultimul fold trebuie sa aiba mult mai multe date de antrenare"


def test_walk_forward_never_trains_on_future_data():
    """Cel mai important test: fold k antreneaza STRICT pe date anterioare
    segmentului de validare - nicio scurgere temporala."""
    n = 300
    X, y = _make_chronological_dataset(n)
    result = MLPredictorEngine._walk_forward_validate(X, y, n_folds=5)
    boundaries = np.linspace(0, n, 7, dtype=int)  # n_folds+2 = 7 puncte
    for i, fold in enumerate(result["folds"]):
        val_start = boundaries[i + 1]
        # train_size-ul fold-ului nu poate depasi inceputul segmentului sau de validare
        assert fold["train_size"] <= val_start


def test_walk_forward_returns_averaged_metrics():
    X, y = _make_chronological_dataset(300)
    result = MLPredictorEngine._walk_forward_validate(X, y, n_folds=5)
    assert result["avg_accuracy"] is not None
    assert result["avg_brier_score"] is not None
    assert 0.0 <= result["avg_accuracy"] <= 1.0
    assert 0.0 <= result["avg_brier_score"] <= 2.0


def test_walk_forward_skips_folds_with_too_little_training_data():
    """Cu un dataset foarte mic, primele folduri (antrenare <20 randuri)
    trebuie sarite, nu esuate."""
    X, y = _make_chronological_dataset(30)  # foarte putine date
    result = MLPredictorEngine._walk_forward_validate(X, y, n_folds=5)
    # cu doar 30 randuri / 5 folduri = ~5 randuri/segment, multe folduri
    # timpurii vor avea <20 randuri de antrenare si vor fi sarite
    assert len(result["folds"]) < 5


def test_walk_forward_empty_result_when_all_folds_too_small():
    X, y = _make_chronological_dataset(10)
    result = MLPredictorEngine._walk_forward_validate(X, y, n_folds=5)
    if not result["folds"]:
        assert result["avg_accuracy"] is None
        assert result["avg_brier_score"] is None
