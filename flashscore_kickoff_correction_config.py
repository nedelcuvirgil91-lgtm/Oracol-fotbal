"""
================================================================================
FOOTBALL ORACLE — Flashscore Kickoff Correction Config (ADR-070)
================================================================================
Module: flashscore_kickoff_correction_config.py

Flag dedicat pentru corectarea `match_history.kickoff_date`/`league` pe un
rând deja scris, când `pre_match_odds.py` (rulat de 2x/zi, ADR-043) descoperă
o dată diferită de cea înregistrată — implicit False (North Star #3: niciun
flag nou pornește implicit activ). Tipar identic
`flashscore_odds_fallback_config.py`, responsabilitate separată — acela
populează cote SERVITE, acesta corectează identitatea (data) unui rând deja
canonic, prin RPC-ul deja existent (migrarea 048), niciodată o cale nouă de
scriere.
================================================================================
"""
from __future__ import annotations

import supabase_client as sb

_DEFAULT_CONFIG = {"flashscore_kickoff_correction_enabled": False}


def is_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("flashscore_kickoff_correction_enabled", False))
