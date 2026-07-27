"""Teste pentru freelf_event_resolver.py — componentă reutilizabilă Sync
Layer (Sprint 1). Verifică: (1) deleagă la
oracle_api.resolve_freelf_finished_match_id(), nu reimplementă rezoluția;
(2) cache-uiește rezultatul (pozitiv ȘI negativ) — nu repetă un lookup deja
făcut pentru același meci; (3) reutilizează cache_manager generic (zero
tabelă nouă)."""
from __future__ import annotations

import freelf_event_resolver as mod


class _FakeApi:
    def __init__(self, return_value):
        self.calls: list = []
        self._return_value = return_value

    def resolve_freelf_finished_match_id(self, home, away, kickoff_date, league):
        self.calls.append((home, away, kickoff_date, league))
        return self._return_value


class _FakeCache:
    def __init__(self):
        self.store: dict = {}
        self.set_calls: list = []

    def get_raw(self, category, key):
        return self.store.get((category, key))

    def set(self, category, key, data, provider="unknown"):
        self.store[(category, key)] = data
        self.set_calls.append((category, key, data, provider))
        return True


def test_resolve_delegates_to_api_on_cache_miss():
    api = _FakeApi(42)
    cache = _FakeCache()
    resolver = mod.FreelfEventResolver(api=api, cache=cache)
    result = resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    assert result == 42
    assert len(api.calls) == 1


def test_resolve_caches_positive_result():
    api = _FakeApi(42)
    cache = _FakeCache()
    resolver = mod.FreelfEventResolver(api=api, cache=cache)
    resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    assert len(api.calls) == 1  # al doilea apel a lovit cache-ul


def test_resolve_caches_negative_result_too():
    """Un meci pentru care FreeLF nu are event_id nu trebuie re-interogat
    la fiecare rulare — cache-uit și eșecul, nu doar succesul."""
    api = _FakeApi(None)
    cache = _FakeCache()
    resolver = mod.FreelfEventResolver(api=api, cache=cache)
    r1 = resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    r2 = resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    assert r1 is None and r2 is None
    assert len(api.calls) == 1


def test_resolve_uses_generic_cache_category():
    api = _FakeApi(1)
    cache = _FakeCache()
    resolver = mod.FreelfEventResolver(api=api, cache=cache)
    resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    assert cache.set_calls[0][0] == "freelf_event_resolution"


def test_resolve_key_distinguishes_different_matches():
    api = _FakeApi(1)
    cache = _FakeCache()
    resolver = mod.FreelfEventResolver(api=api, cache=cache)
    resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    resolver.resolve("Liverpool", "Everton", "2026-01-01", "Premier League")
    assert len(api.calls) == 2  # meciuri diferite -> chei de cache diferite


def test_resolve_key_distinguishes_same_teams_different_dates():
    api = _FakeApi(1)
    cache = _FakeCache()
    resolver = mod.FreelfEventResolver(api=api, cache=cache)
    resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    resolver.resolve("Arsenal", "Chelsea", "2026-02-01", "Premier League")
    assert len(api.calls) == 2


def test_get_freelf_event_resolver_returns_singleton(monkeypatch):
    """Fără rețea — FootballOracleAPI() reală ar putea încerca I/O la
    construcție; izolăm complet componentele externe ale FreelfEventResolver."""
    monkeypatch.setattr(mod, "_resolver_instance", None)
    monkeypatch.setattr("oracle_api.FootballOracleAPI", lambda: _FakeApi(None))
    monkeypatch.setattr(mod, "get_cache", lambda: _FakeCache())
    r1 = mod.get_freelf_event_resolver()
    r2 = mod.get_freelf_event_resolver()
    assert r1 is r2
