"""Teste pentru scheletul providers/flashscore/ (R-Sync-FLASH-01) — fara retea.

[ACTUALIZAT M0] normalize_match_statistics/player_match_stats/match_events
au implementare reala acum (vezi test_providers_flashscore_normalizer.py) -
scoase de aici din lista "raise NotImplementedError". adapter.py ramane
schelet (Step 5, neinceput) - fetch()/persist()/preflight() raman blocate,
neschimbat. normalize_upcoming_match ramane afara scope M0, neimplementat."""
from __future__ import annotations

import pytest

from generic_rich_match_scraper_adapter import PlaywrightNotImplementedError
from providers.flashscore.adapter import FLASH_PROVIDER_CAPABILITIES, FlashscoreAdapter
from providers.flashscore.normalizer import normalize_upcoming_match
from scraper_adapter_base import ScraperPreflightError


def test_flashscore_capabilities_match_poc_findings():
    """Fiecare True/False provine direct din UDAL_FLASHSCORE_POC_10MATCHES_REPORT.md
    - regresie: niciun camp neverificat nu devine tacit True."""
    confirmed_true = {
        "possession", "shots", "shots_on_target", "corners", "fouls",
        "yellow_cards", "red_cards", "offsides", "goalkeeper_saves",
        "lineups_starting_xi", "player_ratings", "substitution_events",
        "referee", "attendance", "stadium",
        # [R-Sync-FLASH-01 §10.7, ADR-043 PROPUS] fallback temporar, nu
        # sursa principala - vezi odds_fallback_flashscore in design.
        "odds_snapshot",
    }
    confirmed_false = {
        "xg", "weather", "h2h_history_rows",
        "coach_name", "bench_full_list",
    }
    assert set(FLASH_PROVIDER_CAPABILITIES) == confirmed_true | confirmed_false
    assert all(FLASH_PROVIDER_CAPABILITIES[f] is True for f in confirmed_true)
    assert all(FLASH_PROVIDER_CAPABILITIES[f] is False for f in confirmed_false)


def test_flashscore_adapter_fetch_raises_not_implemented():
    adapter = FlashscoreAdapter()
    with pytest.raises(PlaywrightNotImplementedError):
        adapter.fetch({})


def test_flashscore_adapter_persist_raises_not_implemented():
    adapter = FlashscoreAdapter()
    with pytest.raises(NotImplementedError):
        adapter.persist([])


def test_flashscore_adapter_preflight_blocked_by_tos_gate():
    """Gate independent de fetch() - tos_reviewed=False in scraper_registry.py
    blocheaza inainte ca fetch() sa fie macar apelat."""
    adapter = FlashscoreAdapter()
    with pytest.raises(ScraperPreflightError):
        adapter.preflight()


def test_normalize_upcoming_match_still_out_of_scope():
    """[Afara scope M0] Pre-Match Sync - singura functie normalizer.py
    ramasa neimplementata (celelalte 3 au implementare reala, M0 - vezi
    test_providers_flashscore_normalizer.py)."""
    with pytest.raises(NotImplementedError):
        normalize_upcoming_match({})
