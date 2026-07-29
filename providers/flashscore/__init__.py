"""
================================================================================
FOOTBALL ORACLE — Provider Flashscore (Foundation Data Layer, ADR-044)
================================================================================
Flashscore e provider AUXILIAR (Tier 2, Playwright) — completează DOAR
câmpurile lipsă din `match_history`/`player_match_stats`/`match_events`
după ce API Providers și Open Data (prioritățile 1 și 2, ADR-042) au fost
deja interogate.

[ACTUALIZAT 2026-07-29] `tos_reviewed=True` (`scraper_registry.py`) —
aprobare explicită, separată, a proprietarului produsului, pentru primul
test live controlat. `adapter.py` (fetch/normalize/validate/persist),
`discovery.py` (M1, listă de meciuri per competiție urmărită) și
`persistence.py` (Data Trust Layer) au implementare reală, testată
structural — vezi `docs/00_GOVERNANCE/ADR-044-flashscore-foundation-data-layer.md`.
================================================================================
"""
