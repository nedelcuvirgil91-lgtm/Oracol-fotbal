"""
================================================================================
FOOTBALL ORACLE — Learning Core: Champion Loader (Pasul 6, Implementation
Contract) — vezi ADR-019/RUNTIME_CONTRACT.md, Architecture Gate 6
================================================================================
Module: learning_core/champion_loader.py

Aplică toate cele 6 condiții de utilizabilitate din
`docs/04_LEARNING_CORE/RUNTIME_CONTRACT.md` — cele 5 originale (Champion
există/activ, artefact există/valid, deserializare funcțională) plus
`algorithm_version` compatibil (adăugat la Architecture Gate 6). None dacă
oricare eșuează — niciodată o folosire parțială (Regula #8 CLAUDE.md).

── Pasul 6 vs. Pasul 7B ─────────────────────────────────────────────────────
Acest modul NU decide dacă rezultatul lui e folosit pentru servire — asta
e responsabilitatea apelantului. În Pasul 6, `oracle_engine.py` îl folosește
STRICT pentru diagnostic (`FootballOracleEngine.champion_diagnostic`) —
`self.ml`, ce servește efectiv predicțiile, rămâne populat exclusiv din
antrenarea locală. Switch-ul real de servire e Pasul 7B, gate arhitectural
separat, neautorizat încă.

Complet izolat: niciun alt fișier din proiect nu importă acest modul în
afara `oracle_engine.py` (diagnostic only, Pasul 6) și propriului test.
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

        return ChampionLoadResult(
            training_run_id=champion["training_run_id"],
            model=model,
            samples_used=training_run.get("samples_used", 0),
            algorithm_family=algorithm_family,
            algorithm_version=training_run.get("algorithm_version"),
            league_scope=league_scope,
        )
    except Exception as exc:
        logger.warning("[ChampionLoader] load_champion_or_none eșuat pentru %s/%s: %s",
                        algorithm_family, league_scope, exc)
        return None
