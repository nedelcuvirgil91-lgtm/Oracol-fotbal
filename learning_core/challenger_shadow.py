"""
================================================================================
FOOTBALL ORACLE — Learning Core: inferență Challenger pentru Shadow Logging
(Pasul 3, Implementation Contract)
================================================================================
Module: learning_core/challenger_shadow.py

O singură funcție: calculează probabilitățile (home, draw, away) ale unui
Challenger, pentru feature-urile deja calculate de predicția de producție —
nimic altceva. Nu decide dacă shadow logging e activ (asta rămâne în
oracle_engine.py, gated de `challenger_shadow_logging_enabled`), nu scrie
nimic — pur funcție de inferență, best-effort.

Reutilizează `ml_predictor.FEATURE_COLUMNS` (import read-only al unei
constante, nu modifică ml_predictor.py) — garantează că un Challenger e
evaluat cu exact aceeași listă de coloane ca modelul de producție, fără
duplicare care ar putea rămâne desincronizată la o viitoare promovare de
feature (ADR-012/013 și oricare viitoare).

Best-effort, simetric cu model_artifact_storage.py (Pasul 1): orice eșec
(artefact lipsă/corupt, Supabase indisponibil, eroare de inferență)
întoarce None, niciodată excepție necontrolată — apelantul din
oracle_engine.py rulează deja într-un bloc gated, izolat de predicția
servită utilizatorului.
================================================================================
"""
from __future__ import annotations

import logging

logger = logging.getLogger("FootballOracle.LearningCore.ChallengerShadow")


def predict_with_challenger(features: dict, training_run_id: str) -> tuple[float, float, float] | None:
    """Probabilitățile (prob_home, prob_draw, prob_away) ale Challenger-ului
    identificat prin training_run_id, pentru `features` (dict cu cheile din
    ml_predictor.FEATURE_COLUMNS — vine din oracle_engine._build_ml_features(),
    identic cu ce primește modelul de producție). None la orice eșec."""
    try:
        from learning_core import model_artifact_storage
        from ml_predictor import FEATURE_COLUMNS
        import numpy as np
        import pandas as pd

        model = model_artifact_storage.load_model_artifact(training_run_id)
        if model is None:
            return None

        row = pd.DataFrame([{c: features.get(c, np.nan) for c in FEATURE_COLUMNS}])
        row = row.astype(float)
        row = row.fillna(row.median(numeric_only=True)).fillna(0.0)
        probs = model.predict_proba(row)[0]
        return float(probs[0]), float(probs[1]), float(probs[2])
    except Exception as exc:
        logger.warning("[ChallengerShadow] predict_with_challenger eșuat pentru %s: %s",
                        training_run_id, exc)
        return None
