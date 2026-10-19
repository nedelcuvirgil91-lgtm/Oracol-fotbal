"""
================================================================================
FOOTBALL ORACLE — Flashscore Team Identity Capture Config (ADR-078, Faza 0)
================================================================================
Module: flashscore_team_identity_config.py

Flag dedicat pentru CAPTAREA identitatii de echipa a lui Flashscore
(`/team/<slug>/<id>/`) — implicit False (North Star #3: niciun flag nou
porneste implicit activ). Tipar identic `flashscore_kickoff_correction_config.
py`, responsabilitate separata.

Faza 0 doar OBSERVA: `id`-ul nu e citit nicaieri ca identitate, nu intra in
`match_history`, nu atinge nicio predictie. Scopul lui unic e harta
`id -> nume afisate`, din care „un id cu doua nume" devine o interogare in loc
de o descoperire intamplatoare.
================================================================================
"""
from __future__ import annotations

import supabase_client as sb

_DEFAULT_CONFIG = {"flashscore_team_identity_capture_enabled": False}


def is_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("flashscore_team_identity_capture_enabled", False))
