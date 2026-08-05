"""
================================================================================
FOOTBALL ORACLE — Learning Core: Local Model Cache
================================================================================
Module: learning_core/local_model_cache.py

[ADAUGAT — fix „aplicația pornește foarte greu"] Al doilea nivel de servire
ML, sub Champion, deasupra „fără ML": încarcă ultimul artefact antrenat cu
succes — NICIODATĂ nu antrenează nimic aici. Înainte, absența unui Champion
promovat însemna că `oracle_engine._initialize_ml()` reantrena XGBoost
sincron, la fiecare pornire de motor (fiecare restart de container, fiecare
„Clear cache") — 6 antrenări complete (5 fold-uri walk-forward + fit final)
pe tot istoricul (peste 50.000 de meciuri), blocând startup-ul 3-5 minute.
Acest modul elimină complet acel blocaj: antrenarea reală rămâne exclusiv
responsabilitatea learning_core/continuous_learning.py (Faza B, ADR-030),
decuplată, în fundal (cron GitHub Actions `continuous_learning.yml`),
niciodată în calea de servire.

Structural, oglindește champion_loader.py — aceleași condiții de
utilizabilitate (status=='trained', algorithm_version compatibil, artefact
încărcabil, deserializare funcțională reală) — dar sursa e
list_recent_training_runs() (orice antrenare reușită, indiferent dacă a
devenit vreodată Challenger/Champion), nu get_active_champion(). Încearcă
rândurile în ordine de la cel mai recent — dacă cel mai nou nu are artefact
persistat (ex. un retrain manual, retrain_ml_model(), care nu persistă
model_artifact_storage), cade grațios pe următorul cel mai recent cu
artefact valid, nu declară cache-ul indisponibil.

Nu implică nicio validare statistică — spre deosebire de un Champion
promovat, un model din cache NU a trecut prin Shadow Evaluation (North
Star #2); e tratat identic cu ce oracle_engine.py eticheta deja
`ml_source="local"` înainte de acest fix — doar încărcat, nu reantrenat.

Complet izolat: niciun alt fișier din proiect nu importă acest modul în
afara `oracle_engine.py` și propriului test.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("FootballOracle.LearningCore.LocalModelCache")

_MAX_CANDIDATES = 10


@dataclass
class LocalCacheLoadResult:
    training_run_id: str
    model: Any
    samples_used: int
    algorithm_family: str
    algorithm_version: str
    league_scope: str
    accuracy: float | None
    log_loss: float | None
    trained_at: str | None
    temperature: float | None


def load_latest_trained_model_or_none(algorithm_family: str, league_scope: str) -> LocalCacheLoadResult | None:
    """Ultimul artefact antrenat cu succes, servabil fără nicio antrenare.
    None dacă niciun candidat (dintre cele mai recente _MAX_CANDIDATES
    rulări) nu satisface toate condițiile — niciodată excepție propagată
    către apelant (Regula #8, degradare grațioasă, tipar identic
    champion_loader.py)."""
    try:
        import numpy as np

        import supabase_client as sb
        from learning_core import calibration_artifact_storage, model_artifact_storage
        from ml_predictor import _ALGORITHM_VERSION, FEATURE_COLUMNS

        candidates = sb.list_recent_training_runs(algorithm_family, league_scope, limit=_MAX_CANDIDATES)
        for training_run in candidates:
            if training_run.get("status") != "trained":
                continue
            if training_run.get("algorithm_version") != _ALGORITHM_VERSION:
                logger.warning(
                    "[LocalModelCache] Rularea %s are algorithm_version=%r, codul curent așteaptă %r — sărită.",
                    training_run.get("training_run_id"), training_run.get("algorithm_version"), _ALGORITHM_VERSION,
                )
                continue

            training_run_id = training_run["training_run_id"]
            model = model_artifact_storage.load_model_artifact(training_run_id)
            if model is None:
                continue

            try:
                probe = np.zeros((1, len(FEATURE_COLUMNS)))
                model.predict_proba(probe)
            except Exception as exc:
                logger.warning(
                    "[LocalModelCache] Artefact %s încărcat dar deserializare/inferență eșuată — sărit: %s",
                    training_run_id, exc,
                )
                continue

            walk_forward_metrics = training_run.get("walk_forward_metrics") or {}
            temperature = calibration_artifact_storage.load_calibration_artifact(training_run_id)

            return LocalCacheLoadResult(
                training_run_id=training_run_id,
                model=model,
                samples_used=training_run.get("samples_used", 0),
                algorithm_family=algorithm_family,
                algorithm_version=training_run.get("algorithm_version"),
                league_scope=league_scope,
                accuracy=walk_forward_metrics.get("accuracy"),
                log_loss=walk_forward_metrics.get("log_loss"),
                trained_at=training_run.get("created_at"),
                temperature=temperature,
            )

        return None
    except Exception as exc:
        logger.warning("[LocalModelCache] load_latest_trained_model_or_none eșuat pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return None
