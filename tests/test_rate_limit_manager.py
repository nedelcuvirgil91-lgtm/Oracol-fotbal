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


# ── Scheme reale per provider (Phase 4 Functional Completion, punctul 1) ──
# Confirmate live prin POC dedicat (sync/poc_rate_limit_headers_check.py,
# rulare GitHub Actions 30831280759, 2026-08-03) — nu presupuse.

def test_oddsapi_real_header_recognized_not_apifootball_convention():
    """The Odds API trimite "x-requests-remaining", nu "x-ratelimit-*" —
    inainte de generalizare, acest header nu era niciodata recunoscut si
    oddsapi ramanea fail-open permanent."""
    rlm = RateLimitManager()
    rlm.record_response_headers("oddsapi", {"x-requests-remaining": "0"})
    assert rlm.can_request("oddsapi") is False
    assert rlm.status("oddsapi")["daily_remaining"] == 0


def test_oddsapi_positive_remaining_allows_request():
    rlm = RateLimitManager()
    rlm.record_response_headers("oddsapi", {"x-requests-remaining": "484"})
    assert rlm.can_request("oddsapi") is True
    assert rlm.status("oddsapi")["daily_remaining"] == 484


def test_weatherapi_real_header_recognized_as_minute_budget():
    """WeatherAPI trimite "x-weatherapi-qpm-left" (queries per minut) —
    semantic per-minut, mapat la minute_remaining, nu daily_remaining."""
    rlm = RateLimitManager()
    rlm.record_response_headers("weatherapi", {"x-weatherapi-qpm-left": "0"})
    assert rlm.can_request("weatherapi") is False
    status = rlm.status("weatherapi")
    assert status["minute_remaining"] == 0
    assert status["daily_remaining"] is None


def test_weatherapi_high_qpm_left_allows_request():
    rlm = RateLimitManager()
    rlm.record_response_headers("weatherapi", {"x-weatherapi-qpm-left": "999999"})
    assert rlm.can_request("weatherapi") is True


def test_apifootball_scheme_unaffected_by_provider_specific_schemes():
    """Generalizarea NU trebuie sa schimbe comportamentul existent pentru
    providerii deja acoperiti de scheme-ul implicit (API-Football, Soccer
    Football Info) — regresie directa pe schema default."""
    rlm = RateLimitManager()
    rlm.record_response_headers("apifootball", {
        "x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "0",
    })
    assert rlm.can_request("apifootball") is False
    # Header-ele reale ale oddsapi/weatherapi NU trebuie sa afecteze apifootball.
    rlm.record_response_headers("apifootball", {"x-requests-remaining": "0"})
    assert rlm.status("apifootball")["daily_remaining"] == 0  # neschimbat de la primul apel


def test_thesportsdb_and_eloratings_have_no_scheme_stay_fail_open():
    """Confirmat live: zero header-e de rate-limit pentru TheSportsDB si
    eloratings.net — raman fail-open prin design (protejate separat, prin
    throttling static in oracle_api.py, nu prin header-e aici)."""
    rlm = RateLimitManager()
    rlm.record_response_headers("thesportsdb", {"date": "Mon, 03 Aug 2026 16:15:53 GMT", "server": "cloudflare"})
    assert rlm.can_request("thesportsdb") is True
    rlm.record_response_headers("eloratings", {"server": "LiteSpeed"})
    assert rlm.can_request("eloratings") is True
