"""
Teste izolate pentru ml_feature_pipeline.compute_derived_dominance_features()
(Phase 2, ML_IMPLEMENTATION_ROADMAP.md, ADR-051) — funcție pură, extrasă din
ml_predictor.MLPredictorEngine._fetch_training_dataframe(), unde era inline.

Acoperirea end-to-end (via train(), cu XGBoost mock-uit) rămâne în
tests/test_ml_predictor_no_imputation.py — neschimbată de acest refactor,
servește drept dovadă de echivalență comportamentală (roadmap-ul cere
explicit "verificat prin test de echivalență, nu presupus"). Fișierul de
față testează DOAR funcția extrasă, izolat, fără a duplica acoperirea de
acolo.
"""
import numpy as np
import pandas as pd

from ml_feature_pipeline import compute_derived_dominance_features


def test_corner_dominance_computed_as_home_minus_away():
    df = pd.DataFrame({
        "home_corner_avg_recent": [5.0, 3.0], "away_corner_avg_recent": [4.5, 6.0],
    })
    result = compute_derived_dominance_features(df)
    assert list(result["corner_dominance"]) == [0.5, -3.0]


def test_card_diff_computed_as_away_minus_home():
    df = pd.DataFrame({
        "home_card_avg_recent": [1.5, 2.0], "away_card_avg_recent": [2.0, 1.0],
    })
    result = compute_derived_dominance_features(df)
    assert list(result["card_diff"]) == [0.5, -1.0]


def test_foul_diff_computed_as_away_minus_home():
    df = pd.DataFrame({
        "home_foul_avg_recent": [11.0, 9.0], "away_foul_avg_recent": [10.0, 12.0],
    })
    result = compute_derived_dominance_features(df)
    assert list(result["foul_diff"]) == [-1.0, 3.0]


def test_shot_dominance_computed_as_home_minus_away():
    df = pd.DataFrame({
        "home_shot_avg_recent": [12.0, 8.0], "away_shot_avg_recent": [9.5, 10.0],
    })
    result = compute_derived_dominance_features(df)
    assert list(result["shot_dominance"]) == [2.5, -2.0]


def test_all_four_columns_nan_when_raw_columns_absent():
    """Meci fără istoric de cornere/cartonașe/faulturi/șuturi — NaN nativ,
    niciodată aproximat (ADR-012/013/021, Regula #8 CLAUDE.md)."""
    df = pd.DataFrame({"unrelated_column": [1, 2, 3]})
    result = compute_derived_dominance_features(df)
    for col in ("corner_dominance", "card_diff", "foul_diff", "shot_dominance"):
        assert result[col].isna().all()


def test_partial_raw_columns_still_yields_nan_not_partial_computation():
    """Doar o singură coloană brută prezentă (ex. home_corner_avg_recent
    fără away_corner_avg_recent) — tot NaN, nu o eroare, nu o aproximare
    pe jumătate de formulă."""
    df = pd.DataFrame({"home_corner_avg_recent": [5.0, 3.0]})
    result = compute_derived_dominance_features(df)
    assert result["corner_dominance"].isna().all()


def test_returns_same_dataframe_object_mutated_in_place():
    """Comportament identic cu blocul inline pe care îl înlocuiește —
    modifică df în loc și îl întoarce, nu creează o copie."""
    df = pd.DataFrame({
        "home_corner_avg_recent": [5.0], "away_corner_avg_recent": [4.5],
    })
    result = compute_derived_dominance_features(df)
    assert result is df


def test_all_four_derived_columns_present_simultaneously():
    df = pd.DataFrame({
        "home_corner_avg_recent": [5.0], "away_corner_avg_recent": [4.5],
        "home_card_avg_recent": [1.5], "away_card_avg_recent": [2.0],
        "home_foul_avg_recent": [11.0], "away_foul_avg_recent": [10.0],
        "home_shot_avg_recent": [12.0], "away_shot_avg_recent": [9.5],
    })
    result = compute_derived_dominance_features(df)
    assert set(["corner_dominance", "card_diff", "foul_diff", "shot_dominance"]) <= set(result.columns)
    assert result["corner_dominance"].iloc[0] == 0.5
    assert result["card_diff"].iloc[0] == 0.5
    assert result["foul_diff"].iloc[0] == -1.0
    assert result["shot_dominance"].iloc[0] == 2.5
