"""
================================================================================
FOOTBALL ORACLE — Learning Core: persistare artefact de calibrare (Pasul 10a)
================================================================================
Module: learning_core/calibration_artifact_storage.py

Persistă/încarcă parametrul de calibrare (Temperature Scaling, ADR-049) al
unui model XGBoost antrenat, identificat prin același `training_run_id` ca
artefactul de model — dar ca artefact SEPARAT, complet independent de
`model_artifact_storage.py` (neatins de acest modul, per ADR-049 §7C).

Stochează în același bucket Supabase Storage `model-artifacts`, cheie
`<training_run_id>.calibration.json`, conținut minimal `{"temperature": T}`.

Semantica valorii `temperature`: strict pozitivă (T>0), finită (nu
NaN/±inf). `T == 1.0` e o valoare validă, normală — înseamnă "calibrare
fără efect" (softmax(z/1) == softmax(z), transformare identitate), NU
"necalibrat". Un model necalibrat e reprezentat prin absența artefactului
(`load_calibration_artifact()` întoarce None), nu prin T=1 persistat —
distincție deliberată, ca `MLPredictorEngine.predict()` să poată alege
corect calea (calibrată vs. `predict_proba()` nativă) doar pe baza
existenței artefactului.

Best-effort, simetric cu `model_artifact_storage.py`: niciun eșec de aici
ridică excepție necontrolată către apelant.
================================================================================
"""
from __future__ import annotations

import json
import logging
import math

logger = logging.getLogger("FootballOracle.LearningCore.CalibrationArtifactStorage")

BUCKET_NAME = "model-artifacts"


def _artifact_path(training_run_id: str) -> str:
    # Reutilizează exact regula de normalizare a lui model_artifact_storage.py
    # (nu duplicată aici) — cele două artefacte trebuie să rămână derivate
    # din același training_run_id printr-o SINGURĂ regulă, ca să nu se
    # desincronizeze dacă naming-ul modelului se schimbă vreodată. Import
    # read-only — model_artifact_storage.py rămâne complet neatins.
    from learning_core.model_artifact_storage import _artifact_path as _model_artifact_path

    model_path = _model_artifact_path(training_run_id)  # "<safe_id>.json"
    safe_id = model_path.removesuffix(".json")
    return f"{safe_id}.calibration.json"


def _is_valid_temperature(temperature) -> bool:
    return isinstance(temperature, (int, float)) and not isinstance(temperature, bool) \
        and math.isfinite(temperature) and temperature > 0


def save_calibration_artifact(temperature: float, training_run_id: str) -> str | None:
    """Persistă parametrul de temperatură (Temperature Scaling, ADR-049)
    pentru un training_run_id dat. Întoarce calea de storage la succes,
    None la eșec — niciodată nu ridică excepție (Regula #8, degradare
    grațioasă). `temperature` trebuie să fie strict pozitivă și finită
    (nu NaN/±inf) — validat aici, nu doar la fitting."""
    if not _is_valid_temperature(temperature):
        logger.warning("[CalibrationArtifactStorage] temperature invalidă (%r) — artefact nesalvat.", temperature)
        return None
    try:
        import supabase_client as sb
        client = sb.get_client()
        if client is None:
            logger.warning("[CalibrationArtifactStorage] Supabase indisponibil — artefact nesalvat.")
            return None

        path = _artifact_path(training_run_id)
        payload = json.dumps({"temperature": float(temperature)}).encode("utf-8")

        client.storage.from_(BUCKET_NAME).upload(
            path, payload, {"content-type": "application/json"}
        )
        logger.info("[CalibrationArtifactStorage] Artefact salvat: %s", path)
        return path
    except Exception as exc:
        logger.warning("[CalibrationArtifactStorage] save_calibration_artifact eșuat pentru %s: %s",
                        training_run_id, exc)
        return None


def load_calibration_artifact(training_run_id: str) -> float | None:
    """Reîncarcă parametrul de temperatură persistat anterior. Întoarce
    None (nu excepție) dacă artefactul lipsește, e corupt, are o valoare
    invalidă (T<=0 sau non-finită — NaN/±inf), sau Storage e indisponibil
    — degradare grațioasă, Regula #8."""
    try:
        import supabase_client as sb
        client = sb.get_client()
        if client is None:
            logger.warning("[CalibrationArtifactStorage] Supabase indisponibil — artefact nereîncărcat.")
            return None

        path = _artifact_path(training_run_id)
        raw_bytes = client.storage.from_(BUCKET_NAME).download(path)
        data = json.loads(raw_bytes.decode("utf-8"))
        temperature = data.get("temperature")
        if not _is_valid_temperature(temperature):
            logger.warning("[CalibrationArtifactStorage] temperature invalidă în artefact (%r) pentru %s.",
                            temperature, training_run_id)
            return None
        return float(temperature)
    except Exception as exc:
        logger.warning("[CalibrationArtifactStorage] load_calibration_artifact eșuat pentru %s: %s",
                        training_run_id, exc)
        return None
