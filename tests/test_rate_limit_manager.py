"""Teste pentru rate_limit_manager.py (R4.1, ADR-038 audit §5/§7/§14)."""
from __future__ import annotations

import time

from rate_limit_manager import RateLimitManager


def test_can_request_fail_open_when_no_headers_seen():
    rlm = RateLimitManager()
    assert rlm.can_request("apifootball") is True


def test_daily_quota_exhausted_blocks_request():
    rlm = RateLimitManager()
    rlm.record_response_headers("apifootball", {
        "x-ratelimit-requests-limit": "100",
        "x-ratelimit-requests-remaining": "0",
    })
    assert rlm.can_request("apifootball") is False


def test_daily_quota_positive_allows_request():
    rlm = RateLimitManager()
    rlm.record_response_headers("apifootball", {
        "x-ratelimit-requests-limit": "100",
        "x-ratelimit-requests-remaining": "42",
    })
    assert rlm.can_request("apifootball") is True


def test_per_minute_quota_exhausted_blocks_request_within_window():
    rlm = RateLimitManager()
    rlm.record_response_headers("apifootball", {
        "x-ratelimit-limit": "10",
        "x-ratelimit-remaining": "0",
    })
    assert rlm.can_request("apifootball") is False


def test_per_minute_quota_recovers_after_window():
    """Regresie directa pe fereastra de 60s — nu blocat permanent, doar
    pana la refresh-ul urmator de header (simulat prin monotonic decalat)."""
    rlm = RateLimitManager()
    rlm.record_response_headers("apifootball", {
        "x-ratelimit-limit": "10",
        "x-ratelimit-remaining": "0",
    })
    state = rlm._state["apifootball"]
    state.minute_updated_at = time.monotonic() - 61.0  # simuleaza trecerea ferestrei
    assert rlm.can_request("apifootball") is True


def test_headers_are_case_insensitive():
    rlm = RateLimitManager()
    rlm.record_response_headers("apifootball", {
        "X-RateLimit-Requests-Limit": "100",
        "X-RateLimit-Requests-Remaining": "0",
    })
    assert rlm.can_request("apifootball") is False


def test_malformed_header_value_is_ignored_not_crashed():
    rlm = RateLimitManager()
    rlm.record_response_headers("apifootball", {
        "x-ratelimit-requests-remaining": "not-a-number",
    })
    assert rlm.can_request("apifootball") is True  # fail-open, nu crash


def test_providers_are_independent():
    rlm = RateLimitManager()
    rlm.record_response_headers("apifootball", {"x-ratelimit-requests-remaining": "0", "x-ratelimit-requests-limit": "100"})
    assert rlm.can_request("apifootball") is False
    assert rlm.can_request("oddsapi") is True


def test_status_reports_known_state():
    rlm = RateLimitManager()
    assert rlm.status("apifootball")["known"] is False
    rlm.record_response_headers("apifootball", {"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "77"})
    status = rlm.status("apifootball")
    assert status["known"] is True
    assert status["daily_limit"] == 100
    assert status["daily_remaining"] == 77
