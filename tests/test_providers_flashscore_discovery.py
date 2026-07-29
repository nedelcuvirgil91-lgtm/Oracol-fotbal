"""Teste pentru providers/flashscore/discovery.py (Foundation Data Layer,
ADR-044, M1) — fara retea.

`parse_match_links()` e testata direct contra evidentei brute REALE,
capturate live in aceasta sesiune (docs/06_UDAL/poc_evidence/
flashscore_10matches/*_hub_raw.html) - nu contra unui fixture inventat."""
from __future__ import annotations

from pathlib import Path

import pytest

from providers.flashscore.adapter import FlashscoreAdapter
from providers.flashscore.discovery import (
    FLASHSCORE_TRACKED_COMPETITIONS,
    DiscoveredMatch,
    discover_matches,
    parse_match_links,
    run_foundation_data_layer_for_discovered_matches,
)

EVIDENCE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_10matches"


def test_tracked_competitions_only_contains_live_verified_slugs():
    """Regresie - orice liga noua adaugata aici fara verificare live ar
    trebui sa fie o schimbare deliberata, vizibila la code review, nu
    tacita."""
    assert FLASHSCORE_TRACKED_COMPETITIONS == {
        "Romania SuperLiga": ("romania", "superliga"),
        "UEFA Champions League": ("europe", "champions-league"),
    }


def test_parse_match_links_on_real_superliga_hub_evidence():
    html = (EVIDENCE_DIR / "superliga_results_hub_raw.html").read_text(encoding="utf-8")
    pairs = parse_match_links(html)
    assert len(pairs) == 16
    base, mid = pairs[0]
    assert base == "https://www.flashscore.com/match/football/fc-botosani-GjY1JjUS/rapid-bucuresti-YFCpigVG"
    assert mid == "EeqI7WJc"
    assert all(not b.endswith("/") and "?" not in b for b, _ in pairs)
    assert len({b for b, _ in pairs}) == len(pairs)


def test_parse_match_links_on_real_ucl_hub_evidence():
    html = (EVIDENCE_DIR / "ucl_results_hub_raw.html").read_text(encoding="utf-8")
    pairs = parse_match_links(html)
    assert len(pairs) == 28


def test_parse_match_links_empty_html():
    assert parse_match_links("<html><body>no matches</body></html>") == []


def test_parse_match_links_ignores_links_without_mid():
    html = '<a href="https://www.flashscore.com/match/football/a-1/b-2/">no mid param</a>'
    assert parse_match_links(html) == []


def test_discover_matches_rejects_unknown_league():
    with pytest.raises(ValueError):
        discover_matches(leagues=["Not A Tracked League"])


def test_discovered_match_is_frozen_dataclass():
    m = DiscoveredMatch(league="Romania SuperLiga", match_base_url="https://x", mid="abc", source="results")
    with pytest.raises(Exception):
        m.mid = "changed"  # type: ignore[misc]


def test_run_foundation_data_layer_passes_league_to_persist(monkeypatch):
    """[FIX live, gasit la al treilea run live real] match_history.league
    e NOT NULL - Discovery deja cunoaste liga (a ales-o explicit ca sa
    construiasca URL-ul), trebuie sa o transmita mai departe la persist(),
    nu doar la fetch()."""
    monkeypatch.setattr(FlashscoreAdapter, "preflight", lambda self: None)
    monkeypatch.setattr(FlashscoreAdapter, "fetch", lambda self, params: {"summary": "<html></html>"})
    monkeypatch.setattr(FlashscoreAdapter, "normalize", lambda self, raw: [raw])
    monkeypatch.setattr(
        FlashscoreAdapter, "validate",
        lambda self, records: [{
            "home_team": "A", "away_team": "B", "kickoff_date": "2026-08-01T18:00:00",
            "_pages": records[0],
        }],
    )
    calls = []
    monkeypatch.setattr(
        "providers.flashscore.persistence.persist_match_with_data_trust_layer",
        lambda pages, match_ref, **kw: calls.append(kw) or {"ok": True},
    )

    match = DiscoveredMatch(league="Romania SuperLiga", match_base_url="https://x", mid="abc", source="results")
    reports = run_foundation_data_layer_for_discovered_matches([match])

    assert reports == [{"ok": True, "match": match}]
    assert calls == [{"league": "Romania SuperLiga", "competition": "Romania SuperLiga"}]
