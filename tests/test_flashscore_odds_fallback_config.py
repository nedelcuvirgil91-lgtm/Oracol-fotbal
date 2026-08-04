"""Teste pentru flashscore_odds_fallback_config.py (ADR-043) — fără rețea,
Supabase mock-uit prin monkeypatch (niciun apel real)."""
from __future__ import annotations

import flashscore_odds_fallback_config


def test_is_enabled_false_by_default_when_supabase_unavailable(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))
    assert flashscore_odds_fallback_config.is_enabled() is False


def test_is_enabled_true_when_flag_set_in_config(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: {"flashscore_odds_fallback_enabled": True})
    assert flashscore_odds_fallback_config.is_enabled() is True


def test_is_enabled_false_when_key_absent_from_remote_config(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: {"some_other_flag": True})
    assert flashscore_odds_fallback_config.is_enabled() is False


def test_default_config_flag_is_false():
    assert flashscore_odds_fallback_config._DEFAULT_CONFIG == {"flashscore_odds_fallback_enabled": False}
