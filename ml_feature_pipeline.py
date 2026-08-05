"""
================================================================================
FOOTBALL ORACLE — ML Feature Pipeline (Phase 2, ADR-051)
================================================================================
Module: ml_feature_pipeline.py

Feature-uri derivate pentru antrenarea ML (corner_dominance/card_diff/
foul_diff/shot_dominance) — extrase din
ml_predictor.MLPredictorEngine._fetch_training_dataframe(), unde erau
inline, cuplate. Decuplare comportament-identică (Phase 2,
ML_IMPLEMENTATION_ROADMAP.md) — zero feature nou, zero schimbare la
FEATURE_COLUMNS, aceeași formulă, aceeași disciplină NaN (gestionat nativ
de XGBoost, niciodată aproximat — ADR-012/013/021).

De ce NU în feature_engine.py: acel modul e scopat explicit, în propriul
docstring, la matematica comună între oracle_engine.py (live) și
sync/backfill_features.py (backfill retrospectiv). Funcția de mai jos e
folosită azi exclusiv de ml_predictor.py (antrenare) — o a treia
proveniență, distinctă de cele două deja acoperite acolo, nu „matematică
comună" în sensul deja declarat al acelui modul. Modul nou, dedicat,
reutilizabil de orice viitor al doilea algoritm ML din Model Registry —
motivul explicit citat de v3 §1.2.C / v4 §2 pentru această decuplare.
================================================================================
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def compute_derived_dominance_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculează corner_dominance/card_diff/foul_diff/shot_dominance din
    cele 8 coloane brute (*_avg_recent) — identic, linie cu linie, cu
    logica anterior inline din ml_predictor._fetch_training_dataframe()
    (ADR-012/013/021). NaN dacă brutele lipsesc (meci fără istoric) —
    gestionat nativ de XGBoost (missing-value split), niciodată aproximat.

    Modifică `df` în loc (adaugă 4 coloane noi) și îl întoarce — exact
    comportamentul funcției pe care o înlocuiește."""
    # [ADR-012] corner_dominance/card_diff se calculează din cele 4 coloane
    # brute, nu se citesc direct.
    if "home_corner_avg_recent" in df.columns and "away_corner_avg_recent" in df.columns:
        df["corner_dominance"] = df["home_corner_avg_recent"] - df["away_corner_avg_recent"]
    else:
        df["corner_dominance"] = np.nan
    if "home_card_avg_recent" in df.columns and "away_card_avg_recent" in df.columns:
        df["card_diff"] = df["away_card_avg_recent"] - df["home_card_avg_recent"]
    else:
        df["card_diff"] = np.nan
    # [ADR-013] foul_diff, aceeași disciplină ca mai sus.
    if "home_foul_avg_recent" in df.columns and "away_foul_avg_recent" in df.columns:
        df["foul_diff"] = df["away_foul_avg_recent"] - df["home_foul_avg_recent"]
    else:
        df["foul_diff"] = np.nan
    # [ADR-021, P7.1] shot_dominance, aceeași disciplină.
    if "home_shot_avg_recent" in df.columns and "away_shot_avg_recent" in df.columns:
        df["shot_dominance"] = df["home_shot_avg_recent"] - df["away_shot_avg_recent"]
    else:
        df["shot_dominance"] = np.nan
    return df
