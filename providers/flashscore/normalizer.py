"""
================================================================================
FOOTBALL ORACLE — Flashscore Normalizer (R-Sync-FLASH-01, ADR-042)
================================================================================
Module: providers/flashscore/normalizer.py

Schelet — mapează recordurile extrase (via `extractor.py` + `udal_extraction.
extract()`) la forma canonică pe care `upsert_match_canonical` / tabelele
noi `player_match_stats` / `match_events` o așteaptă (vezi
`docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md`, §3).

Neimplementat deliberat (`NotImplementedError`) — nicio logică reală de
mapare până nu există `fetch()` funcțional (Faza 4, ADR-042 §16.2) și
migrarea Supabase propusă în §3 nu e aprobată/aplicată.
================================================================================
"""
from __future__ import annotations

from typing import Any


def normalize_match_statistics(raw_record: dict) -> dict:
    """[Schelet] -> forma acceptată de `upsert_match_canonical` (subset
    COALESCE-safe: home/away_possession, shots, corners, fouls, cards,
    offsides, referee, stadium, home/away_lineup — vezi migrația 026)."""
    raise NotImplementedError(
        "R-Sync-FLASH-01: design-only. Implementare reală după aprobarea "
        "migrării Supabase (§3) și a fetch()-ului Playwright (Faza 4)."
    )


def normalize_player_match_stats(raw_record: dict) -> list[dict]:
    """[Schelet] -> rânduri `player_match_stats` (§3.2 din design)."""
    raise NotImplementedError(
        "R-Sync-FLASH-01: design-only. Vezi docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md."
    )


def normalize_match_events(raw_record: dict) -> list[dict]:
    """[Schelet] -> rânduri `match_events` (§3.3 din design)."""
    raise NotImplementedError(
        "R-Sync-FLASH-01: design-only. Vezi docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md."
    )


def normalize_upcoming_match(raw_record: dict) -> dict[str, Any]:
    """[Schelet] -> `upcoming_matches`/`upcoming_lineups`/`upcoming_match_features`
    (§3.5 din design) — Pre-Match Sync, niciodată `match_history`."""
    raise NotImplementedError(
        "R-Sync-FLASH-01: design-only. Vezi docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md."
    )
