"""Teste pentru gating-ul universal (should_request) + înregistrarea
automată de header-e (record_response_headers) din oracle_api.py::_get(),
și pentru throttling-ul static al TheSportsDB — Phase 4 Functional
Completion, punctul 1 (eliminarea fail-open din RateLimitManager pentru cei
5 provideri neconectați: TheSportsDB, WeatherAPI, The Odds API,
eloratings.net, football-data.org).

Header-ele reale folosite mai jos (x-requests-remaining, x-weatherapi-qpm-
left) sunt confirmate live prin POC dedicat
(sync/poc_rate_limit_headers_check.py, rulare GitHub Actions 30831280759,
2026-08-03), nu presupuse."""
from __future__ import annotations

import oracle_api


class _FakeResp:
    def __init__(self, payload=None, ok=True, status_code=200, headers=None):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self.headers = headers if headers is not None else {}

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, resp=None):
        self._resp = resp
        self.calls: list[str] = []

    def get(self, url, headers=None, params=None, timeout=12):
        self.calls.append(url)
        return self._resp


class _FakeRequestManager:
    def __init__(self, allow_request: bool = True):
        self._allow_request = allow_request
        self.should_request_calls: list[str] = []
        self.recorded_headers: list[tuple] = []

    def should_request(self, provider):
        self.should_request_calls.append(provider)
        return self._allow_request

    def record_response_headers(self, provider, headers):
        self.recorded_headers.append((provider, headers))


def _api(session: _FakeSession, request_manager) -> oracle_api.FootballOracleAPI:
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = session
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._request_manager = request_manager
    return api


def test_get_records_headers_automatically_for_detected_provider():
    """Fara return_headers=True, fara cod suplimentar la apelant — _get()
    recunoaste providerul din URL si alimenteaza RateLimitManager singur."""
    headers = {"x-requests-remaining": "484", "x-requests-used": "16"}
    session = _FakeSession(_FakeResp({"ok": True}, headers=headers))
    rm = _FakeRequestManager()
    api = _api(session, rm)

    data = api._get(f"{oracle_api.ODDS_API_URL}/sports/soccer_epl/scores", params={"apiKey": "x"})

    assert data == {"ok": True}
    assert rm.recorded_headers == [("oddsapi", headers)]


def test_get_blocks_request_before_http_when_should_request_false():
    session = _FakeSession(_FakeResp({"ok": True}))
    rm = _FakeRequestManager(allow_request=False)
    api = _api(session, rm)

    data = api._get(f"{oracle_api.ODDS_API_URL}/sports/soccer_epl/scores", params={"apiKey": "x"})

    assert data is None
    assert session.calls == []  # niciun apel HTTP real facut
    assert rm.should_request_calls == ["oddsapi"]


def test_get_gating_is_fail_open_without_request_manager():
    """Dublurile de test existente (FootballOracleAPI.__new__ fara
    _request_manager) trebuie sa ramana neafectate — comportament identic
    cu inainte de generalizare."""
    session = _FakeSession(_FakeResp({"ok": True}))
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = session
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()

    data = api._get(f"{oracle_api.ODDS_API_URL}/sports/soccer_epl/scores", params={"apiKey": "x"})

    assert data == {"ok": True}
    assert session.calls == [f"{oracle_api.ODDS_API_URL}/sports/soccer_epl/scores"]


def test_get_recording_no_crash_when_fake_response_has_no_headers_attr():
    """_FakeResp-uri mai vechi, fara atribut `headers` (folosite in alte
    fisiere de test) nu trebuie sa provoace crash acum ca record_response_
    headers e apelat universal."""
    class _NoHeadersResp:
        def __init__(self):
            self.ok = True
            self.status_code = 200
        def json(self):
            return {"ok": True}

    class _Session:
        def get(self, url, headers=None, params=None, timeout=12):
            return _NoHeadersResp()

    rm = _FakeRequestManager()
    api = _api(_Session(), rm)

    data = api._get(f"{oracle_api.ODDS_API_URL}/sports/soccer_epl/scores", params={"apiKey": "x"})

    assert data == {"ok": True}
    # Niciun crash - getattr(r, "headers", None) intoarce None, record_response_headers
    # primeste None (RateLimitManager real face no-op pe None, testat separat in test_rate_limit_manager.py).
    assert rm.recorded_headers == [("oddsapi", None)]


def test_thesportsdb_static_throttle_interval_documented():
    assert oracle_api._STATIC_THROTTLE_INTERVAL_SECONDS.get("thesportsdb") == 1.0


def test_thesportsdb_static_throttle_enforced_between_consecutive_calls(monkeypatch):
    """A doua cerere TSDB, imediat dupa prima, trebuie sa astepte pana la
    intervalul static configurat — verificat prin monkeypatch pe time.sleep
    (fara sa astepte efectiv in test)."""
    oracle_api._static_throttle_last_call.clear()
    session = _FakeSession(_FakeResp({"results": []}))
    api = _api(session, _FakeRequestManager())

    sleeps: list[float] = []
    monkeypatch.setattr(oracle_api.time, "sleep", lambda s: sleeps.append(s))

    api._get(f"{oracle_api.THESPORTSDB_URL}/eventslast.php", params={"id": "1"})
    assert sleeps == []  # primul apel din proces - elapsed uriaș, fara asteptare

    api._get(f"{oracle_api.THESPORTSDB_URL}/eventslast.php", params={"id": "1"})
    assert len(sleeps) == 1
    assert 0 < sleeps[0] <= 1.0
