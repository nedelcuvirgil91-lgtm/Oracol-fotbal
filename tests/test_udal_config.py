"""Teste pentru udal_config.py (UDAL Faza 0, ADR-042) — fără rețea,
Supabase mock-uit prin monkeypatch (niciun apel real), tipar identic
test_shadow_config.py."""
from __future__ import annotations

import udal_config


def _mock_config(monkeypatch, overrides: dict | None = None):
    import supabase_client as sb
    merged = dict(udal_config._DEFAULT_CONFIG)
    merged.update(overrides or {})
    monkeypatch.setattr(sb, "load_config", lambda default: merged)


def test_all_master_flags_default_false(monkeypatch):
    _mock_config(monkeypatch)
    assert udal_config.is_udal_enabled() is False
    assert udal_config.is_tier_http_scraper_enabled() is False
    assert udal_config.is_tier_playwright_enabled() is False
    assert udal_config.is_historical_backfill_enabled() is False
    assert udal_config.is_live_acquisition_enabled() is False


def test_shadow_mode_defaults_true():
    """Singura exceptie deliberata - implicit True, nu False (siguranta
    implicita pentru orice sursa noua, UDAL_ARCHITECTURE_SPEC v1.0 §13)."""
    assert udal_config._DEFAULT_CONFIG["udal_shadow_mode_enabled"] is True


def test_shadow_mode_enabled_reads_true_by_default(monkeypatch):
    _mock_config(monkeypatch)
    assert udal_config.is_shadow_mode_enabled() is True


def test_shadow_mode_can_be_disabled_explicitly(monkeypatch):
    _mock_config(monkeypatch, {"udal_shadow_mode_enabled": False})
    assert udal_config.is_shadow_mode_enabled() is False


def test_udal_enabled_true_when_flag_set(monkeypatch):
    _mock_config(monkeypatch, {"udal_enabled": True})
    assert udal_config.is_udal_enabled() is True


def test_is_source_enabled_false_for_unknown_source(monkeypatch):
    _mock_config(monkeypatch)
    assert udal_config.is_source_enabled("pilot-ro-superliga") is False


def test_is_source_enabled_true_when_explicitly_listed(monkeypatch):
    _mock_config(monkeypatch, {"udal_source_enabled": {"pilot-ro-superliga": True}})
    assert udal_config.is_source_enabled("pilot-ro-superliga") is True
    assert udal_config.is_source_enabled("alta-sursa") is False


def test_default_config_all_flags_false_except_shadow_mode():
    for key, value in udal_config._DEFAULT_CONFIG.items():
        if key == "udal_shadow_mode_enabled":
            assert value is True
        elif key == "udal_source_enabled":
            assert value == {}
        else:
            assert value is False, f"{key} nu e implicit False"
