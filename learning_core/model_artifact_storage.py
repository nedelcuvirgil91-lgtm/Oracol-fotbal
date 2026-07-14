"""
================================================================================
FOOTBALL ORACLE — Learning Core: persistare artefact model (Pasul 1, izolat)
================================================================================
Module: learning_core/model_artifact_storage.py

Demonstrează DOAR că un model XGBoost antrenat poate fi persistat și
reîncărcat, producând predicții identice — nimic mai mult.

Nu implementează Challenger, Promotion, sau citirea Champion — vezi
Implementation Contract, Pasul 1. Modul complet izolat, autosuficient:
niciun alt fișier din proiect nu importă acest modul. Dacă fișierul ar fi
șters, restul aplicației funcționează identic.

Stochează în Supabase Storage, bucket privat `model-artifacts` (creat
aditiv, fără nicio legătură cu vreun tabel existent), cheie = training_run_id.
Serializare prin formatul nativ XGBoost (`save_model`/`load_model`, `.json`)
— nu pickle — pentru compatibilitate mai robustă între versiuni.

Best-effort, simetric cu restul proiectului (key_manager/cache_manager):
niciun eșec de aici nu ridică excepție necontrolată către apelant.
================================================================================
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

logger = logging.getLogger("FootballOracle.LearningCore.ModelArtifactStorage")

BUCKET_NAME = "model-artifacts"


def _artifact_path(training_run_id: str) -> str:
    safe_id = training_run_id.replace("/", "_")
    return f"{safe_id}.json"


def save_model_artifact(model, training_run_id: str) -> str | None:
    """Persistă un XGBClassifier deja antrenat, identificat prin
    training_run_id. Întoarce calea de storage la succes, None la eșec —
    niciodată nu ridică excepție (Regula #8, degradare grațioasă)."""
    try:
        import supabase_client as sb
        client = sb.get_client()
        if client is None:
            logger.warning("[ModelArtifactStorage] Supabase indisponibil — artefact nesalvat.")
            return None

        path = _artifact_path(training_run_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "model.json"
            model.save_model(str(tmp_path))
            raw_bytes = tmp_path.read_bytes()

        client.storage.from_(BUCKET_NAME).upload(
            path, raw_bytes, {"content-type": "application/json"}
        )
        logger.info("[ModelArtifactStorage] Artefact salvat: %s", path)
        return path
    except Exception as exc:
        logger.warning("[ModelArtifactStorage] save_model_artifact eșuat pentru %s: %s",
                        training_run_id, exc)
        return None


def load_model_artifact(training_run_id: str):
    """Reîncarcă un XGBClassifier persistat anterior. Întoarce None (nu
    excepție) dacă artefactul lipsește, e corupt, sau Storage e
    indisponibil — degradare grațioasă, Regula #8."""
    try:
        import supabase_client as sb
        from xgboost import XGBClassifier

        client = sb.get_client()
        if client is None:
            logger.warning("[ModelArtifactStorage] Supabase indisponibil — artefact nereîncărcat.")
            return None

        path = _artifact_path(training_run_id)
        raw_bytes = client.storage.from_(BUCKET_NAME).download(path)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / "model.json"
            tmp_path.write_bytes(raw_bytes)
            model = XGBClassifier()
            model.load_model(str(tmp_path))
        return model
    except Exception as exc:
        logger.warning("[ModelArtifactStorage] load_model_artifact eșuat pentru %s: %s",
                        training_run_id, exc)
        return None
