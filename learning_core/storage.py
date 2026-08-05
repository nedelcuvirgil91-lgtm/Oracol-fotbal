"""
================================================================================
FOOTBALL ORACLE — Learning Core: persistare training_runs
================================================================================
Module: learning_core/storage.py

Abstractizează UNDE se scriu rezultatele de antrenare, ca Training Runner să
nu depindă de detaliu. Scrie ÎNTOTDEAUNA local (fișier JSON per rulare, exact
tiparul deja folosit de oracle_engine.py pentru PREDICTIONS_DIR) — rezistent
la absența Supabase, exact tiparul deja aplicat în cache_manager/key_manager.

[ADAUGAT — ADR-015] Migrarea database/migrations/002_learning_core.sql a fost
aplicată — scrie acum și în tabela `training_runs` din Supabase, best-effort
(eșecul scrierii remote nu întrerupe scrierea locală, care rămâne sursa
garantată). Interfața consumată de Training Runner rămâne neschimbată.
================================================================================
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from learning_core.model_registry import TrainingRunResult

logger = logging.getLogger("FootballOracle.LearningCore.Storage")

STORAGE_DIR = Path(__file__).parent / "data" / "training_runs"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


def save_training_run(
    result: TrainingRunResult,
    *,
    algorithm_name: str,
    algorithm_version: str,
    league_scope: str,
) -> Path:
    """Persistă local un training_run — un fișier JSON per rulare, numit
    după training_run_id — și, best-effort, în Supabase (`training_runs`).
    Întoarce calea fișierului local scris (garantată, indiferent de Supabase).

    [ADAUGAT — audit final ADR-051/052] Idempotent pe training_run_id: dacă
    fișierul local există deja, întoarce calea fără să rescrie/reîncerce
    scrierea remote — necesar de când XGBoostV1Algorithm.fit() refolosește
    training_run_id-ul deja persistat intern de MLPredictorEngine.train()
    (ml_predictor._record_training_run()), ca training_runner.run_training()
    să nu mai producă un al doilea INSERT pe același training_run_id
    (constraint UNIQUE, migrația 002) — ar fi eșuat oricum remote (prins,
    logat), dar rândul local mai complet (are brier_score) ar fi fost
    suprascris de unul mai sărac. Pentru orice alt apelant, care nu a
    persistat deja acest id, comportamentul rămâne neschimbat."""
    safe_id = result.training_run_id.replace("/", "_")
    path = STORAGE_DIR / f"{safe_id}.json"
    if path.exists():
        logger.debug("[LearningCore] training_run_id %s deja persistat — scriere idempotentă, sărită.",
                      result.training_run_id)
        return path

    row = {
        "training_run_id": result.training_run_id,
        "algorithm_name": algorithm_name,
        "algorithm_version": algorithm_version,
        "league_scope": league_scope,
        "status": result.status,
        "samples_used": result.samples_used,
        "walk_forward_metrics": result.walk_forward_metrics,
        "message": result.message,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")

    try:
        import supabase_client as sb
        sb.save_training_run(
            training_run_id=result.training_run_id,
            algorithm_name=algorithm_name,
            algorithm_version=algorithm_version,
            league_scope=league_scope,
            status=result.status,
            samples_used=result.samples_used,
            walk_forward_metrics=result.walk_forward_metrics,
            message=result.message,
        )
    except Exception as exc:
        logger.warning("[LearningCore] scriere remote training_runs eșuată "
                        "(rândul local rămâne sursa garantată): %s", exc)

    return path


def list_training_runs() -> list[dict]:
    """Citește toate rulările persistate local, cele mai recente primele."""
    rows = []
    for f in STORAGE_DIR.glob("*.json"):
        try:
            rows.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows
