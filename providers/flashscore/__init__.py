"""
================================================================================
FOOTBALL ORACLE — Provider Flashscore (R-Sync-FLASH-01, ADR-042)
================================================================================
Schelet de design — vezi `docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md`.

Flashscore e provider AUXILIAR (Tier 2, Playwright) — completează DOAR
câmpurile lipsă din `match_history`/`player_match_stats`/`match_events`
după ce API Providers și Open Data (prioritățile 1 și 2, ADR-042) au fost
deja interogate. Niciun cod din acest pachet nu rulează live: `fetch()`
rămâne neimplementat (`PlaywrightNotImplementedError`), `tos_reviewed`
rămâne `False` în `scraper_registry.py`.
================================================================================
"""
