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
    def __init__(self, payload=None, ok=True, status_code=200, text=""):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self.headers = {}
        self.text = text

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


# ════════════════════════════════════════════════════════════════════════════
# INSTRUMENTARE 2026-10-20 — corpul raspunsului la eșec
#
# De ce exista: 75 de apeluri, 0 reusite, 100% HTTP 400 intre 11 si 19 oct, iar
# codul logheaza doar STATUSUL. Un 400 de la RapidAPI isi spune motivul in corp,
# iar motivele cer remedii DIFERITE ("not subscribed" -> audit de cheie;
# parametru respins -> reparatie la noi). Fara corp, nu se poate decide.
# ════════════════════════════════════════════════════════════════════════════

def test_corpul_raspunsului_ajunge_in_log_la_eșec(caplog):
    """Garda centrala: motivul trebuie sa fie VIZIBIL, nu doar codul."""
    import logging
    corp = '{"message":"You are not subscribed to this API."}'
    client = _client_with_session(_FakeSession(resp=_FakeResp(ok=False, status_code=400, text=corp)))
    with caplog.at_level(logging.WARNING, logger="FootballOracle.SyncLayer.SoccerFootballInfoClient"):
        client.get_matches_for_day("2026-01-01")
    mesaje = " ".join(r.getMessage() for r in caplog.records)
    assert "not subscribed" in mesaje, "motivul respingerii trebuie sa apara in log"
    assert "400" in mesaje


def test_cheia_nu_poate_ajunge_in_log(caplog):
    """Contrapondere de securitate: se logheaza corpul RASPUNSULUI, niciodata
    cererea. Cheia circula doar in header-ul de cerere (`_FakeKeyManager` o
    pune ca "fake"), deci nu are cale spre log — verificat, nu presupus."""
    import logging
    client = _client_with_session(_FakeSession(resp=_FakeResp(ok=False, status_code=400, text="refuzat")))
    with caplog.at_level(logging.WARNING, logger="FootballOracle.SyncLayer.SoccerFootballInfoClient"):
        client.get_matches_for_day("2026-01-01")
    mesaje = " ".join(r.getMessage() for r in caplog.records)
    assert "fake" not in mesaje
    assert "x-rapidapi-key" not in mesaje


def test_corp_lung_e_trunchiat():
    """Un HTML de eroare poate avea kilobytes; log-ul de noapte are deja
    peste 100.000 de linii."""
    from soccerfootballinfo_client import _corp_diagnostic, _LUNGIME_MAXIMA_CORP_DIAGNOSTIC
    rezultat = _corp_diagnostic(_FakeResp(text="x" * 5000))
    assert len(rezultat) <= _LUNGIME_MAXIMA_CORP_DIAGNOSTIC + len("…[trunchiat]")
    assert rezultat.endswith("…[trunchiat]")


def test_corp_pe_o_singura_linie():
    """Un corp cu linii noi ar rupe o singura intrare de log in mai multe,
    facand-o ne-grepabila."""
    from soccerfootballinfo_client import _corp_diagnostic
    rezultat = _corp_diagnostic(_FakeResp(text="prima\n\nlinie   \t a doua\n"))
    assert "\n" not in rezultat
    assert rezultat == "prima linie a doua"


def test_corp_gol_e_numit_explicit():
    """Regula #8 — o stare necunoscuta rămâne explicit numita, nu se confunda
    cu un corp care chiar lipsește."""
    from soccerfootballinfo_client import _corp_diagnostic
    assert _corp_diagnostic(_FakeResp(text="")) == "<corp gol>"


def test_corp_necitibil_nu_arunca():
    """Chemata pe calea de EROARE: o excepție aici ar masca exact defectul pe
    care incearca sa-l explice."""
    from soccerfootballinfo_client import _corp_diagnostic

    class _RespRupt:
        @property
        def text(self):
            raise OSError("conexiune inchisa inainte de corp")

    assert _corp_diagnostic(_RespRupt()) == "<corp necitibil>"


def test_succesul_nu_logheaza_corpul(caplog):
    """Instrumentarea e strict pe calea de eșec — altfel fiecare apel reusit ar
    adauga pana la 400 de caractere in log, degeaba."""
    import logging
    client = _client_with_session(
        _FakeSession(resp=_FakeResp({"result": []}, ok=True, status_code=200, text="corp-de-succes")))
    with caplog.at_level(logging.WARNING, logger="FootballOracle.SyncLayer.SoccerFootballInfoClient"):
        client.get_matches_for_day("2026-01-01")
    mesaje = " ".join(r.getMessage() for r in caplog.records)
    assert "corp-de-succes" not in mesaje


def test_instrumentarea_nu_schimba_valoarea_intoarsa():
    """Zero schimbare de comportament: un eșec intoarce in continuare None, un
    succes intoarce in continuare payload-ul."""
    eșec = _client_with_session(_FakeSession(resp=_FakeResp(ok=False, status_code=400, text="x")))
    assert eșec.get_matches_for_day("2026-01-01") is None
    succes = _client_with_session(_FakeSession(resp=_FakeResp({"result": [1]}, ok=True, status_code=200, text="x")))
    assert succes.get_matches_for_day("2026-01-02") == {"result": [1]}
