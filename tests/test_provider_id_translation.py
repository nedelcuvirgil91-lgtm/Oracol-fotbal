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


def test_legacy_to_canonical_is_bijective_no_duplicate_values():
    """Daca doua chei legacy ar traduce catre acelasi canonical_id,
    CANONICAL_TO_LEGACY ar pierde tacit una dintre ele - verificat explicit,
    nu doar presupus. Modulul insusi arunca AssertionError la import daca
    asta se intampla (fail loud) - testul confirma ca starea curenta e ok."""
    values = list(LEGACY_TO_CANONICAL.values())
    assert len(values) == len(set(values)), f"valori duplicate in LEGACY_TO_CANONICAL: {values}"


def test_every_canonical_id_in_translation_table_exists_in_provider_registry():
    """Fiecare canonical_id la care traduce tabelul TREBUIE sa existe real
    in Provider Registry (PR1) - altfel traducerea duce catre un provider
    fantoma."""
    from provider_registry import ProviderRegistry
    reg = ProviderRegistry()
    known_ids = {r.provider_id for r in reg.list_providers()}
    for legacy_key, canonical_id in LEGACY_TO_CANONICAL.items():
        assert canonical_id in known_ids, (
            f"{legacy_key!r} traduce catre {canonical_id!r}, care NU exista "
            f"in Provider Registry"
        )


def test_full_round_trip_both_directions():
    for legacy_key, canonical_id in LEGACY_TO_CANONICAL.items():
        assert to_canonical(legacy_key) == canonical_id
        assert to_legacy(canonical_id) == legacy_key


def test_providers_without_legacy_equivalent_are_documented_not_silent():
    """sportapi si weatherapi NU au echivalent in mappings.py azi - fapt
    real (sportapi nu exista deloc in schema veche, weatherapi nu e sursa
    de fixtures/odds/standings), nu un gol accidental. Testat explicit ca
    sa fie o afirmatie verificata, nu o presupunere tacuta."""
    assert to_legacy("sportapi") is None
    assert to_legacy("weatherapi") is None
    # Provider Registry are 8 provideri; exact 6 au echivalent legacy.
    from provider_registry import ProviderRegistry
    reg = ProviderRegistry()
    known_ids = {r.provider_id for r in reg.list_providers()}
    without_legacy = {pid for pid in known_ids if to_legacy(pid) is None}
    assert without_legacy == {"sportapi", "weatherapi"}
