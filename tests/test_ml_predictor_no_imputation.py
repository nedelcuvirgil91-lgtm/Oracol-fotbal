"""
Teste pentru eliminarea imputării cu mediană globală din
MLPredictorEngine.train()/predict() — fix pentru scurgerea de informație
descoperită la auditul de data leakage (2026-07-14).

Context: `fillna(df[FEATURE_COLUMNS].median())` era calculat pe tot setul
DEJA sortat cronologic, înainte de walk-forward validation — mediana
fold-urilor timpurii "vedea" astfel segmente viitoare. Contrazicea, în
plus, designul deja documentat pentru corner_dominance/card_diff
(ADR-012) și foul_diff (ADR-013): "gestionat nativ de XGBoost
(missing-value split), niciodată aproximat" — acum extins consecvent la
toate cele 13 coloane din FEATURE_COLUMNS, nu doar la cele 3.

Fără rețea — Supabase mockuit prin monkeypatch, XGBClassifier înlocuit cu
o clasă care înregistrează exact ce matrice X primește la fit()/
predict_proba(), ca să putem inspecta NaN-urile fără să depindem de
comportamentul intern real al XGBoost.
"""
import math

import numpy as np
import pandas as pd
import pytest

import ml_predictor
from ml_predictor import FEATURE_COLUMNS, MLPredictorEngine

FEATURE_ROW_TEMPLATE = {
    "home_offensive_rating": 1.1, "home_defensive_rating": 0.9,
    "away_offensive_rating": 1.0, "away_defensive_rating": 1.0,
    "home_form_score": 0.5, "away_form_score": 0.5,
    "home_elo": 1500, "away_elo": 1500,
    "h2h_modifier": 0.0, "h2h_meetings": 0,
}
RESULTS_CYCLE = ["H", "D", "A"]


class _RecordingXGBClassifier:
    """Înlocuiește xgboost.XGBClassifier — înregistrează matricea X primită
    la fiecare fit()/predict_proba(), fără să antreneze nimic real."""

    instances: list["_RecordingXGBClassifier"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.X_fit = None
        self.X_predict_calls: list[pd.DataFrame] = []
        _RecordingXGBClassifier.instances.append(self)

    def fit(self, X, y):
        self.X_fit = X.copy()
        self.y_fit = y.copy()
        return self

    def predict(self, X, output_margin=False):
        if output_margin:
            return np.zeros((len(X), 3), dtype=float)
        return np.zeros(len(X), dtype=int)

    def predict_proba(self, X):
        self.X_predict_calls.append(X.copy())
        return np.full((len(X), 3), 1 / 3)


@pytest.fixture(autouse=True)
def _reset_recorder():
    _RecordingXGBClassifier.instances.clear()
    yield
    _RecordingXGBClassifier.instances.clear()


@pytest.fixture
def engine_with_recording_xgb(monkeypatch):
    monkeypatch.setattr("xgboost.XGBClassifier", _RecordingXGBClassifier)
    eng = MLPredictorEngine()
    monkeypatch.setattr(ml_predictor.sb, "is_available", lambda: True)
    monkeypatch.setattr(ml_predictor.sb, "save_ml_status", lambda **kw: True)
    monkeypatch.setattr("learning_core.storage.save_training_run", lambda *a, **kw: None)
    monkeypatch.setattr(
        "learning_core.champion_comparison.compare_to_champion",
        lambda *a, **kw: type("R", (), {"message": "n/a"})(),
    )
    return eng


def _rows_with_missing_corner_card_foul(n: int = 40) -> list[dict]:
    """corner/card/foul/shot brute LIPSESC (ca în producție azi, ~90% din
    rânduri) — trebuie să ajungă NaN în corner_dominance/card_diff/
    foul_diff/shot_dominance, nu aproximate."""
    rows = []
    for i in range(n):
        row = dict(FEATURE_ROW_TEMPLATE)
        row["home_elo"] = 1500 + (i % 5) * 10
        row["away_elo"] = 1500 - (i % 5) * 10
        row["actual_result"] = RESULTS_CYCLE[i % 3]
        row["kickoff_date"] = f"2026-01-{(i % 28) + 1:02d}"
        # fără home/away_corner_avg_recent, card_avg_recent, foul_avg_recent
        rows.append(row)
    return rows


def _rows_fully_populated(n: int = 40) -> list[dict]:
    """Toate cele 14 coloane complete, fără niciun NULL."""
    rows = []
    for i in range(n):
        row = dict(FEATURE_ROW_TEMPLATE)
        row["home_elo"] = 1500 + (i % 5) * 10
        row["away_elo"] = 1500 - (i % 5) * 10
        row["home_corner_avg_recent"] = 5.0 + (i % 3)
        row["away_corner_avg_recent"] = 4.5
        row["home_card_avg_recent"] = 1.5
        row["away_card_avg_recent"] = 2.0
        row["home_foul_avg_recent"] = 11.0
        row["away_foul_avg_recent"] = 10.0
        row["home_shot_avg_recent"] = 12.0
        row["away_shot_avg_recent"] = 9.5
        row["actual_result"] = RESULTS_CYCLE[i % 3]
        row["kickoff_date"] = f"2026-01-{(i % 28) + 1:02d}"
        rows.append(row)
    return rows


# ── DoD #1: NaN pentru corner_dominance/card_diff/foul_diff ajunge
# neschimbat la XGBoost (nu e aproximat) ──────────────────────────────────

def test_missing_corner_card_foul_reach_xgboost_as_nan_not_imputed(engine_with_recording_xgb, monkeypatch):
    monkeypatch.setattr(
        ml_predictor.sb, "get_training_data",
        lambda only_with_results=True: _rows_with_missing_corner_card_foul(),
    )

    result = engine_with_recording_xgb.train()
    assert result.status == "trained"

    # ultimul model instanțiat e cel de producție (după walk-forward,
    # care rulează primul, pe modele separate per fold).
    production_model = _RecordingXGBClassifier.instances[-1]
    X_fit = production_model.X_fit

    for col in ("corner_dominance", "card_diff", "foul_diff", "shot_dominance"):
        assert X_fit[col].isna().all(), (
            f"{col} trebuie să rămână NaN (nativ XGBoost), nu aproximat cu mediana"
        )


def test_no_nan_is_silently_replaced_anywhere_in_pipeline(engine_with_recording_xgb, monkeypatch):
    """Gardă generală: NICIO valoare NaN din setul de antrenare nu trebuie
    să devină non-NaN pe drumul spre XGBoost (indiferent de coloană)."""
    rows = _rows_with_missing_corner_card_foul()
    monkeypatch.setattr(ml_predictor.sb, "get_training_data", lambda only_with_results=True: rows)

    engine_with_recording_xgb.train()

    raw_df = pd.DataFrame(rows)
    expected_nan_columns = {
        c for c in FEATURE_COLUMNS
        if c not in raw_df.columns or raw_df[c].isna().any()
        or c in ("corner_dominance", "card_diff", "foul_diff", "shot_dominance")
    }

    production_model = _RecordingXGBClassifier.instances[-1]
    for col in expected_nan_columns:
        assert production_model.X_fit[col].isna().any(), (
            f"{col} avea NaN în sursă dar nu mai are NaN în matricea trimisă la fit() — a fost aproximat undeva"
        )


# ── DoD #2: regresie — dataset complet produce o matrice IDENTICĂ cu
# valorile brute (nicio transformare ascunsă) ─────────────────────────────

def test_fully_populated_dataset_input_matrix_matches_raw_values_exactly(engine_with_recording_xgb, monkeypatch):
    rows = _rows_fully_populated()
    monkeypatch.setattr(ml_predictor.sb, "get_training_data", lambda only_with_results=True: rows)

    engine_with_recording_xgb.train()

    df = pd.DataFrame(rows)
    df["corner_dominance"] = df["home_corner_avg_recent"] - df["away_corner_avg_recent"]
    df["card_diff"] = df["away_card_avg_recent"] - df["home_card_avg_recent"]
    df["foul_diff"] = df["away_foul_avg_recent"] - df["home_foul_avg_recent"]
    df["shot_dominance"] = df["home_shot_avg_recent"] - df["away_shot_avg_recent"]
    df = df.sort_values("kickoff_date", kind="stable").reset_index(drop=True)
    expected = df[FEATURE_COLUMNS].astype(float)

    production_model = _RecordingXGBClassifier.instances[-1]
    pd.testing.assert_frame_equal(
        production_model.X_fit.reset_index(drop=True), expected.reset_index(drop=True),
    )


# ── predict() — consistență cu train(): NaN nativ, nu 0.0/mediană ────────

def test_predict_passes_nan_natively_not_zero_or_median():
    engine = MLPredictorEngine()
    engine.model = _RecordingXGBClassifier()
    engine.is_trained = True
    engine.feature_names = list(FEATURE_COLUMNS)
    engine.model_version = 1
    engine.samples_used = 100

    # simulăm exact ce trimite oracle_engine când corner/card/foul lipsesc:
    # cheile absente din dict -> predict() le mapează la np.nan (features.get(c, np.nan))
    features = {c: 1.0 for c in FEATURE_COLUMNS}
    for missing_col in ("corner_dominance", "card_diff", "foul_diff", "shot_dominance"):
        features.pop(missing_col, None)

    pred = engine.predict(features)
    assert pred is not None

    row_sent = engine.model.X_predict_calls[0]
    for missing_col in ("corner_dominance", "card_diff", "foul_diff", "shot_dominance"):
        value = row_sent.iloc[0][missing_col]
        assert math.isnan(value), (
            f"{missing_col} trebuie trimis ca NaN la predict_proba(), nu 0.0/mediană"
        )
