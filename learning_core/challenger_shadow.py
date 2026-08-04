"""
================================================================================
FOOTBALL ORACLE — Learning Core: Shadow Adapter (Pasul 3, Implementation
Contract) — vezi ADR-017, addendum Chief Architect Review
================================================================================
Module: learning_core/challenger_shadow.py

Singura frontieră între Oracle Engine (Prediction Pipeline) și
Challenger Manager / Shadow Testing infrastructure. Regulă arhitecturală
explicită (Chief Architect Review, post-Pasul 3):

    OracleEngine → Shadow Adapter (acest modul) → ChallengerManager

    NU:  OracleEngine → ChallengerManager  (direct, interzis)

`oracle_engine.py` nu importă niciodată `learning_core.challenger_manager`
direct — trece exclusiv prin `log_shadow_for_active_challenger()`, singurul
punct de intrare public al acestui modul folosit de Oracle Engine. Verificat
prin gardă arhitecturală (`tests/test_challenger_shadow_logging.py`).

Shadow e un SIDE EFFECT al predicției, nu parte din Prediction Pipeline:

    Prediction Pipeline:  Input → Prediction → Return către utilizator
    Side Effect:                  Prediction → Shadow Logging (nu invers)

`log_shadow_for_active_challenger()` nu întoarce nimic folosit de apelant
pentru a construi predicția, nu poate influența Prediction Pipeline — e
strict observațională. Best-effort: orice eșec (Challenger inexistent,
artefact lipsă/corupt, Supabase indisponibil, eroare de inferență)
întoarce False, niciodată excepție necontrolată.

Reutilizează `ml_predictor.FEATURE_COLUMNS` (import read-only al unei
constante, nu modifică ml_predictor.py) — garantează că un Challenger e
evaluat cu exact aceeași listă de coloane ca modelul de producție, fără
duplicare care ar putea rămâne desincronizată la o viitoare promovare de
feature (ADR-012/013 și oricare viitoare).
================================================================================
"""
from __future__ import annotations

import logging

logger = logging.getLogger("FootballOracle.LearningCore.ChallengerShadow")


def predict_with_challenger(features: dict, training_run_id: str) -> tuple[float, float, float] | None:
    """Probabilitățile (prob_home, prob_draw, prob_away) ale Challenger-ului
    identificat prin training_run_id, pentru `features` (dict cu cheile din
    ml_predictor.FEATURE_COLUMNS). None la orice eșec.

    [ADAUGAT — ADR-049, Pasul 10a] Dacă există o calibrare validă
    (Temperature Scaling) pentru același training_run_id, se aplică pe
    marginile brute ale modelului — altfel cade grațios pe predict_proba()
    nativă, exact calea de dinainte de acest pas. Absența calibrării NU
    oprește shadow logging-ul (spre deosebire de gate-ul de la creare,
    continuous_learning.py) — degradare grațioasă, nu blocare, fiindcă
    funcția rulează la fiecare predicție live (ADR-049 §8/§9)."""
    try:
        from learning_core import calibration_artifact_storage, model_artifact_storage
        from ml_predictor import FEATURE_COLUMNS, _softmax_with_temperature
        import numpy as np
        import pandas as pd

        model = model_artifact_storage.load_model_artifact(training_run_id)
        if model is None:
            return None

        row = pd.DataFrame([{c: features.get(c, np.nan) for c in FEATURE_COLUMNS}])
        row = row.astype(float)
        row = row.fillna(row.median(numeric_only=True)).fillna(0.0)

        temperature = calibration_artifact_storage.load_calibration_artifact(training_run_id)
        if temperature is not None:
            margins = model.predict(row, output_margin=True)
            probs = _softmax_with_temperature(margins, temperature)[0]
        else:
            probs = model.predict_proba(row)[0]

        return float(probs[0]), float(probs[1]), float(probs[2])
    except Exception as exc:
        logger.warning("[ChallengerShadow] predict_with_challenger eșuat pentru %s: %s",
                        training_run_id, exc)
        return None


def log_shadow_for_active_challenger(
    algorithm_family: str, league_scope: str, features: dict,
    fixture_id: str, home_xg: float, away_xg: float,
    control_prob_home: float, control_prob_draw: float, control_prob_away: float,
    league: str, home_team: str, away_team: str, kickoff_date: str,
) -> bool:
    """Punctul de intrare PUBLIC folosit de oracle_engine.py — singurul.
    Nu face nimic (False) dacă nu există Challenger activ pentru
    (algorithm_family, league_scope), sau dacă artefactul lui e
    indisponibil. Altfel, loghează prin shadow_testing.log_shadow_prediction()
    (deja existent, neschimbat) atât predicția Challenger-ului
    (experiment_group="treatment") cât și predicția reală deja servită,
    primită ca parametri control_prob_* (experiment_group="control") —
    pereche necesară pentru comparația paired din
    shadow_testing.evaluate_experiment().

    Best-effort: orice excepție e prinsă aici, niciodată propagată către
    Oracle Engine (Regula #8, degradare grațioasă)."""
    try:
        from learning_core import challenger_manager

        active = challenger_manager.get_active_challenger(algorithm_family, league_scope)
        if active is None:
            return False

        challenger_probs = predict_with_challenger(features, active["training_run_id"])
        if challenger_probs is None:
            return False
        c_ph, c_pd, c_pa = challenger_probs

        import shadow_testing

        shadow_testing.log_shadow_prediction(
            fixture_id=fixture_id,
            experiment_name=algorithm_family, experiment_version=active["training_run_id"],
            home_xg=home_xg, away_xg=away_xg,
            prob_home=c_ph, prob_draw=c_pd, prob_away=c_pa,
            experiment_group="treatment", processing_stage="final",
            league=league, home_team=home_team, away_team=away_team, kickoff_date=kickoff_date,
        )
        shadow_testing.log_shadow_prediction(
            fixture_id=fixture_id,
            experiment_name=algorithm_family, experiment_version=active["training_run_id"],
            home_xg=home_xg, away_xg=away_xg,
            prob_home=control_prob_home, prob_draw=control_prob_draw, prob_away=control_prob_away,
            experiment_group="control", processing_stage="final",
            league=league, home_team=home_team, away_team=away_team, kickoff_date=kickoff_date,
        )
        return True
    except Exception as exc:
        logger.warning("[ChallengerShadow] log_shadow_for_active_challenger eșuat: %s", exc)
        return False
