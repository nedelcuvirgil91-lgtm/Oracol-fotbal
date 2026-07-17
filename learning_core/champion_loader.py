"""
================================================================================
FOOTBALL ORACLE — Learning Core: Champion Loader (Pasul 6/7B, Implementation
Contract) — vezi ADR-019/RUNTIME_CONTRACT.md, Architecture Gate 6/7B
================================================================================
Module: learning_core/champion_loader.py

Aplică toate cele 6 condiții de utilizabilitate din
`docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md` — cele 5 originale (Champion
există/activ, artefact există/valid, deserializare funcțională) plus
`algorithm_version` compatibil (adăugat la Architecture Gate 6). None dacă
oricare eșuează — niciodată o folosire parțială (Regula #8 CLAUDE.md).

Acest modul NU decide dacă rezultatul lui e folosit pentru servire — asta
e responsabilitatea apelantului (`oracle_engine.py`). Din Pasul 7B,
`FootballOracleEngine._resolve_champion()` îl apelă exact O SINGURĂ DATĂ per
construcție și seedează `self.ml` direct dacă reușește — vezi
`ATOMICITY`-ul deciziei în `RUNTIME_CONTRACT.md`.

Complet izolat: niciun alt fișier din proiect nu importă acest modul în
afara `oracle_engine.py` și propriului test.
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("FootballOracle.LearningCore.ChampionLoader")


@dataclass
class ChampionLoadResult:
    training_run_id: str
    model: Any
    samples_used: int
    algorithm_family: str
    algorithm_version: str
    league_scope: str
    # [ADAUGAT — Pasul 7B] Metadate pt status_summary() Champion-aware
    # (Defectul B, Architecture Gate 7B) — niciodată folosite pentru decizie,
    # doar transportate mai departe către ml_predictor.seed_from_champion().
    accuracy: float | None
    log_loss: float | None
    trained_at: str | None


def load_champion_or_none(algorithm_family: str, league_scope: str) -> ChampionLoadResult | None:
    """Cele 6 condiții de utilizabilitate, verificate în ordine, fail-fast.
    None la orice eșec — niciodată excepție propagată către apelant."""
    try:
        import supabase_client as sb

        champion = sb.get_active_champion(algorithm_family, league_scope)
        if champion is None:
            return None  # Condițiile 1+2: există + activ

        training_run = sb.get_training_run(champion["training_run_id"])
        if training_run is None:
            return None

        from ml_predictor import _ALGORITHM_VERSION

        if training_run.get("algorithm_version") != _ALGORITHM_VERSION:
            logger.warning(
                "[ChampionLoader] Champion %s are algorithm_version=%r, codul curent așteaptă %r — tratat ca indisponibil.",
                champion["training_run_id"], training_run.get("algorithm_version"), _ALGORITHM_VERSION,
            )
            return None  # Condiția 6 (Architecture Gate 6)

        from learning_core import model_artifact_storage

        model = model_artifact_storage.load_model_artifact(champion["training_run_id"])
        if model is None:
            return None  # Condițiile 3+4: artefact există + valid

        import numpy as np
        from ml_predictor import FEATURE_COLUMNS

        probe = np.zeros((1, len(FEATURE_COLUMNS)))
        model.predict_proba(probe)  # Condiția 5: deserializare funcțională reală

        walk_forward_metrics = training_run.get("walk_forward_metrics") or {}

        return ChampionLoadResult(
            training_run_id=champion["training_run_id"],
            model=model,
            samples_used=training_run.get("samples_used", 0),
            algorithm_family=algorithm_family,
            algorithm_version=training_run.get("algorithm_version"),
            league_scope=league_scope,
            accuracy=walk_forward_metrics.get("accuracy"),
            log_loss=walk_forward_metrics.get("log_loss"),
            trained_at=training_run.get("created_at"),
        )
    except Exception as exc:
        logger.warning("[ChampionLoader] load_champion_or_none eșuat pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return None
