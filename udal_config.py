"""
================================================================================
FOOTBALL ORACLE — UDAL Config (Universal Data Acquisition Layer, Faza 0, ADR-042)
================================================================================
Module: udal_config.py

Flag-uri dedicate UDAL — toate implicit `False` (North Star #3: niciun flag
nou nu pornește implicit activ), exact tiparul deja folosit de
`scheduled_fixtures_shadow_config.py`/`shadow_config.py`. Un singur modul,
nu unul per flag — UDAL are nevoie de mai multe control-uri granulare
corelate (master + per-tier + per-mod + per-sursă), separarea în module
individuale ar fragmenta inutil ceva ce se citește/gestionează împreună.

[UDAL Faza 0] Niciun cod de producție nu citește încă aceste flag-uri —
Faza 0 doar le înregistrează, cu implicit `False` peste tot (excepție
documentată: `udal_shadow_mode_enabled`, implicit `True` DOAR relativ la
`udal_enabled` — dacă master-ul e oprit, shadow mode nu are efect oricum).
================================================================================
"""
from __future__ import annotations

import supabase_client as sb

_DEFAULT_CONFIG = {
    "udal_enabled": False,
    "udal_tier_http_scraper_enabled": False,
    "udal_tier_playwright_enabled": False,
    "udal_historical_backfill_enabled": False,
    "udal_live_acquisition_enabled": False,
    # Implicit True (nu False) — orice sursă nouă rulează în shadow înainte
    # de scriere live, siguranță implicită, nu opțională (UDAL_ARCHITECTURE_SPEC
    # v1.0, §13). Relevant DOAR când udal_enabled=True.
    "udal_shadow_mode_enabled": True,
    # Per-sursă — populat dinamic per scraper_id, nu enumerat static aici.
    "udal_source_enabled": {},
}


def is_udal_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("udal_enabled", False))


def is_tier_http_scraper_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("udal_tier_http_scraper_enabled", False))


def is_tier_playwright_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("udal_tier_playwright_enabled", False))


def is_historical_backfill_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("udal_historical_backfill_enabled", False))


def is_live_acquisition_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("udal_live_acquisition_enabled", False))


def is_shadow_mode_enabled() -> bool:
    cfg = sb.load_config(_DEFAULT_CONFIG)
    return bool(cfg.get("udal_shadow_mode_enabled", True))


def is_source_enabled(scraper_id: str) -> bool:
    """Control granular per sursă — implicit False pentru orice
    scraper_id neenumerat explicit (fail-closed, consecvent cu
    `scraper_registry.is_runnable()` — o sursă nouă nu rulează niciodată
    „din greșeală" doar pentru că master-ul e pornit)."""
    cfg = sb.load_config(_DEFAULT_CONFIG)
    per_source = cfg.get("udal_source_enabled", {}) or {}
    return bool(per_source.get(scraper_id, False))
