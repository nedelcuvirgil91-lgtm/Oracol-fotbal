"""
================================================================================
FOOTBALL ORACLE — Learning Core: Champion Loader pentru blend_v1 (ADR-061)
================================================================================
Module: learning_core/blend_v1_champion_loader.py

Analog cu `champion_loader.py` (Pasul 6/7B, RUNTIME_CONTRACT.md, FROZEN via
ADR-019) — dar NU o reutilizare a lui. `RUNTIME_CONTRACT.md` e scris explicit
la singular ("cum consumă Runtime UN Champion") și descrie strict starea
`self.ml`/`MLPredictorEngine`/`xgboost_v1` — condiția 6 de acolo compară
`training_run.algorithm_version` cu `ml_predictor._ALGORITHM_VERSION`, o
constantă legată de acea familie specifică, nu de un parametru generic.
Reutilizarea directă a `champion_loader.load_champion_or_none("blend_v1", ...)`
ar fi funcționat "din întâmplare" azi (ambele familii au version="1"), dar ar
fi reinterpretat tacit un contract FROZEN — vezi ADR-061 pentru analiza
completă.

Aceleași 6 condiții de utilizabilitate (RUNTIME_CONTRACT.md, adaptate):
  1. Champion există (model_champions, algorithm_family="blend_v1")
  2. Champion e activ (superseded_at IS NULL)
  3. Artefactul există (model_artifact_storage.load_model_artifact)
  4. Artefactul e valid (deserializare fără excepție)
  5. Deserializarea reușește (predict_proba apelabil real)
  6. algorithm_version compatibil — comparat cu
     `learning_core.algorithms.blend_v1.BlendV1Algorithm.version`, NU cu
     `ml_predictor._ALGORITHM_VERSION` (distincție deliberată, vezi ADR-061).

Spre deosebire de champion_loader.py: NU există fallback pe "antrenare
locală" — nu are sens un "blend_v1 local" fără un Challenger activ evaluat.
Indisponibilitatea Campionului înseamnă doar `available=False`, niciodată
aproximare (Regula #8 CLAUDE.md).

Semnătură restrânsă deliberat (league_scope, fără algorithm_family) — exact
tiparul din blend_challenger_shadow.py (`_BLEND_ALGORITHM_FAMILY` hardcodat,
YAGNI explicit, un singur algoritm compus există azi).

Complet izolat: consumatorul unic e oracle_engine.py
(_get_blend_v1_champion_prediction()) și propriul test.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("FootballOracle.LearningCore.BlendV1ChampionLoader")

_ALGORITHM_FAMILY = "blend_v1"


@dataclass
class BlendV1ChampionLoadResult:
    training_run_id: str
    model: Any
    samples_used: int
    league_scope: str
    algorithm_version: str
    accuracy: float | None
    log_loss: float | None
    trained_at: str | None
    temperature: float | None


def load_blend_v1_champion_or_none(league_scope: str) -> BlendV1ChampionLoadResult | None:
    """Cele 6 condiții de utilizabilitate, verificate în ordine, fail-fast.
    None la orice eșec — niciodată excepție propagată către apelant."""
    try:
        import supabase_client as sb

        champion = sb.get_active_champion(_ALGORITHM_FAMILY, league_scope)
        if champion is None:
            return None  # Condițiile 1+2: există + activ

        training_run = sb.get_training_run(champion["training_run_id"])
        if training_run is None:
            return None

        from learning_core.algorithms.blend_v1 import BlendV1Algorithm

        if training_run.get("algorithm_version") != BlendV1Algorithm.version:
            logger.warning(
                "[BlendV1ChampionLoader] Champion %s are algorithm_version=%r, "
                "codul curent așteaptă %r (BlendV1Algorithm.version) — tratat ca indisponibil.",
                champion["training_run_id"], training_run.get("algorithm_version"), BlendV1Algorithm.version,
            )
            return None  # Condiția 6

        from learning_core import model_artifact_storage

        model = model_artifact_storage.load_model_artifact(champion["training_run_id"])
        if model is None:
            return None  # Condițiile 3+4: artefact există + valid

        import numpy as np
        from ml_predictor import FEATURE_COLUMNS

        probe = np.zeros((1, len(FEATURE_COLUMNS)))
        model.predict_proba(probe)  # Condiția 5: deserializare funcțională reală

        walk_forward_metrics = training_run.get("walk_forward_metrics") or {}

        from learning_core import calibration_artifact_storage

        temperature = calibration_artifact_storage.load_calibration_artifact(champion["training_run_id"])

        return BlendV1ChampionLoadResult(
            training_run_id=champion["training_run_id"],
            model=model,
            samples_used=training_run.get("samples_used", 0),
            league_scope=league_scope,
            algorithm_version=training_run.get("algorithm_version"),
            accuracy=walk_forward_metrics.get("accuracy"),
            log_loss=walk_forward_metrics.get("log_loss"),
            trained_at=training_run.get("created_at"),
            temperature=temperature,
        )
    except Exception as exc:
        logger.warning("[BlendV1ChampionLoader] load_blend_v1_champion_or_none eșuat pentru %s: %s",
                        league_scope, exc)
        return None
