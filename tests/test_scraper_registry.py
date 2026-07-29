"""Teste pentru scraper_registry.py (UDAL Faza 0, ADR-042) — fără rețea."""
from __future__ import annotations

from types import MappingProxyType

import pytest

from acquisition_tier import AcquisitionTier
from provider_capabilities import DataType
from scraper_registry import (
    SCRAPERS, ScraperCapability, get_capability, is_runnable, supports,
)


def test_scrapers_registry_has_exactly_known_entries():
    """Regresie directa: nicio sursa noua nu se adauga tacit, in afara
    setului explicit aprobat pana acum - pilotul generic (Faza 1) si
    Flashscore (R-Sync-FLASH-01, design-only, tos_reviewed=False)."""
    assert set(SCRAPERS.keys()) == {
        "udal_pilot_generic_html_stats",
        "flashscore_match_enrichment",
    }


def test_flashscore_scraper_tos_not_reviewed():
    """[R-Sync-FLASH-01] Regresie critica - design-only, ramane
    tos_reviewed=False pana la un POC live dedicat + aprobare separata."""
    cap = get_capability("flashscore_match_enrichment")
    assert cap.tos_reviewed is False
    assert cap.tos_reviewed_by is None
    assert cap.tos_reviewed_at is None


def test_flashscore_scraper_is_not_runnable_yet():
    assert is_runnable("flashscore_match_enrichment") is False


def test_pilot_scraper_tos_not_reviewed():
    """[UDAL Faza 1] Regresie critica - pilotul ramane tos_reviewed=False
    pana la POC_SCRAPER_SOURCE_01 + aprobare separata."""
    cap = get_capability("udal_pilot_generic_html_stats")
    assert cap.tos_reviewed is False
    assert cap.tos_reviewed_by is None
    assert cap.tos_reviewed_at is None


def test_pilot_scraper_is_not_runnable_yet():
    """Consecinta directa a tos_reviewed=False - is_runnable() trebuie sa
    ramana False pentru pilot, chiar daca e inregistrat."""
    assert is_runnable("udal_pilot_generic_html_stats") is False


def test_scrapers_is_immutable_mapping():
    assert isinstance(SCRAPERS, MappingProxyType)
    with pytest.raises(TypeError):
        SCRAPERS["noua_intrare"] = None  # type: ignore[index]


def test_scraper_capability_rejects_api_tier():
    """Un ScraperCapability cu tier=API n-are ce cauta aici - apartine
    exclusiv provider_capabilities.py."""
    with pytest.raises(ValueError):
        ScraperCapability(
            scraper_id="test", version=1, tier=AcquisitionTier.API,
            data_types=frozenset({DataType.STATISTICS}),
            target_url_template="https://example.com/{league}",
            selector_map_ref="test-v1", politeness_policy_ref="test-politeness",
            tos_reviewed=False, tos_reviewed_by=None, tos_reviewed_at=None,
        )


def test_scraper_capability_accepts_http_scraper_tier():
    cap = ScraperCapability(
        scraper_id="test", version=1, tier=AcquisitionTier.HTTP_SCRAPER,
        data_types=frozenset({DataType.STATISTICS}),
        target_url_template="https://example.com/{league}/{season}",
        selector_map_ref="test-v1", politeness_policy_ref="test-politeness",
        tos_reviewed=False, tos_reviewed_by=None, tos_reviewed_at=None,
    )
    assert cap.tier is AcquisitionTier.HTTP_SCRAPER
    assert cap.data_types == frozenset({DataType.STATISTICS})


def test_get_capability_returns_none_for_unknown_scraper():
    assert get_capability("nu-exista-inca") is None


def test_supports_false_for_unknown_scraper():
    assert supports("nu-exista-inca", DataType.STATISTICS) is False


def test_is_runnable_false_for_unknown_scraper():
    """Fail-closed, nu fail-open - diferit deliberat de
    key_manager.is_available() (care e fail-open la nivel de cota, nu de
    aprobare legala)."""
    assert is_runnable("nu-exista-inca") is False


def test_is_runnable_false_when_tos_not_reviewed(monkeypatch):
    fake_cap = ScraperCapability(
        scraper_id="pilot", version=1, tier=AcquisitionTier.HTTP_SCRAPER,
        data_types=frozenset({DataType.STATISTICS}),
        target_url_template="https://example.com/{league}",
        selector_map_ref="pilot-v1", politeness_policy_ref="pilot-politeness",
        tos_reviewed=False, tos_reviewed_by=None, tos_reviewed_at=None,
    )
    monkeypatch.setattr(
        "scraper_registry.SCRAPERS", MappingProxyType({"pilot": fake_cap})
    )
    assert is_runnable("pilot") is False


def test_is_runnable_true_when_tos_reviewed(monkeypatch):
    from datetime import datetime, timezone
    fake_cap = ScraperCapability(
        scraper_id="pilot", version=1, tier=AcquisitionTier.HTTP_SCRAPER,
        data_types=frozenset({DataType.STATISTICS}),
        target_url_template="https://example.com/{league}",
        selector_map_ref="pilot-v1", politeness_policy_ref="pilot-politeness",
        tos_reviewed=True, tos_reviewed_by="product-owner",
        tos_reviewed_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "scraper_registry.SCRAPERS", MappingProxyType({"pilot": fake_cap})
    )
    assert is_runnable("pilot") is True
