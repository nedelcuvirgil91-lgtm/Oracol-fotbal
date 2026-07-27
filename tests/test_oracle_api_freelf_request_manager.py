"""Teste pentru integrarea FreeLF în Request Manager/Rate Limit Manager
(ADR-039, R-Sync-6) — decizie explicită, proprietar produs: „Nu accept
provideri care ocolesc infrastructura generică introdusă în R4.1".

FreeLF era singurul provider din oracle_api.py care ocolea complet
Request Manager (confirmat, audit R-Sync-6) — aceste teste dovedesc
mecanic că `_free_lf_get()` acum trece prin RAM cache (L0), dedup
in-flight și gating de buget, exact tiparul deja dovedit în
ApiFootballProvider._get() (R4.1)."""
from __future__ import annotations

import oracle_api


class _FakeResp:
    def __init__(self, payload, ok=True, status_code=200, headers=None):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, responses: list[_FakeResp] | None = None):
        self._responses = list(responses or [])
        self.calls: list[str] = []

    def get(self, url, headers=None, params=None, timeout=12):
        self.calls.append(url)
        if self._responses:
            return self._responses.pop(0)
        return _FakeResp(None, ok=False, status_code=404)


class _FakeRequestManager:
    """Dublură care înregistrează exact ce metode i se cer — echivalentul
    unui `Mock` scris manual, ca să nu introducem o dependință nouă."""

    def __init__(self, allow_request: bool = True, ram_hit=None, inflight_free: bool = True):
        self._allow_request = allow_request
        self._ram_hit = ram_hit
        self._inflight_free = inflight_free
        self.calls: list[tuple] = []

    def get_ram(self, provider, category, key):
        self.calls.append(("get_ram", provider, category, key))
        return self._ram_hit

    def set_ram(self, provider, category, key, value):
        self.calls.append(("set_ram", provider, category, key, value))

    def should_request(self, provider):
        self.calls.append(("should_request", provider))
        return self._allow_request

    def try_acquire_inflight(self, provider, category, key):
        self.calls.append(("try_acquire_inflight", provider, category, key))
        return self._inflight_free

    def release_inflight(self, provider, category, key):
        self.calls.append(("release_inflight", provider, category, key))

    def record_response_headers(self, provider, headers):
        self.calls.append(("record_response_headers", provider, headers))


def _api(session: _FakeSession, request_manager: _FakeRequestManager) -> oracle_api.FootballOracleAPI:
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = session
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._freelf_exhausted = False
    api._request_manager = request_manager
    from key_manager import get_key_manager
    api._key_manager = get_key_manager()
    return api


def test_free_lf_get_checks_ram_cache_before_http():
    session = _FakeSession()
    rm = _FakeRequestManager(ram_hit={"cached": True})
    api = _api(session, rm)

    result = api._free_lf_get("football-get-standing-all", {"leagueid": 1})

    assert result == {"cached": True}
    assert session.calls == []  # RAM hit -> nicio cerere HTTP reală
    assert ("get_ram", "freelivefootball", "freelf_raw", "football-get-standing-all:{'leagueid': 1}") in rm.calls


def test_free_lf_get_blocked_by_budget_gate():
    session = _FakeSession([_FakeResp({"data": "should not be reached"})])
    rm = _FakeRequestManager(allow_request=False)
    api = _api(session, rm)

    result = api._free_lf_get("football-get-standing-all", {"leagueid": 1})

    assert result is None
    assert session.calls == []  # bugetul blochează ÎNAINTE de orice apel HTTP
    assert any(c[0] == "should_request" for c in rm.calls)


def test_free_lf_get_blocked_by_inflight_dedup():
    session = _FakeSession([_FakeResp({"data": "should not be reached"})])
    rm = _FakeRequestManager(inflight_free=False)
    api = _api(session, rm)

    result = api._free_lf_get("football-get-standing-all", {"leagueid": 1})

    assert result is None
    assert session.calls == []


def test_free_lf_get_records_response_headers_on_real_call():
    headers = {"x-ratelimit-requests-limit": "100", "x-ratelimit-requests-remaining": "42"}
    session = _FakeSession([_FakeResp({"standing": []}, headers=headers)])
    rm = _FakeRequestManager()
    api = _api(session, rm)

    result = api._free_lf_get("football-get-standing-all", {"leagueid": 1})

    assert result == {"standing": []}
    assert len(session.calls) == 1
    header_calls = [c for c in rm.calls if c[0] == "record_response_headers"]
    assert header_calls == [("record_response_headers", "freelivefootball", headers)]


def test_free_lf_get_stores_successful_response_in_ram():
    session = _FakeSession([_FakeResp({"standing": ["x"]})])
    rm = _FakeRequestManager()
    api = _api(session, rm)

    api._free_lf_get("football-get-standing-all", {"leagueid": 1})

    set_ram_calls = [c for c in rm.calls if c[0] == "set_ram"]
    assert len(set_ram_calls) == 1
    assert set_ram_calls[0][4] == {"standing": ["x"]}


def test_free_lf_get_releases_inflight_even_on_failure():
    session = _FakeSession([_FakeResp(None, ok=False, status_code=500)])
    rm = _FakeRequestManager()
    api = _api(session, rm)

    result = api._free_lf_get("football-get-standing-all", {"leagueid": 1})

    assert result is None
    release_calls = [c for c in rm.calls if c[0] == "release_inflight"]
    assert len(release_calls) == 1


def test_football_oracle_api_init_wires_request_manager():
    """Regresie de integrare: constructorul real (__init__) trebuie să
    apeleze get_request_manager() și să seteze self._request_manager —
    nu doar testele care îl injectează manual peste __new__."""
    import inspect

    source = inspect.getsource(oracle_api.FootballOracleAPI.__init__)
    assert "self._request_manager = get_request_manager()" in source


def test_free_lf_get_uses_freelivefootball_as_provider_id():
    """Regresie directă: cheia de provider folosită pentru RAM/buget/
    header-e e 'freelivefootball' — aceeași folosită deja de key_manager
    (self._key_manager.get_headers('freelivefootball')), nu un identificator
    nou, paralel."""
    session = _FakeSession([_FakeResp({"standing": []})])
    rm = _FakeRequestManager()
    api = _api(session, rm)

    api._free_lf_get("football-get-standing-all", {"leagueid": 1})

    providers_used = {c[1] for c in rm.calls if len(c) > 1}
    assert providers_used == {"freelivefootball"}
