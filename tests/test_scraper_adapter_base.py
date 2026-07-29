"""Teste pentru scraper_adapter_base.py (UDAL Faza 0, ADR-042) — fără rețea."""
from __future__ import annotations

from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from acquisition_tier import AcquisitionTier
from provider_capabilities import DataType
from scraper_adapter_base import ScraperAdapterBase, ScraperPreflightError
from scraper_registry import ScraperCapability
from sync_adapter import SyncAdapter


class _FakeScraperAdapter(ScraperAdapterBase):
    scraper_id = "pilot"
    tier = AcquisitionTier.HTTP_SCRAPER
    provider_id = "pilot"  # mostenit din SyncAdapter, cerut de contract

    def fetch(self, params):
        return {"ok": True}

    def normalize(self, raw_payload):
        return [raw_payload]

    def validate(self, records):
        return records

    def persist(self, records):
        return True


def test_scraper_adapter_base_is_a_sync_adapter():
    assert issubclass(ScraperAdapterBase, SyncAdapter)


def test_fetch_remains_abstract_in_phase_0():
    """[UDAL Faza 0] fetch() ramane abstracta - o subclasa care nu o
    implementeaza nu poate fi instantiata."""
    class _Incomplete(ScraperAdapterBase):
        scraper_id = "incomplete"
        tier = AcquisitionTier.HTTP_SCRAPER
        provider_id = "incomplete"

        def normalize(self, raw_payload):
            return []

        def validate(self, records):
            return records

        def persist(self, records):
            return True

    with pytest.raises(TypeError):
        _Incomplete()  # type: ignore[abstract]


def test_preflight_raises_when_scraper_not_registered():
    adapter = _FakeScraperAdapter()
    with pytest.raises(ScraperPreflightError):
        adapter.preflight()


def test_preflight_raises_when_tos_not_reviewed(monkeypatch):
    fake_cap = ScraperCapability(
        scraper_id="pilot", version=1, tier=AcquisitionTier.HTTP_SCRAPER,
        data_types=frozenset({DataType.STATISTICS}),
        target_url_template="https://example.com/{league}",
        selector_map_ref="pilot-v1", politeness_policy_ref="pilot-politeness",
        tos_reviewed=False, tos_reviewed_by=None, tos_reviewed_at=None,
    )
    monkeypatch.setattr("scraper_registry.SCRAPERS", MappingProxyType({"pilot": fake_cap}))
    adapter = _FakeScraperAdapter()
    with pytest.raises(ScraperPreflightError):
        adapter.preflight()


def test_preflight_passes_when_tos_reviewed(monkeypatch):
    fake_cap = ScraperCapability(
        scraper_id="pilot", version=1, tier=AcquisitionTier.HTTP_SCRAPER,
        data_types=frozenset({DataType.STATISTICS}),
        target_url_template="https://example.com/{league}",
        selector_map_ref="pilot-v1", politeness_policy_ref="pilot-politeness",
        tos_reviewed=True, tos_reviewed_by="product-owner",
        tos_reviewed_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr("scraper_registry.SCRAPERS", MappingProxyType({"pilot": fake_cap}))
    adapter = _FakeScraperAdapter()
    adapter.preflight()  # nu aruncă
