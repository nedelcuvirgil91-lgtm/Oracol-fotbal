"""Teste pentru providers/flashscore/adapter.py (Foundation Data Layer,
ADR-044) — fara retea.

[ACTUALIZAT 2026-07-29] `tos_reviewed=True` pentru `flashscore_match_
enrichment` (scraper_registry.py) — aprobare explicita, separata, a
proprietarului produsului ("DA. Activeaza acum."), pentru primul test
live controlat. Gate-ul `preflight()` ramane mecanismul neschimbat
(scraper_adapter_base.py) - doar starea `tos_reviewed` s-a schimbat, nu
codul care o verifica."""
from __future__ import annotations

import pytest

from providers.flashscore.adapter import (
    FLASH_PROVIDER_CAPABILITIES,
    FlashscoreAdapter,
    _build_match_ref,
)
from providers.flashscore.normalizer import normalize_upcoming_match


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


def test_flashscore_adapter_preflight_passes_after_tos_review():
    """[ADR-044, 2026-07-29] tos_reviewed=True in scraper_registry.py -
    aprobare explicita, separata, a proprietarului produsului. Cel mai
    important test din acest fisier - trebuie sa ramana verde doar cat
    timp aceasta aprobare ramane valabila; daca tos_reviewed redevine
    False fara o decizie explicita, acest test trebuie sa pice."""
    adapter = FlashscoreAdapter()
    assert adapter.preflight() is None


def test_flashscore_adapter_fetch_requires_match_identity():
    adapter = FlashscoreAdapter()
    with pytest.raises(ValueError):
        adapter.fetch({})
    with pytest.raises(ValueError):
        adapter.fetch({"match_base_url": "https://www.flashscore.com/match/football/x/y"})


def test_flashscore_adapter_normalize_wraps_pages_as_single_record():
    adapter = FlashscoreAdapter()
    pages = {"summary": "<html></html>"}
    assert adapter.normalize(pages) == [pages]
    assert adapter.normalize(None) == []
    assert adapter.normalize({}) == []


def test_flashscore_adapter_validate_uses_real_fixture(monkeypatch):
    """validate() ruleaza normalize_match_statistics() + validate_flat_identity()
    pe date reale (fixture-ul complet, 7 tab-uri) - randul valid trece,
    pastreaza pagina originala sub '_pages' pentru persist()."""
    from pathlib import Path
    fixture_dir = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_full_tabs_poc"
    pages = {f.stem: f.read_text(encoding="utf-8") for f in fixture_dir.glob("*.html")}

    adapter = FlashscoreAdapter()
    valid = adapter.validate([pages])
    assert len(valid) == 1
    assert valid[0]["home_team"] == "Dinamo Bucuresti"
    assert valid[0]["_pages"] == pages


def test_flashscore_adapter_validate_rejects_record_without_natural_key():
    adapter = FlashscoreAdapter()
    assert adapter.validate([{}]) == []


def test_flashscore_adapter_persist_calls_data_trust_layer(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "providers.flashscore.adapter.persist_match_with_data_trust_layer",
        lambda pages, match_ref, **kw: calls.append((match_ref, pages)) or {"ok": True},
    )
    adapter = FlashscoreAdapter()
    record = {"home_team": "A", "away_team": "B", "kickoff_date": "2026-08-01T18:00:00", "_pages": {"summary": "x"}}
    assert adapter.persist([record]) is True
    assert calls == [("a__b__2026-08-01", {"summary": "x"})]


def test_flashscore_adapter_persist_empty_records_returns_true():
    assert FlashscoreAdapter().persist([]) is True


def test_flashscore_adapter_persist_returns_false_on_partial_failure(monkeypatch):
    monkeypatch.setattr(
        "providers.flashscore.adapter.persist_match_with_data_trust_layer",
        lambda pages, match_ref, **kw: {"ok": False},
    )
    adapter = FlashscoreAdapter()
    record = {"home_team": "A", "away_team": "B", "kickoff_date": "2026-08-01", "_pages": {"summary": "x"}}
    assert adapter.persist([record]) is False


def test_build_match_ref_stable_and_slugified():
    assert _build_match_ref("Dinamo Bucuresti", "Univ. Craiova", "2026-07-25T17:30:00") == \
        "dinamo-bucuresti__univ-craiova__2026-07-25"
    assert _build_match_ref(None, None, None) == "unknown__unknown__unknown"


def test_normalize_upcoming_match_empty_without_summary_tab():
    """[Implementat — flux Pre-Match Odds, providers/flashscore/pre_match_odds.py]
    Fara tab-ul "summary", functia ramane pura si nu aproximeaza nimic."""
    assert normalize_upcoming_match({}) == {}
    assert normalize_upcoming_match({"odds": "<html></html>"}) == {}
