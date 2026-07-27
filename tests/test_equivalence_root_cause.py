"""Teste pentru equivalence_root_cause.py (ADR-040, G2) — clasificare
euristică, pură, fără I/O."""
from __future__ import annotations

import equivalence_root_cause as mod


def test_classify_field_difference_known_fields():
    assert mod.classify_field_difference("venue_city") == mod.VENUE_PRIORITY
    assert mod.classify_field_difference("league") == mod.LEAGUE_MAPPING
    assert mod.classify_field_difference("kickoff_utc") == mod.KICKOFF_CONFLICT


def test_classify_field_difference_unknown_field_is_unknown():
    assert mod.classify_field_difference("some_future_field") == mod.UNKNOWN


def test_classify_provider_id_difference_missing_vs_conflict():
    assert mod.classify_provider_id_difference(None) == mod.MISSING_PROVIDER_ID
    assert mod.classify_provider_id_difference("some-other-id") == mod.UNKNOWN


def test_classify_missing_scheduled_and_missing_live():
    assert mod.classify_missing_scheduled() == mod.PROVIDER_TIMEOUT
    assert mod.classify_missing_live() == mod.UNKNOWN


def test_all_categories_frozen_and_contains_every_constant():
    for cat in (mod.VENUE_PRIORITY, mod.LEAGUE_MAPPING, mod.KICKOFF_CONFLICT,
                mod.MISSING_PROVIDER_ID, mod.PROVIDER_TIMEOUT, mod.TEAM_NORMALIZATION, mod.UNKNOWN):
        assert cat in mod.ALL_CATEGORIES
    assert isinstance(mod.ALL_CATEGORIES, frozenset)


def test_extensible_via_dict_not_via_function_body():
    """Regula de Aur: adăugarea unei categorii se face prin dicționar, nu
    prin extinderea unui CASE -- verificăm că mecanismul e chiar un dict."""
    assert isinstance(mod._FIELD_TO_CATEGORY, dict)
