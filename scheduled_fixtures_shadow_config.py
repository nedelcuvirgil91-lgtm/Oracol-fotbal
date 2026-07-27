"""
================================================================================
FOOTBALL ORACLE — Scheduled Fixtures Shadow Config (R-Sync-7b, ADR-039)
================================================================================
Module: scheduled_fixtures_shadow_config.py

Flag dedicat pentru shadow-ul de echivalență scheduled_fixtures vs. calea
live de discovery — implicit False (North Star #3: niciun flag nou pornește
implicit activ). Deliberat NEreutilizat `shadow_config.py`
(selection_engine_shadow_enabled) — responsabilități separate, rollback
trivial pentru fiecare shadow independent, decizie explicită proprietar
produs (§6f, audit R-Sync-7b).
================================================================================
"""
from __future__ import annotations

import supabase_client as sb

_DEFAULT_CONFIG = {"scheduled_fixtures_shadow_enabled": False}


def is_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("scheduled_fixtures_shadow_enabled", False))
