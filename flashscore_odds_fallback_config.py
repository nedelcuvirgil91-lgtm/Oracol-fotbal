"""
================================================================================
FOOTBALL ORACLE — Flashscore Odds Fallback Config (ADR-043)
================================================================================
Module: flashscore_odds_fallback_config.py

Flag dedicat pentru citirea `odds_fallback_flashscore` ca sursă secundară
de cote pentru Predictor (ADR-043 §Decizie pct. 3) — implicit False (North
Star #3: niciun flag nou pornește implicit activ). Deliberat NEreutilizat
`shadow_config.py`/`scheduled_fixtures_shadow_config.py` — acelea sunt
strict observaționale (nu modifică niciodată `matches`), acesta chiar
populează cote SERVITE Predictorului dacă activat. Responsabilitate
separată, rollback trivial (un singur boolean), independent de orice alt
flag existent.
================================================================================
"""
from __future__ import annotations

import supabase_client as sb

_DEFAULT_CONFIG = {"flashscore_odds_fallback_enabled": False}


def is_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("flashscore_odds_fallback_enabled", False))
