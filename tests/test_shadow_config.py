"""Teste pentru shadow_config.py (ADR-034, PR5) — fără rețea, Supabase
mock-uit prin monkeypatch (niciun apel real)."""
from __future__ import annotations

import shadow_config


def test_is_enabled_false_by_default_when_supabase_unavailable(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))
    assert shadow_config.is_enabled() is False


def test_is_enabled_true_when_flag_set_in_config(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: {"selection_engine_shadow_enabled": True})
    assert shadow_config.is_enabled() is True


def test_is_enabled_false_when_key_absent_from_remote_config(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: {"some_other_flag": True})
    assert shadow_config.is_enabled() is False


def test_default_config_flag_is_false():
    assert shadow_config._DEFAULT_CONFIG == {"selection_engine_shadow_enabled": False}
