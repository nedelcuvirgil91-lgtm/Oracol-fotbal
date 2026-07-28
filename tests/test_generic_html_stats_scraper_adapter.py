"""Teste pentru generic_html_stats_scraper_adapter.py (UDAL Faza 1, ADR-042)
— fără rețea, fixture HTML local."""
from __future__ import annotations

from pathlib import Path

import pytest

from generic_html_stats_scraper_adapter import (
    GenericHtmlStatsScraperAdapter, LiveFetchNotAllowedError,
)

REPO_ROOT = Path(__file__).parent.parent
REAL_FIXTURE = REPO_ROOT / "docs" / "06_UDAL" / "fixtures" / "pilot_match_statistics.html"

_SELECTOR_MAP = {
    "row_selector": "table.match-stats tbody tr",
    "fields": {
        "home_team": "td.home-team", "away_team": "td.away-team",
        "kickoff_date": "td.date",
        "home_corners": "td.home-corners", "away_corners": "td.away-corners",
        "home_cards": "td.home-cards", "away_cards": "td.away-cards",
        "home_fouls": "td.home-fouls", "away_fouls": "td.away-fouls",
    },
}

_MINI_HTML = """
<table class="match-stats"><tbody>
<tr>
  <td class="home-team">Test Home</td><td class="away-team">Test Away</td>
  <td class="date">2026-01-01</td>
  <td class="home-corners">5</td><td class="away-corners">3</td>
  <td class="home-cards">1</td><td class="away-cards">2</td>
  <td class="home-fouls">9</td><td class="away-fouls">7</td>
</tr>
</tbody></table>
"""


def _adapter():
    return GenericHtmlStatsScraperAdapter("test-scraper", _SELECTOR_MAP)


def test_fetch_rejects_non_fixture_mode():
    adapter = _adapter()
    with pytest.raises(LiveFetchNotAllowedError):
        adapter.fetch({"mode": "live", "url": "https://example.com"})


def test_fetch_rejects_missing_mode():
    adapter = _adapter()
    with pytest.raises(LiveFetchNotAllowedError):
        adapter.fetch({"fixture_path": "irrelevant"})


def test_fetch_reads_fixture_file(tmp_path):
    fixture_file = tmp_path / "test.html"
    fixture_file.write_text(_MINI_HTML, encoding="utf-8")
    adapter = _adapter()
    raw = adapter.fetch({"mode": "fixture", "fixture_path": str(fixture_file)})
    assert "Test Home" in raw


def test_normalize_extracts_fields_per_selector_map():
    adapter = _adapter()
    records = adapter.normalize(_MINI_HTML)
    assert len(records) == 1
    assert records[0]["home_team"] == "Test Home"
    assert records[0]["away_team"] == "Test Away"
    assert records[0]["home_corners"] == "5"  # text brut, inainte de validare/conversie numerica


def test_normalize_empty_payload_returns_empty_list():
    adapter = _adapter()
    assert adapter.normalize(None) == []
    assert adapter.normalize("") == []


def test_normalize_missing_field_becomes_none():
    html = """
    <table class="match-stats"><tbody>
    <tr><td class="home-team">A</td><td class="away-team">B</td>
    <td class="date">2026-01-01</td><td class="home-corners">2</td></tr>
    </tbody></table>
    """
    adapter = _adapter()
    records = adapter.normalize(html)
    assert records[0]["away_corners"] is None


def test_validate_returns_validation_result_with_provenance():
    adapter = _adapter()
    records = adapter.normalize(_MINI_HTML)
    result = adapter.validate(records)
    assert len(result.valid) == 1
    assert result.valid[0]["_provenance"]["source_id"] == "test-scraper"
    assert result.valid[0]["_provenance"]["source_tier"] == "http_scraper"


def test_persist_is_a_noop_returning_true():
    adapter = _adapter()
    assert adapter.persist([{"anything": "here"}]) is True


def test_end_to_end_against_real_pilot_fixture():
    """Integrare: fixture-ul real al pilotului (6 randuri brute, 3 valide,
    3 respinse - vezi comentariile din fixture) - regresie directa daca
    fixture-ul sau logica de validare se schimba fara sa se actualizeze
    impreuna."""
    adapter = _adapter()
    raw = adapter.fetch({"mode": "fixture", "fixture_path": str(REAL_FIXTURE)})
    records = adapter.normalize(raw)
    assert len(records) == 6

    result = adapter.validate(records)
    assert len(result.valid) == 3
    assert len(result.rejected) == 3
    reasons = {r.reason for r in result.rejected}
    assert any(r.startswith("negative_value") for r in reasons)
    assert any(r.startswith("missing_required_fields") for r in reasons)
    assert "duplicate_natural_key_in_batch" in reasons
