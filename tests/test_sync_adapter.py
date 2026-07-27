"""Teste pentru sync_adapter.py (R-Sync-1, ADR-039).

Niciun adaptor real de provider nu e implementat aici — doar contractul
abstract în sine (fetch/normalize/validate/persist obligatorii,
coverage_check opțional cu implicit True)."""
from __future__ import annotations

import pytest

from sync_adapter import SyncAdapter


def test_cannot_instantiate_without_implementing_abstract_methods():
    class IncompleteAdapter(SyncAdapter):
        provider_id = "incomplete"

    with pytest.raises(TypeError):
        IncompleteAdapter()


def test_minimal_concrete_adapter_can_be_instantiated():
    class MinimalAdapter(SyncAdapter):
        provider_id = "minimal"

        def fetch(self, params):
            return {"raw": True}

        def normalize(self, raw_payload):
            return [raw_payload]

        def validate(self, records):
            return records

        def persist(self, records):
            return True

    adapter = MinimalAdapter()
    assert adapter.provider_id == "minimal"
    assert adapter.fetch({}) == {"raw": True}
    assert adapter.normalize({"a": 1}) == [{"a": 1}]
    assert adapter.validate([1, 2, 3]) == [1, 2, 3]
    assert adapter.persist([1, 2, 3]) is True


def test_coverage_check_defaults_to_true():
    class NoCoverageAdapter(SyncAdapter):
        provider_id = "no-coverage"

        def fetch(self, params):
            return None

        def normalize(self, raw_payload):
            return []

        def validate(self, records):
            return records

        def persist(self, records):
            return True

    adapter = NoCoverageAdapter()
    assert adapter.coverage_check({}) is True
    assert adapter.coverage_check({"league": "anything"}) is True


def test_coverage_check_can_be_overridden():
    class GatedAdapter(SyncAdapter):
        provider_id = "gated"

        def fetch(self, params):
            return None

        def normalize(self, raw_payload):
            return []

        def validate(self, records):
            return records

        def persist(self, records):
            return True

        def coverage_check(self, context):
            return context.get("league") == "Premier League"

    adapter = GatedAdapter()
    assert adapter.coverage_check({"league": "Premier League"}) is True
    assert adapter.coverage_check({"league": "Unknown League"}) is False


def test_validate_can_filter_records_without_raising():
    class FilteringAdapter(SyncAdapter):
        provider_id = "filtering"

        def fetch(self, params):
            return None

        def normalize(self, raw_payload):
            return []

        def validate(self, records):
            # Regula #8 - exclude, nu arunca exceptie
            return [r for r in records if r.get("odds", 0) > 1.0]

        def persist(self, records):
            return True

    adapter = FilteringAdapter()
    result = adapter.validate([{"odds": 0.5}, {"odds": 2.1}, {"odds": 1.0}])
    assert result == [{"odds": 2.1}]
