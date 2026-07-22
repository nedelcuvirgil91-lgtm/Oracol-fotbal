"""Teste pentru coverage_cache.py (R4.1, ADR-038 audit §2)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import coverage_cache


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_is_fresh_true_within_active_ttl():
    entry = {
        "verified_at": _iso(datetime.now(timezone.utc) - timedelta(days=10)),
        "fixtures_supported": "True",
        "coverage_raw": {"standings": True, "injuries": True},
    }
    assert coverage_cache.is_fresh(entry) is True


def test_is_fresh_false_beyond_active_ttl():
    entry = {
        "verified_at": _iso(datetime.now(timezone.utc) - timedelta(days=31)),
        "fixtures_supported": "True",
        "coverage_raw": {"standings": True},
    }
    assert coverage_cache.is_fresh(entry) is False


def test_is_fresh_uses_short_ttl_for_preseason_all_flags_false():
    entry = {
        "verified_at": _iso(datetime.now(timezone.utc) - timedelta(days=8)),
        "fixtures_supported": "necunoscut",
        "coverage_raw": {"standings": False, "injuries": False, "odds": False},
    }
    # 8 zile > 7 zile (TTL pre-sezon) -> expirat, desi ar fi fresh la TTL activ (30)
    assert coverage_cache.is_fresh(entry) is False


def test_is_fresh_preseason_within_short_ttl():
    entry = {
        "verified_at": _iso(datetime.now(timezone.utc) - timedelta(days=3)),
        "fixtures_supported": "necunoscut",
        "coverage_raw": {"standings": False, "injuries": False},
    }
    assert coverage_cache.is_fresh(entry) is True


def test_is_fresh_missing_coverage_raw_uses_active_ttl_not_preseason():
    """Absenta coverage_raw NU inseamna pre-sezon - ar fi o presupunere."""
    entry = {
        "verified_at": _iso(datetime.now(timezone.utc) - timedelta(days=10)),
        "fixtures_supported": "necunoscut",
        "coverage_raw": None,
    }
    assert coverage_cache.is_fresh(entry) is True  # 10 zile < 30 (TTL activ)


def test_is_fresh_plan_restricted_uses_long_ttl_even_with_no_flags():
    entry = {
        "verified_at": _iso(datetime.now(timezone.utc) - timedelta(days=10)),
        "fixtures_supported": "plan_restricted",
        "coverage_raw": {},
    }
    assert coverage_cache.is_fresh(entry) is True


def test_is_fresh_missing_verified_at_is_not_fresh():
    assert coverage_cache.is_fresh({}) is False


def test_get_cached_coverage_returns_none_when_no_entry(monkeypatch):
    import supabase_client

    monkeypatch.setattr(supabase_client, "get_league_coverage", lambda *a, **kw: None)
    assert coverage_cache.get_cached_coverage("Romania SuperLiga", 283, 2026) is None


def test_get_cached_coverage_returns_none_when_stale(monkeypatch):
    import supabase_client

    stale_entry = {
        "verified_at": _iso(datetime.now(timezone.utc) - timedelta(days=365)),
        "fixtures_supported": "True",
        "coverage_raw": {"standings": True},
    }
    monkeypatch.setattr(supabase_client, "get_league_coverage", lambda *a, **kw: stale_entry)
    assert coverage_cache.get_cached_coverage("Premier League", 39, 2025) is None


def test_get_cached_coverage_returns_entry_when_fresh(monkeypatch):
    import supabase_client

    fresh_entry = {
        "verified_at": _iso(datetime.now(timezone.utc) - timedelta(days=1)),
        "fixtures_supported": "True",
        "coverage_raw": {"standings": True},
    }
    monkeypatch.setattr(supabase_client, "get_league_coverage", lambda *a, **kw: fresh_entry)
    assert coverage_cache.get_cached_coverage("Premier League", 39, 2025) == fresh_entry


def test_record_coverage_forwards_all_fields(monkeypatch):
    import supabase_client

    calls = []

    def _fake_set(league_id_canonical, api_football_league_id, season, **kwargs):
        calls.append((league_id_canonical, api_football_league_id, season, kwargs))
        return True

    monkeypatch.setattr(supabase_client, "set_league_coverage", _fake_set)
    ok = coverage_cache.record_coverage(
        "Romania SuperLiga", 283, 2026,
        fixtures_supported="plan_restricted",
        coverage_raw={"standings": False},
        verified_via="error_response",
        raw_error_payload={"error": "plan restricted"},
    )
    assert ok is True
    assert calls[0][:3] == ("Romania SuperLiga", 283, 2026)
    assert calls[0][3]["fixtures_supported"] == "plan_restricted"
    assert calls[0][3]["verified_via"] == "error_response"
