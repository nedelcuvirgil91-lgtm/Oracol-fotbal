"""Teste pentru soccerfootballinfo_client.py (Sprint 1 v6, ADR-041 Faza 1).
Fără rețea — key_manager/cache/request_manager injectate ca fake-uri, tipar
identic cu test_football_providers.py (gating de sănătate/buget verificat
fără niciun apel HTTP real)."""
from __future__ import annotations

from soccerfootballinfo_client import SoccerFootballInfoClient


class _FakeKeyManager:
    def __init__(self, healthy=True):
        self._healthy = healthy

    def is_available(self, provider_id):
        return self._healthy

    def get_headers(self, provider_id):
        return {"x-rapidapi-key": "fake"}

    def record_request(self, provider_id):
        pass


class _FakeCache:
    def __init__(self, store=None):
        self.store = store or {}

    def get_raw(self, category, key):
        return self.store.get((category, key))

    def set(self, category, key, data, provider="unknown"):
        self.store[(category, key)] = data
        return True


class _FakeRequestManager:
    def __init__(self, should_request=True):
        self._should_request = should_request
        self.recorded_results: list = []

    def get_ram(self, provider, category, key):
        return None

    def set_ram(self, provider, category, key, value):
        pass

    def should_request(self, provider):
        return self._should_request

    def try_acquire_inflight(self, provider, category, key):
        return True

    def release_inflight(self, provider, category, key):
        pass

    def record_response_headers(self, provider, headers):
        pass

    def record_result(self, provider, endpoint, success, latency_ms, status_code=None, exc=None):
        self.recorded_results.append((provider, endpoint, success, latency_ms, status_code, exc))


def _client(healthy=True, cache_store=None, should_request=True):
    return SoccerFootballInfoClient(
        key_manager=_FakeKeyManager(healthy=healthy),
        cache=_FakeCache(store=cache_store),
        request_manager=_FakeRequestManager(should_request=should_request),
    )


def test_unhealthy_provider_blocks_request_without_http():
    client = _client(healthy=False)
    assert client.get_matches_for_day("2026-01-01") is None


def test_cache_hit_returns_cached_payload_without_http():
    cached_payload = {"result": [{"id": "abc123", "status": "ENDED"}]}
    client = _client(cache_store={("soccerfootballinfo_day_full", "20260101"): cached_payload})
    assert client.get_matches_for_day("2026-01-01") == cached_payload


def test_get_matches_for_day_uses_compact_date_as_cache_key():
    cached_payload = {"result": []}
    client = _client(cache_store={("soccerfootballinfo_day_full", "20260315"): cached_payload})
    assert client.get_matches_for_day("2026-03-15") == cached_payload


def test_should_request_false_blocks_when_no_cache_hit():
    client = _client(cache_store={}, should_request=False)
    assert client.get_matches_for_day("2026-01-01") is None


def test_get_match_detail_unwraps_result_list():
    cached_payload = {"result": [{"id": "8f7fca2d606aef7f", "referee": {"name": "Istvan Kovacs"}}]}
    client = _client(cache_store={("soccerfootballinfo_match_detail", "8f7fca2d606aef7f"): cached_payload})
    detail = client.get_match_detail("8f7fca2d606aef7f")
    assert detail == {"id": "8f7fca2d606aef7f", "referee": {"name": "Istvan Kovacs"}}


def test_get_match_detail_returns_none_when_result_missing():
    client = _client(cache_store={("soccerfootballinfo_match_detail", "unknown"): {"result": []}})
    assert client.get_match_detail("unknown") is None


class _FakeResp:
    def __init__(self, payload=None, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    def get(self, url, headers=None, params=None, timeout=12):
        if self._exc is not None:
            raise self._exc
        return self._resp


def _client_with_session(session, request_manager=None):
    client = SoccerFootballInfoClient(
        key_manager=_FakeKeyManager(healthy=True),
        cache=_FakeCache(store={}),
        request_manager=request_manager or _FakeRequestManager(should_request=True),
    )
    client._session = session  # ocolește _get_session() -- sesiune deja "deschisă"
    return client


def test_429_forwarded_to_record_result_with_status_code():
    """[ADR-041 Faza 2, Sprint 1.1 #3] status_code/exc ajung la
    RequestManager.record_result(), care le clasifică (429 -> quota)."""
    rm = _FakeRequestManager(should_request=True)
    client = _client_with_session(_FakeSession(resp=_FakeResp(ok=False, status_code=429)), request_manager=rm)
    client.get_matches_for_day("2026-01-01")
    assert len(rm.recorded_results) == 1
    _, _, success, _, status_code, exc = rm.recorded_results[0]
    assert success is False
    assert status_code == 429
    assert exc is None


def test_connection_exception_forwarded_to_record_result():
    import requests
    rm = _FakeRequestManager(should_request=True)
    client = _client_with_session(_FakeSession(exc=requests.exceptions.ConnectionError("refused")), request_manager=rm)
    client.get_matches_for_day("2026-01-01")
    assert len(rm.recorded_results) == 1
    _, _, success, _, status_code, exc = rm.recorded_results[0]
    assert success is False
    assert status_code is None
    assert isinstance(exc, requests.exceptions.ConnectionError)


def test_success_forwarded_with_status_code_and_no_exception():
    rm = _FakeRequestManager(should_request=True)
    client = _client_with_session(_FakeSession(resp=_FakeResp({"result": []}, ok=True, status_code=200)), request_manager=rm)
    client.get_matches_for_day("2026-01-01")
    _, _, success, _, status_code, exc = rm.recorded_results[0]
    assert success is True
    assert status_code == 200
    assert exc is None


def test_get_soccerfootballinfo_client_returns_singleton(monkeypatch):
    import soccerfootballinfo_client as mod
    monkeypatch.setattr(mod, "_client_instance", None)
    c1 = mod.get_soccerfootballinfo_client()
    c2 = mod.get_soccerfootballinfo_client()
    assert c1 is c2
