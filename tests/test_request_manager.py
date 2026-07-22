"""Teste pentru request_manager.py (R4.1, ADR-038 audit §4/§7/§8)."""
from __future__ import annotations

import time

from request_manager import RequestManager, _RAM_TTL_SECONDS


def test_ram_cache_miss_returns_none():
    rm = RequestManager()
    assert rm.get_ram("apifootball", "injuries", "team:42") is None


def test_ram_cache_set_then_get_hit():
    rm = RequestManager()
    rm.set_ram("apifootball", "injuries", "team:42", {"response": []})
    assert rm.get_ram("apifootball", "injuries", "team:42") == {"response": []}


def test_ram_cache_none_value_never_stored():
    rm = RequestManager()
    rm.set_ram("apifootball", "injuries", "team:42", None)
    assert rm.get_ram("apifootball", "injuries", "team:42") is None


def test_ram_cache_keys_are_provider_and_category_scoped():
    """Aceeasi cheie brută, provideri/categorii diferite - fara coliziune."""
    rm = RequestManager()
    rm.set_ram("apifootball", "injuries", "42", {"a": 1})
    rm.set_ram("apifootball", "coaches", "42", {"b": 2})
    rm.set_ram("otherprovider", "injuries", "42", {"c": 3})
    assert rm.get_ram("apifootball", "injuries", "42") == {"a": 1}
    assert rm.get_ram("apifootball", "coaches", "42") == {"b": 2}
    assert rm.get_ram("otherprovider", "injuries", "42") == {"c": 3}


def test_ram_cache_expires_after_ttl():
    rm = RequestManager()
    rm.set_ram("apifootball", "injuries", "team:42", {"response": []})
    # Simuleaza trecerea TTL-ului fara sa astepte 5 minute reale.
    ram_key = rm._ram_key("apifootball", "injuries", "team:42")
    rm._ram[ram_key].expires_at = time.monotonic() - 1.0
    assert rm.get_ram("apifootball", "injuries", "team:42") is None


def test_should_request_fail_open_without_rate_limiter():
    rm = RequestManager(rate_limiter=None)
    assert rm.should_request("apifootball") is True


def test_should_request_delegates_to_rate_limiter():
    class _FakeLimiter:
        def can_request(self, provider):
            return provider != "apifootball"

    rm = RequestManager(rate_limiter=_FakeLimiter())
    assert rm.should_request("apifootball") is False
    assert rm.should_request("oddsapi") is True


def test_inflight_dedup_blocks_second_acquire_for_same_key():
    rm = RequestManager()
    assert rm.try_acquire_inflight("apifootball", "injuries", "team:42") is True
    assert rm.try_acquire_inflight("apifootball", "injuries", "team:42") is False


def test_inflight_release_allows_reacquire():
    rm = RequestManager()
    assert rm.try_acquire_inflight("apifootball", "injuries", "team:42") is True
    rm.release_inflight("apifootball", "injuries", "team:42")
    assert rm.try_acquire_inflight("apifootball", "injuries", "team:42") is True


def test_inflight_is_scoped_per_key_not_global():
    rm = RequestManager()
    assert rm.try_acquire_inflight("apifootball", "injuries", "team:42") is True
    assert rm.try_acquire_inflight("apifootball", "injuries", "team:99") is True


def test_record_response_headers_forwards_to_rate_limiter():
    calls = []

    class _FakeLimiter:
        def can_request(self, provider):
            return True

        def record_response_headers(self, provider, headers):
            calls.append((provider, dict(headers)))

    rm = RequestManager(rate_limiter=_FakeLimiter())
    rm.record_response_headers("apifootball", {"x-ratelimit-requests-remaining": "5"})
    assert calls == [("apifootball", {"x-ratelimit-requests-remaining": "5"})]
