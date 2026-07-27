"""Teste pentru clasificarea eșecurilor HTTP (429/403/timeout/5xx) în
football_providers.py::ApiFootballProvider._get() (ADR-041 Faza 2, Sprint
1.1 #3) — fără rețea reală, mock direct pe sesiune, request_manager fake
care permite mereu cererea."""
from __future__ import annotations

import requests

from football_providers import ApiFootballProvider


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


class _FakeKeyManager:
    def is_available(self, provider_id):
        return True

    def get_headers(self, provider_id):
        return {"x-apisports-key": "fake"}

    def record_request(self, provider_id):
        pass


class _FakeCache:
    def get_raw(self, category, key):
        return None

    def set(self, category, key, data, provider="unknown"):
        return True


class _AlwaysAllowRequestManager:
    def get_ram(self, provider, category, key):
        return None

    def set_ram(self, provider, category, key, value):
        pass

    def should_request(self, provider):
        return True

    def try_acquire_inflight(self, provider, category, key):
        return True

    def release_inflight(self, provider, category, key):
        pass

    def record_response_headers(self, provider, headers):
        pass


def _provider_with_session(session) -> ApiFootballProvider:
    p = ApiFootballProvider(key_manager=_FakeKeyManager(), cache=_FakeCache(),
                             request_manager=_AlwaysAllowRequestManager())
    p._session = session  # ocolește _get_session() -- sesiune deja "deschisă"
    return p


def _call_and_capture(monkeypatch, session):
    calls = []
    monkeypatch.setattr("supabase_client.record_provider_call",
                         lambda *a, **kw: (calls.append((a, kw)), True)[1])
    p = _provider_with_session(session)
    p._get("fixtures", {}, "matches", "test-key")
    return calls[0][1]  # kwargs


def test_429_classified_as_quota(monkeypatch):
    kwargs = _call_and_capture(monkeypatch, _FakeSession(resp=_FakeResp(ok=False, status_code=429)))
    assert kwargs["http_status"] == 429
    assert kwargs["failure_reason"] == "quota"


def test_403_classified_as_forbidden(monkeypatch):
    kwargs = _call_and_capture(monkeypatch, _FakeSession(resp=_FakeResp(ok=False, status_code=403)))
    assert kwargs["http_status"] == 403
    assert kwargs["failure_reason"] == "forbidden"


def test_503_classified_as_upstream_5xx(monkeypatch):
    kwargs = _call_and_capture(monkeypatch, _FakeSession(resp=_FakeResp(ok=False, status_code=503)))
    assert kwargs["http_status"] == 503
    assert kwargs["failure_reason"] == "upstream_5xx"


def test_timeout_classified_as_timeout(monkeypatch):
    kwargs = _call_and_capture(monkeypatch, _FakeSession(exc=requests.exceptions.ConnectTimeout("timed out")))
    assert kwargs["http_status"] is None
    assert kwargs["failure_reason"] == "timeout"


def test_connection_error_classified_as_network(monkeypatch):
    kwargs = _call_and_capture(monkeypatch, _FakeSession(exc=requests.exceptions.ConnectionError("refused")))
    assert kwargs["http_status"] is None
    assert kwargs["failure_reason"] == "network"


def test_success_has_status_code_and_no_failure_reason(monkeypatch):
    kwargs = _call_and_capture(monkeypatch, _FakeSession(resp=_FakeResp({"response": []}, ok=True, status_code=200)))
    assert kwargs["http_status"] == 200
    assert kwargs["failure_reason"] is None
