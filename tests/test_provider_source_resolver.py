"""Teste pentru provider_source_resolver.py (ADR-034, PR5) — fără rețea."""
from __future__ import annotations

from provider_source_resolver import FALLBACK_PRIORITY, determine_current_provider


def _match(league: str, source: str) -> dict:
    return {"league": league, "source": source}


def test_determine_current_provider_most_matches_wins():
    matches = [
        _match("Romania SuperLiga", "the-odds-api"),
        _match("Romania SuperLiga", "freelivefootball"),
        _match("Romania SuperLiga", "freelivefootball"),
        _match("Romania SuperLiga", "freelivefootball"),
    ]
    assert determine_current_provider("Romania SuperLiga", matches) == "freelivefootball"


def test_determine_current_provider_translates_oracle_source_strings():
    matches = [_match("MLS", "the-odds-api"), _match("MLS", "football-data.org"),
               _match("MLS", "football-data.org")]
    assert determine_current_provider("MLS", matches) == "footballdata"


def test_determine_current_provider_ignores_demo_matches():
    matches = [_match("Romania SuperLiga", "demo-romania-superliga")] * 5
    assert determine_current_provider("Romania SuperLiga", matches) is None


def test_determine_current_provider_none_when_no_matches_for_league():
    matches = [_match("MLS", "espn")]
    assert determine_current_provider("Romania SuperLiga", matches) is None


def test_determine_current_provider_ignores_other_leagues():
    matches = [_match("MLS", "espn"), _match("Romania SuperLiga", "thesportsdb")]
    assert determine_current_provider("Romania SuperLiga", matches) == "thesportsdb"


def test_determine_current_provider_tie_break_uses_fallback_priority():
    # oddsapi si footballdata au cate 2 meciuri fiecare -> egalitate
    matches = [
        _match("MLS", "football-data.org"), _match("MLS", "football-data.org"),
        _match("MLS", "the-odds-api"), _match("MLS", "the-odds-api"),
    ]
    # oddsapi apare inaintea footballdata in FALLBACK_PRIORITY
    assert FALLBACK_PRIORITY.index("oddsapi") < FALLBACK_PRIORITY.index("footballdata")
    assert determine_current_provider("MLS", matches) == "oddsapi"


def test_determine_current_provider_already_canonical_sources_pass_through():
    matches = [_match("Romania SuperLiga", "apifootball")]
    assert determine_current_provider("Romania SuperLiga", matches) == "apifootball"


def test_determine_current_provider_is_deterministic():
    matches = [_match("MLS", "espn"), _match("MLS", "espn"), _match("MLS", "thesportsdb")]
    results = [determine_current_provider("MLS", matches) for _ in range(100)]
    assert all(r == results[0] for r in results)
