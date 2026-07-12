"""
================================================================================
FOOTBALL ORACLE — Learning Core: persistare training_runs (v0.1, locală)
================================================================================
Module: learning_core/storage.py

Abstractizează UNDE se scriu rezultatele de antrenare, ca Training Runner să
nu depindă de detaliu. La v0.1 — migrarea database/migrations/002_learning_core.sql
încă neaplicată pe Supabase — scrie local, un fișier JSON per rulare, exact
tiparul deja folosit de oracle_engine.py pentru PREDICTIONS_DIR.

Când migrarea va fi aplicată pe Supabase, save_training_run() se extinde să
scrie și în tabela training_runs — fără să schimbe interfața consumată de
Training Runner (aceeași disciplină "adaptor înlocuibil" ca restul Learning Core).
================================================================================
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from learning_core.model_registry import TrainingRunResult

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
    după training_run_id. Întoarce calea fișierului scris."""
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
    safe_id = result.training_run_id.replace("/", "_")
    path = STORAGE_DIR / f"{safe_id}.json"
    path.write_text(json.dumps(row, indent=2, ensure_ascii=False), encoding="utf-8")
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
