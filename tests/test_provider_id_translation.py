"""Teste pentru provider_id_translation.py (ADR-034, PR3) — fără rețea."""
from __future__ import annotations

import pytest
from types import MappingProxyType

from mappings import LEAGUE_PROVIDERS
from provider_id_translation import LEGACY_TO_CANONICAL, CANONICAL_TO_LEGACY, to_canonical, to_legacy


def test_tables_are_immutable_mappings():
    assert isinstance(LEGACY_TO_CANONICAL, MappingProxyType)
    assert isinstance(CANONICAL_TO_LEGACY, MappingProxyType)
    with pytest.raises(TypeError):
        LEGACY_TO_CANONICAL["nou"] = "x"  # type: ignore[index]


def test_to_canonical_known_keys():
    assert to_canonical("football_data") == "footballdata"
    assert to_canonical("tsdb") == "thesportsdb"
    assert to_canonical("odds") == "oddsapi"
    assert to_canonical("freelf") == "freelivefootball"
    assert to_canonical("api_football") == "apifootball"
    assert to_canonical("espn") == "espn"


def test_to_legacy_is_exact_inverse():
    for legacy_key, canonical_id in LEGACY_TO_CANONICAL.items():
        assert to_legacy(canonical_id) == legacy_key


def test_to_canonical_none_for_unknown():
    assert to_canonical("nu-exista-asa-ceva") is None


def test_to_legacy_none_for_unknown():
    assert to_legacy("sportapi") is None  # nu are echivalent legacy in mappings.py


def test_every_legacy_key_used_in_mappings_has_translation():
    """Regresie impotriva desincronizarii: daca mappings.py foloseste vreodata
    o cheie noua, netradusa aici, testul trebuie sa pice - nu sa esueze tacit
    la runtime prin league_mapping.get_league_provider_state()."""
    used_keys: set[str] = set()
    for definition in LEAGUE_PROVIDERS.values():
        used_keys.update(definition.provider_ids.keys())
        used_keys.update(definition.supported.keys())
    for key in used_keys:
        assert key in LEGACY_TO_CANONICAL, f"cheia {key!r} din mappings.py nu are traducere"
