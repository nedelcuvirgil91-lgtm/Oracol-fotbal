"""Teste pentru soccerfootballinfo_event_resolver.py (Sprint 1 v6, ADR-041
Faza 1) — tipar identic cu test_freelf_event_resolver.py. Fără rețea, client
injectat ca fake."""
from __future__ import annotations

import soccerfootballinfo_event_resolver as mod

_CHAMPIONSHIP_ID = "6250830696ec934"  # Romania SuperLiga la Soccer Football Info (verificat live)
_LEAGUE = "Romania SuperLiga"


class _FakeClient:
    def __init__(self, day_payload):
        self._day_payload = day_payload
        self.calls: list = []

    def get_matches_for_day(self, date_iso):
        self.calls.append(date_iso)
        return self._day_payload


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


def _day_payload(match_id="8f7fca2d606aef7f", status="ENDED",
                  championship_id=_CHAMPIONSHIP_ID, home="Dinamo Bucuresti", away="CS U Craiova"):
    return {"result": [{
        "id": match_id, "status": status,
        "championship": {"id": championship_id},
        "teamA": {"name": home}, "teamB": {"name": away},
    }]}


def test_resolve_delegates_to_client_on_cache_miss():
    client = _FakeClient(_day_payload())
    resolver = mod.SoccerFootballInfoEventResolver(client=client, cache=_FakeCache())
    result = resolver.resolve("Dinamo Bucuresti", "CS U Craiova", "2026-07-25", _LEAGUE)
    assert result == "8f7fca2d606aef7f"
    assert len(client.calls) == 1


def test_resolve_caches_positive_result():
    client = _FakeClient(_day_payload())
    resolver = mod.SoccerFootballInfoEventResolver(client=client, cache=_FakeCache())
    resolver.resolve("Dinamo Bucuresti", "CS U Craiova", "2026-07-25", _LEAGUE)
    resolver.resolve("Dinamo Bucuresti", "CS U Craiova", "2026-07-25", _LEAGUE)
    assert len(client.calls) == 1  # al doilea apel a lovit cache-ul


def test_resolve_caches_negative_result_too():
    client = _FakeClient({"result": []})
    resolver = mod.SoccerFootballInfoEventResolver(client=client, cache=_FakeCache())
    r1 = resolver.resolve("Dinamo Bucuresti", "CS U Craiova", "2026-07-25", _LEAGUE)
    r2 = resolver.resolve("Dinamo Bucuresti", "CS U Craiova", "2026-07-25", _LEAGUE)
    assert r1 is None and r2 is None
    assert len(client.calls) == 1


def test_resolve_uses_generic_cache_category():
    client = _FakeClient(_day_payload())
    cache = _FakeCache()
    resolver = mod.SoccerFootballInfoEventResolver(client=client, cache=cache)
    resolver.resolve("Dinamo Bucuresti", "CS U Craiova", "2026-07-25", _LEAGUE)
    assert cache.set_calls[0][0] == "soccerfootballinfo_event_resolution"


def test_resolve_returns_none_when_league_has_no_championship_id():
    """Ligă fără mapare Soccer Football Info (ex. Premier League, nu are
    provider_ids["soccerfootballinfo"]) — niciodată aproximat (Regula #8)."""
    client = _FakeClient(_day_payload())
    resolver = mod.SoccerFootballInfoEventResolver(client=client, cache=_FakeCache())
    result = resolver.resolve("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    assert result is None
    assert len(client.calls) == 0  # nici măcar nu apelează clientul fără championship_id


def test_resolve_returns_none_when_status_not_ended():
    client = _FakeClient(_day_payload(status="LIVE"))
    resolver = mod.SoccerFootballInfoEventResolver(client=client, cache=_FakeCache())
    result = resolver.resolve("Dinamo Bucuresti", "CS U Craiova", "2026-07-25", _LEAGUE)
    assert result is None


def test_resolve_returns_none_when_championship_id_does_not_match():
    client = _FakeClient(_day_payload(championship_id="other_id"))
    resolver = mod.SoccerFootballInfoEventResolver(client=client, cache=_FakeCache())
    result = resolver.resolve("Dinamo Bucuresti", "CS U Craiova", "2026-07-25", _LEAGUE)
    assert result is None


def test_resolve_returns_none_when_teams_do_not_match():
    client = _FakeClient(_day_payload())
    resolver = mod.SoccerFootballInfoEventResolver(client=client, cache=_FakeCache())
    result = resolver.resolve("FCSB", "Rapid Bucuresti", "2026-07-25", _LEAGUE)
    assert result is None


def test_get_soccerfootballinfo_event_resolver_returns_singleton(monkeypatch):
    monkeypatch.setattr(mod, "_resolver_instance", None)
    monkeypatch.setattr("soccerfootballinfo_client.get_soccerfootballinfo_client", lambda: _FakeClient(_day_payload()))
    monkeypatch.setattr(mod, "get_cache", lambda: _FakeCache())
    r1 = mod.get_soccerfootballinfo_event_resolver()
    r2 = mod.get_soccerfootballinfo_event_resolver()
    assert r1 is r2
