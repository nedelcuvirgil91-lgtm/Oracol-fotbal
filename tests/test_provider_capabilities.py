"""Teste pentru provider_capabilities.py (ADR-034, PR2) — fără rețea."""
from __future__ import annotations

import pytest
from types import MappingProxyType

from acquisition_tier import AcquisitionTier
from provider_capabilities import (
    CAPABILITIES, CostClass, DataType, ProviderCapability,
    get_capability, supports,
)
from provider_registry import ProviderRegistry


def test_capabilities_is_immutable_mapping():
    with pytest.raises(TypeError):
        CAPABILITIES["noua_intrare"] = None  # type: ignore[index]


def test_capabilities_is_mappingproxy_not_plain_dict():
    assert isinstance(CAPABILITIES, MappingProxyType)


def test_data_types_are_frozenset_not_mutable():
    cap = get_capability("sportapi")
    assert isinstance(cap.data_types, frozenset)
    with pytest.raises(AttributeError):
        cap.data_types.add(DataType.TRANSFERS)  # type: ignore[attr-defined]


def test_cache_ttl_hours_forced_to_mappingproxy_internally():
    """Contractul public accepta Mapping (nu MappingProxyType explicit),
    dar intern tot devine imuabil - __post_init__ forteaza asta indiferent
    ce s-a primit la construire."""
    cap = ProviderCapability(
        provider_id="test", version=1, data_types=frozenset({DataType.FIXTURES}),
        cost_class=CostClass.FREE_UNLIMITED, cache_ttl_hours={DataType.FIXTURES: 1},
    )
    assert isinstance(cap.cache_ttl_hours, MappingProxyType)
    with pytest.raises(TypeError):
        cap.cache_ttl_hours[DataType.FIXTURES] = 999  # type: ignore[index]


def test_provider_capability_dataclass_is_frozen():
    cap = get_capability("apifootball")
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError (subclasa AttributeError)
        cap.version = 2  # type: ignore[misc]


def test_every_capability_has_version_int():
    for provider_id, cap in CAPABILITIES.items():
        assert isinstance(cap.version, int), f"{provider_id} nu are version int"
        assert cap.version >= 1


def test_registry_completeness_capability_to_provider():
    """Fiecare provider_id din Capability Registry TREBUIE sa existe in
    Provider Registry - altfel Capability descrie un provider fantoma."""
    reg = ProviderRegistry()
    known_ids = {r.provider_id for r in reg.list_providers()}
    for provider_id in CAPABILITIES:
        assert provider_id in known_ids, (
            f"{provider_id!r} e in Capability Registry dar NU in Provider Registry"
        )


def test_registry_completeness_provider_to_capability():
    """Invers: fiecare provider din Provider Registry TREBUIE sa aiba o
    intrare in Capability Registry - regresie directa ceruta explicit:
    daca apare un provider nou (ex. viitor 'flashscore') si cineva uita
    sa-l adauge aici, testul trebuie sa pice."""
    reg = ProviderRegistry()
    known_ids = {r.provider_id for r in reg.list_providers()}
    for provider_id in known_ids:
        assert provider_id in CAPABILITIES, (
            f"{provider_id!r} e in Provider Registry dar NU in Capability Registry"
        )


def test_supports_true_for_known_capability():
    assert supports("sportapi", DataType.H2H) is True
    assert supports("sportapi", DataType.XG) is True


def test_supports_false_for_unlisted_capability():
    assert supports("footballdata", DataType.XG) is False
    assert supports("espn", DataType.STATISTICS) is False  # espn ofera doar FIXTURES


def test_supports_false_for_unknown_provider():
    assert supports("flashscore-inca-neadaugat", DataType.FIXTURES) is False


def test_get_capability_returns_none_for_unknown_provider():
    assert get_capability("flashscore-inca-neadaugat") is None


def test_every_capability_defaults_to_api_tier():
    """[UDAL Faza 0, ADR-042] Aditiv - toti cei 9 provideri existenti
    raman AcquisitionTier.API, zero schimbare de comportament."""
    for provider_id, cap in CAPABILITIES.items():
        assert cap.tier is AcquisitionTier.API, (
            f"{provider_id!r} nu e AcquisitionTier.API - regresie neasteptata"
        )


def test_weatherapi_registered_with_empty_data_types_not_omitted():
    """weatherapi nu e sursa de fotbal, dar trebuie sa existe aici (altfel
    pica completitudinea bidirectionala) - frozenset() gol, nu absenta."""
    cap = get_capability("weatherapi")
    assert cap is not None
    assert cap.data_types == frozenset()
