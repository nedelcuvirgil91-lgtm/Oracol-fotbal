"""Teste pentru clasificarea eșecurilor HTTP (429/403/timeout/5xx) în
oracle_api.py::_get()/_record_metric() (ADR-041 Faza 2, Sprint 1.1 #3) —
fără rețea reală, mock direct pe self._s.get(), tiparul din
test_oracle_api_odds.py."""
from __future__ import annotations

import requests

import oracle_api


class _FakeResp:
    def __init__(self, payload=None, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

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


def _api(session: _FakeSession) -> oracle_api.FootballOracleAPI:
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = session
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    return api


_URL = oracle_api.ESPN_API_URL + "/eng.1/scoreboard"


def test_404_recorded_with_status_code_no_failure_reason_needed(monkeypatch):
    calls = []
    monkeypatch.setattr("supabase_client.record_provider_call",
                         lambda *a, **kw: (calls.append((a, kw)), True)[1])
    api = _api(_FakeSession(resp=_FakeResp(ok=False, status_code=404)))
    api._get(_URL)
    _, kwargs = calls[0]
    assert kwargs["http_status"] == 404
    assert kwargs["failure_reason"] == "other_error"


def test_403_classified_as_forbidden(monkeypatch):
    calls = []
    monkeypatch.setattr("supabase_client.record_provider_call",
                         lambda *a, **kw: (calls.append((a, kw)), True)[1])
    api = _api(_FakeSession(resp=_FakeResp(ok=False, status_code=403)))
    api._get(_URL)
    _, kwargs = calls[0]
    assert kwargs["http_status"] == 403
    assert kwargs["failure_reason"] == "forbidden"


def test_429_classified_as_quota(monkeypatch):
    calls = []
    monkeypatch.setattr("supabase_client.record_provider_call",
                         lambda *a, **kw: (calls.append((a, kw)), True)[1])
    api = _api(_FakeSession(resp=_FakeResp(ok=False, status_code=429)))
    api._get(_URL)
    _, kwargs = calls[0]
    assert kwargs["http_status"] == 429
    assert kwargs["failure_reason"] == "quota"


def test_502_classified_as_upstream_5xx(monkeypatch):
    calls = []
    monkeypatch.setattr("supabase_client.record_provider_call",
                         lambda *a, **kw: (calls.append((a, kw)), True)[1])
    api = _api(_FakeSession(resp=_FakeResp(ok=False, status_code=502)))
    api._get(_URL)
    _, kwargs = calls[0]
    assert kwargs["http_status"] == 502
    assert kwargs["failure_reason"] == "upstream_5xx"


def test_timeout_exception_classified_as_timeout(monkeypatch):
    calls = []
    monkeypatch.setattr("supabase_client.record_provider_call",
                         lambda *a, **kw: (calls.append((a, kw)), True)[1])
    api = _api(_FakeSession(exc=requests.exceptions.ReadTimeout("read timed out")))
    api._get(_URL)
    _, kwargs = calls[0]
    assert kwargs["http_status"] is None
    assert kwargs["failure_reason"] == "timeout"


def test_connection_error_classified_as_network(monkeypatch):
    calls = []
    monkeypatch.setattr("supabase_client.record_provider_call",
                         lambda *a, **kw: (calls.append((a, kw)), True)[1])
    api = _api(_FakeSession(exc=requests.exceptions.ConnectionError("refused")))
    api._get(_URL)
    _, kwargs = calls[0]
    assert kwargs["http_status"] is None
    assert kwargs["failure_reason"] == "network"


def test_success_recorded_with_status_code_no_failure_reason(monkeypatch):
    calls = []
    monkeypatch.setattr("supabase_client.record_provider_call",
                         lambda *a, **kw: (calls.append((a, kw)), True)[1])
    api = _api(_FakeSession(resp=_FakeResp({"ok": True}, ok=True, status_code=200)))
    api._get(_URL)
    _, kwargs = calls[0]
    assert kwargs["http_status"] == 200
    assert kwargs["failure_reason"] is None
