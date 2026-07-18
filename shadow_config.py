"""
================================================================================
FOOTBALL ORACLE — Shadow Config (ADR-034, PR5)
================================================================================
Module: shadow_config.py

Flag dedicat pentru Selection Engine shadow mode — implicit False (North
Star #3: niciun flag nou pornește implicit activ, inclusiv unul strict
observațional), independent de orice alt flag existent
(learning_core_enabled, consensus_validation_enabled, challenger_shadow_
logging_enabled etc.) — exact tiparul din
learning_core/consensus_validation.py.
================================================================================
"""
from __future__ import annotations

import supabase_client as sb

_DEFAULT_CONFIG = {"selection_engine_shadow_enabled": False}


def is_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("selection_engine_shadow_enabled", False))
