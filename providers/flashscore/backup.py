"""
================================================================================
FOOTBALL ORACLE — Flashscore Foundation Data Layer Backup (Faza 2)
================================================================================
Module: providers/flashscore/backup.py

Implementarea REALĂ a pasului "Backup" din fluxul oficial documentat în
`season_cleanup.py` (Discovery -> Validation -> Cleanup Report -> Backup
-> Delete -> Integrity Check -> Final Report) — ADR-044 Addendum A6 lăsase
explicit acest pas neimplementat ("activabil ulterior printr-un flag
dedicat"); acesta e acel flag/activare, cerută explicit acum.

Scope IDENTIC cu Season Cleanup (`FOUNDATION_DATA_LAYER_SEASON_TABLES`) —
EXCLUSIV cele 6 tabele Foundation Data Layer, NICIODATĂ `match_history`/
`match_events`/`player_match_stats` de bază (istoric ML) și NICIODATĂ
`odds_history` (document Frozen, ADR-005/006/010).

STRICT READ-ONLY față de Supabase — doar `.select("*")`, nicio scriere,
niciun `DELETE`. Backup-ul e un export JSON pe disc (artefact CI,
`actions/upload-artifact`, deja tiparul folosit de celelalte workflow-uri
din acest repo) — nu o tabelă Supabase nouă (ar necesita migrație +
confirmare explicită, skill `supabase-safety`, pentru un beneficiu marginal
față de un artefact CI, deja retenționat separat, deja auditabil în
istoricul rulărilor GitHub Actions).

Idempotent prin natura operației (export, niciodată scriere) — rulat de
N ori, produce N fișiere distincte (timestamp în nume), niciodată
suprascriere silențioasă a unui backup anterior.
================================================================================
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from providers.flashscore.season_cleanup import FOUNDATION_DATA_LAYER_SEASON_TABLES

logger = logging.getLogger("FootballOracle.Flashscore.Backup")

DEFAULT_BACKUP_DIR = Path(__file__).parent.parent.parent / "backups"


def build_backup_snapshot() -> dict[str, Any]:
    """Citește TOATE rândurile din cele 6 tabele Foundation Data Layer
    (scope identic cu Season Cleanup) — STRICT read-only. Un tabel a
    cărui interogare eșuează e raportat separat (`tables_failed`),
    niciodată tratat ca "gol" (Regula #8 — nicio stare necunoscută nu se
    aproximează)."""
    from database.queries import get_client

    snapshot: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": list(FOUNDATION_DATA_LAYER_SEASON_TABLES),
        "tables": {},
        "row_counts": {},
        "tables_failed": [],
    }

    client = get_client()
    if client is None:
        snapshot["error"] = "supabase_unavailable"
        return snapshot

    for table in FOUNDATION_DATA_LAYER_SEASON_TABLES:
        try:
            res = client.table(table).select("*").execute()
            rows = res.data or []
        except Exception as exc:
            logger.warning("[Backup] %s: interogare eșuată, exclus din backup: %s", table, exc)
            snapshot["tables_failed"].append(table)
            continue
        snapshot["tables"][table] = rows
        snapshot["row_counts"][table] = len(rows)

    return snapshot


def write_backup_file(snapshot: dict[str, Any], out_dir: Path = DEFAULT_BACKUP_DIR) -> Path:
    """Scrie snapshot-ul ca JSON pe disc, cu timestamp în nume (niciodată
    suprascriere) — pregătit pentru upload ca artefact CI
    (`actions/upload-artifact`, retention separat de log-urile de sync)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Microsecunde in timestamp - precizia de secunda ar putea coincide la
    # doua rulari foarte apropiate (ex. teste, retry manual rapid),
    # producand o suprascriere silentioasa a unui backup anterior.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out_path = out_dir / f"flashscore_backup_{stamp}.json"
    out_path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return out_path


def run_backup(out_dir: Path = DEFAULT_BACKUP_DIR) -> dict[str, Any]:
    """Punct de intrare unic — construiește snapshot-ul și îl scrie pe
    disc, întoarce un raport (nu doar bool — North Star #9, trasabilitate
    completă)."""
    snapshot = build_backup_snapshot()
    if snapshot.get("error"):
        return {"ok": False, "error": snapshot["error"]}
    path = write_backup_file(snapshot, out_dir=out_dir)
    return {
        "ok": True,
        "path": str(path),
        "row_counts": snapshot["row_counts"],
        "tables_failed": snapshot["tables_failed"],
    }
