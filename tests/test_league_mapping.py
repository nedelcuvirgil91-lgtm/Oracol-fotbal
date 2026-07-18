"""Teste pentru league_mapping.py (ADR-034, PR3) — fără rețea."""
from __future__ import annotations

import pytest

from mappings import LEAGUE_PROVIDERS
from provider_id_translation import to_canonical
from league_mapping import (
    Confidence, LeagueProviderState, ProviderState,
    _translate_legacy_state, get_league_provider_state,
)


def test_translate_legacy_state_true_to_available():
    assert _translate_legacy_state(True) is ProviderState.AVAILABLE


def test_translate_legacy_state_false_to_unavailable():
    assert _translate_legacy_state(False) is ProviderState.UNAVAILABLE


def test_translate_legacy_state_necunoscut_to_untested():
    """"necunoscut" devine UNTESTED, NU UNKNOWN - distinctie explicit ceruta:
    "nu am testat inca" != "nu stim"."""
    assert _translate_legacy_state("necunoscut") is ProviderState.UNTESTED


def test_translate_legacy_state_plan_restricted():
    assert _translate_legacy_state("plan_restricted") is ProviderState.PLAN_RESTRICTED


def test_translate_legacy_state_raises_on_unmapped_value():
    with pytest.raises(ValueError):
        _translate_legacy_state("cu-totul-altceva")


def test_confidence_validation_rejects_assumed_for_non_available_state():
    with pytest.raises(ValueError):
        LeagueProviderState(
            league="X", provider_id="y", legacy_key="z",
            state=ProviderState.UNAVAILABLE, confidence=Confidence.ASSUMED,
        )


def test_confidence_validation_rejects_documented_for_non_available_state():
    with pytest.raises(ValueError):
        LeagueProviderState(
            league="X", provider_id="y", legacy_key="z",
            state=ProviderState.PLAN_RESTRICTED, confidence=Confidence.DOCUMENTED,
        )


def test_confidence_validation_allows_confirmed_for_non_available_state():
    # Nu trebuie sa arunce - CONFIRMED e permis pt. stari non-AVAILABLE
    LeagueProviderState(
        league="X", provider_id="y", legacy_key="z",
        state=ProviderState.PLAN_RESTRICTED, confidence=Confidence.CONFIRMED,
    )


def test_confidence_validation_allows_unknown_for_non_available_state():
    LeagueProviderState(
        league="X", provider_id="y", legacy_key="z",
        state=ProviderState.DEAD_KEY, confidence=Confidence.UNKNOWN,
    )


def test_confidence_validation_allows_assumed_for_available_state():
    # AVAILABLE nu are restrictie - ASSUMED e permis
    LeagueProviderState(
        league="X", provider_id="y", legacy_key="z",
        state=ProviderState.AVAILABLE, confidence=Confidence.ASSUMED,
    )


def test_get_league_provider_state_romania_superliga_api_football_confirmed():
    """Integrare reala: Romania SuperLiga x apifootball - verificat live in
    aceeasi sesiune (plan_restricted, run 29616468120), confidence=CONFIRMED
    setat explicit in _CONFIDENCE_OVERRIDES."""
    result = get_league_provider_state("Romania SuperLiga", "apifootball")
    assert result is not None
    assert result.state is ProviderState.PLAN_RESTRICTED
    assert result.confidence is Confidence.CONFIRMED
    assert result.legacy_key == "api_football"


def test_get_league_provider_state_defaults_to_unknown_confidence():
    """O pereche AVAILABLE dar niciodata verificata explicit (ex. Premier
    League x espn) - confidence implicit UNKNOWN, nu presupus."""
    result = get_league_provider_state("Premier League", "espn")
    assert result is not None
    assert result.state is ProviderState.AVAILABLE
    assert result.confidence is Confidence.UNKNOWN


def test_get_league_provider_state_none_for_unknown_league():
    assert get_league_provider_state("Liga Complet Necunoscuta", "espn") is None


def test_get_league_provider_state_none_for_provider_without_legacy_translation():
    """sportapi nu are deloc o cheie corespondenta in mappings.py azi."""
    assert get_league_provider_state("Romania SuperLiga", "sportapi") is None


def test_all_real_league_provider_pairs_translate_without_error():
    """Soundness check pe tot setul real de date din mappings.py: fiecare
    (liga, provider canonic) trebuie sa se traduca fara exceptie - confirma
    ca _translate_legacy_state acopera fiecare valoare bruta reala folosita
    azi, nu doar exemplele din teste."""
    for league, definition in LEAGUE_PROVIDERS.items():
        for legacy_key in definition.supported:
            canonical_id = to_canonical(legacy_key)
            assert canonical_id is not None, f"{legacy_key!r} netradus"
            result = get_league_provider_state(league, canonical_id)
            assert result is not None, f"{league!r} x {canonical_id!r} a esuat"
