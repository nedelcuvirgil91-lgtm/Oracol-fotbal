"""Teste pentru generic_rich_match_scraper_adapter.py (UDAL Faza 1.5,
ADR-042) — fără rețea, fixture-uri locale."""
from __future__ import annotations

import json

import pytest

from generic_rich_match_scraper_adapter import (
    GenericJsonMatchScraperAdapter, GenericPlaywrightMatchScraperAdapter,
    GenericRichMatchScraperAdapter, LiveFetchNotAllowedError,
    PlaywrightNotImplementedError,
)

_HTML = """
<div class="match"><span class="home">Echipa A</span><span class="away">Echipa B</span></div>
"""
_MAP = {"teams": {"home_team": ".home", "away_team": ".away"}}

_JSON_PAYLOAD = {"teams": {"home": "Echipa A", "away": "Echipa B"}}
_JSON_MAP = {"teams": {"home_team": "teams.home", "away_team": "teams.away"}}


def test_html_adapter_rejects_non_fixture_mode():
    adapter = GenericRichMatchScraperAdapter("test", _MAP)
    with pytest.raises(LiveFetchNotAllowedError):
        adapter.fetch({"mode": "live"})


def test_html_adapter_fetch_normalize_validate(tmp_path):
    f = tmp_path / "m.html"
    f.write_text(_HTML, encoding="utf-8")
    adapter = GenericRichMatchScraperAdapter("test", _MAP)
    raw = adapter.fetch({"mode": "fixture", "fixture_path": str(f)})
    records = adapter.normalize(raw)
    assert records == [{"teams": {"home_team": "Echipa A", "away_team": "Echipa B"}}]
    result = adapter.validate(records)
    assert len(result.valid) == 1
    assert result.valid[0]["_provenance"]["source_tier"] == "http_scraper"


def test_html_adapter_persist_is_noop():
    adapter = GenericRichMatchScraperAdapter("test", _MAP)
    assert adapter.persist([{"anything": 1}]) is True


def test_json_adapter_fetch_normalize_validate(tmp_path):
    f = tmp_path / "m.json"
    f.write_text(json.dumps(_JSON_PAYLOAD), encoding="utf-8")
    adapter = GenericJsonMatchScraperAdapter("test", _JSON_MAP)
    raw = adapter.fetch({"mode": "fixture", "fixture_path": str(f)})
    records = adapter.normalize(raw)
    assert records == [{"teams": {"home_team": "Echipa A", "away_team": "Echipa B"}}]
    result = adapter.validate(records)
    assert len(result.valid) == 1


def test_json_adapter_rejects_non_fixture_mode():
    adapter = GenericJsonMatchScraperAdapter("test", _JSON_MAP)
    with pytest.raises(LiveFetchNotAllowedError):
        adapter.fetch({"mode": "live"})


def test_playwright_adapter_fetch_always_raises():
    adapter = GenericPlaywrightMatchScraperAdapter("test", _MAP)
    with pytest.raises(PlaywrightNotImplementedError):
        adapter.fetch({"mode": "fixture", "fixture_path": "irrelevant"})


def test_playwright_adapter_normalize_reuses_same_logic_as_html_adapter():
    """Proba centrala Faza 1.5: normalize() e ACELASI COD (mostenit din
    acelasi mixin), nu doar un rezultat echivalent produs separat."""
    html_adapter = GenericRichMatchScraperAdapter("test-html", _MAP)
    pw_adapter = GenericPlaywrightMatchScraperAdapter("test-pw", _MAP)

    assert type(html_adapter).normalize is type(pw_adapter).normalize

    result_html = html_adapter.normalize(_HTML)
    result_pw = pw_adapter.normalize(_HTML)  # simuleaza DOM post-randare
    assert result_html == result_pw


def test_validate_rejects_missing_team_identity():
    adapter = GenericRichMatchScraperAdapter("test", _MAP)
    records = [{"teams": {"home_team": None, "away_team": "Echipa B"}}]
    result = adapter.validate(records)
    assert len(result.valid) == 0
    assert result.rejected[0].reason == "missing_team_identity"
