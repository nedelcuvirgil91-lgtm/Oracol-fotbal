"""Teste pentru scheletul providers/flashscore/ (R-Sync-FLASH-01, design-only) — fara retea.

Garanteaza ca niciun cod din acest pachet nu poate porni o operatie reala:
fetch()/persist() raman NotImplementedError, preflight() ramane blocat de
tos_reviewed=False (scraper_registry), independent de fetch()."""
from __future__ import annotations

import pytest

from generic_rich_match_scraper_adapter import PlaywrightNotImplementedError
from providers.flashscore.adapter import FLASH_PROVIDER_CAPABILITIES, FlashscoreAdapter
from providers.flashscore.normalizer import (
    normalize_match_events, normalize_match_statistics,
    normalize_player_match_stats, normalize_upcoming_match,
)
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


@pytest.mark.parametrize(
    "fn",
    [normalize_match_statistics, normalize_player_match_stats,
     normalize_match_events, normalize_upcoming_match],
)
def test_flashscore_normalizer_functions_raise_not_implemented(fn):
    with pytest.raises(NotImplementedError):
        fn({})
