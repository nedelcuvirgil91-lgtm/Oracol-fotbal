"""
================================================================================
FOOTBALL ORACLE — Learning Core: Blend Shadow Adapter (Pasul 13, derivat din
ADR-050) — vezi docs/00_GOVERNANCE/ADR-050-challenger-framework-compound-
algorithms.md și docs/04_LEARNING_CORE/PASUL13_IMPLEMENTATION_PLAN.md
================================================================================
Module: learning_core/blend_challenger_shadow.py

Mecanism de inferență shadow pentru un Challenger de tip Blend
(`algorithm_family="blend_v1"`) — fișier NOU, complet SEPARAT de
`learning_core/challenger_shadow.py`, care rămâne neatins (ADR-050 §4,
Implementation Plan §1/§2.2/§3: comportamentul Challenger-ului XGBoost
existent nu se schimbă).

Calea de inferență aleasă aici (Implementation Plan §2.3) reconstruiește
predicția direct din artefacte (`model_artifact_storage`/
`calibration_artifact_storage`), fără să treacă prin
`LearningAlgorithm.predict()` — decizie de execuție a acestei implementări,
nu o închidere arhitecturală (ADR-050 lasă forma deschisă).

`predict_with_blend_challenger()` primește `oracle_probs` DEJA calculate de
apelant (`oracle_engine.py`, pentru meciul curent) — NU recalculează
`feature_engine.calibrate_xg()`/`poisson_model()` aici, evitând duplicarea
logicii Oracle (risc semnalat explicit în audit/ADR-050 §5).

Calibrare↔blend (Implementation Plan §2.4): Temperature Scaling se aplică
pe probabilitățile submodelului ML ÎNAINTE de combinarea cu Oracle — ordinea
deja validată empiric la Pasul 11 (ML calibrat → Blend).

Ownership-ul ciclului de viață (Implementation Plan §2.5): acest modul NU
creează, NU tranziționează, NU evaluează Challenger-ul — reutilizează
integral `challenger_manager.py`/`continuous_learning.py`/
`shadow_testing.py`, deja generice. Singura responsabilitate de aici e
inferența + logarea shadow.

Best-effort, simetric cu `challenger_shadow.py`: orice eșec (Challenger
inexistent, artefact lipsă/corupt, Supabase indisponibil, eroare de
inferență) întoarce False/None, niciodată excepție necontrolată.
================================================================================
"""
from __future__ import annotations

import logging

logger = logging.getLogger("FootballOracle.LearningCore.BlendChallengerShadow")

_BLEND_ALGORITHM_FAMILY = "blend_v1"


def predict_with_blend_challenger(
    oracle_probs: tuple[float, float, float], features: dict, training_run_id: str,
) -> tuple[float, float, float] | None:
    """Probabilitățile blend (Oracle + submodel ML) ale Challenger-ului Blend
    identificat prin training_run_id, pentru `features` (dict cu cheile din
    ml_predictor.FEATURE_COLUMNS) și `oracle_probs` (deja calculate de
    apelant — NU recalculate aici). None la orice eșec."""
    try:
        from learning_core import calibration_artifact_storage, model_artifact_storage
        import supabase_client as sb
        from ml_predictor import FEATURE_COLUMNS, MLPrediction, _softmax_with_temperature, blend_predictions
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
            ml_probs = _softmax_with_temperature(margins, temperature)[0]
        else:
            ml_probs = model.predict_proba(row)[0]

        # samples_used e NOT NULL DEFAULT 0 in schema (training_runs, migration
        # 002) — .get(..., 0) e fallback doar pt cazul training_run=None
        # (run negasit/Supabase indisponibil), nu pt o coloana lipsa.
        training_run = sb.get_training_run(training_run_id)
        samples_used = training_run.get("samples_used", 0) if training_run else 0

        ml_pred = MLPrediction(
            prob_home=float(ml_probs[0]), prob_draw=float(ml_probs[1]), prob_away=float(ml_probs[2]),
            confidence=float(max(ml_probs)), model_version=1, samples_used=samples_used,
        )
        ph, pd_, pa, _label = blend_predictions(oracle_probs, ml_pred)
        return ph, pd_, pa
    except Exception as exc:
        logger.warning("[BlendChallengerShadow] predict_with_blend_challenger eșuat pentru %s: %s",
                        training_run_id, exc)
        return None


def log_shadow_for_active_blend_challenger(
    league_scope: str, oracle_probs: tuple[float, float, float], features: dict,
    fixture_id: str, home_xg: float, away_xg: float,
    league: str, home_team: str, away_team: str, kickoff_date: str,
) -> bool:
    """Punctul de intrare public, simetric cu
    challenger_shadow.log_shadow_for_active_challenger(), dar hardcodat pe
    algorithm_family="blend_v1" — NU generic peste mai multe familii
    compuse (YAGNI, un singur algoritm compus există azi).

    Nu face nimic (False) dacă nu există Challenger Blend activ pentru
    league_scope, sau dacă artefactul lui e indisponibil. Altfel, loghează
    prin shadow_testing.log_shadow_prediction() (deja existent, neschimbat)
    atât predicția Challenger-ului (experiment_group="treatment") cât și
    predicția Oracle deja servită, primită ca oracle_probs
    (experiment_group="control") — pereche necesară pentru comparația
    paired din shadow_testing.evaluate_experiment().

    Best-effort: orice excepție e prinsă aici, niciodată propagată către
    Oracle Engine (Regula #8, degradare grațioasă)."""
    try:
        from learning_core import challenger_manager

        active = challenger_manager.get_active_challenger(_BLEND_ALGORITHM_FAMILY, league_scope)
        if active is None:
            return False

        blend_probs = predict_with_blend_challenger(oracle_probs, features, active["training_run_id"])
        if blend_probs is None:
            return False
        b_ph, b_pd, b_pa = blend_probs

        import shadow_testing

        shadow_testing.log_shadow_prediction(
            fixture_id=fixture_id,
            experiment_name=_BLEND_ALGORITHM_FAMILY, experiment_version=active["training_run_id"],
            home_xg=home_xg, away_xg=away_xg,
            prob_home=b_ph, prob_draw=b_pd, prob_away=b_pa,
            experiment_group="treatment", processing_stage="final",
            league=league, home_team=home_team, away_team=away_team, kickoff_date=kickoff_date,
        )
        shadow_testing.log_shadow_prediction(
            fixture_id=fixture_id,
            experiment_name=_BLEND_ALGORITHM_FAMILY, experiment_version=active["training_run_id"],
            home_xg=home_xg, away_xg=away_xg,
            prob_home=oracle_probs[0], prob_draw=oracle_probs[1], prob_away=oracle_probs[2],
            experiment_group="control", processing_stage="final",
            league=league, home_team=home_team, away_team=away_team, kickoff_date=kickoff_date,
        )
        return True
    except Exception as exc:
        logger.warning("[BlendChallengerShadow] log_shadow_for_active_blend_challenger eșuat: %s", exc)
        return False
