"""Teste pentru acquisition_tier.py (UDAL Faza 0, ADR-042) — fără rețea."""
from __future__ import annotations

import pytest

from acquisition_tier import AcquisitionTier, TIER_PRECEDENCE, tier_rank


def test_three_tiers_defined():
    assert {t.value for t in AcquisitionTier} == {"api", "http_scraper", "playwright"}


def test_precedence_order_is_api_then_scraper_then_playwright():
    assert TIER_PRECEDENCE == (
        AcquisitionTier.API, AcquisitionTier.HTTP_SCRAPER, AcquisitionTier.PLAYWRIGHT,
    )


def test_tier_rank_api_is_lowest():
    assert tier_rank(AcquisitionTier.API) == 0


def test_tier_rank_strictly_increasing_with_precedence():
    ranks = [tier_rank(t) for t in TIER_PRECEDENCE]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


def test_tier_rank_raises_for_non_member():
    with pytest.raises(ValueError):
        tier_rank("not-a-real-tier")  # type: ignore[arg-type]
