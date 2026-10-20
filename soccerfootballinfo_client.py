"""
================================================================================
FOOTBALL ORACLE — Soccer Football Info Client (Sync Layer, ADR-041 Faza 1)
================================================================================
Module: soccerfootballinfo_client.py

Adaptor HTTP pentru Soccer Football Info (RapidAPI) — Owner nou pentru Match
Statistics (Sprint 1 v6, §2/§3), verificat live 2026-07-27 (POC izolat,
șters după test — vezi CHANGELOG). NU e conectat la FootballOracleEngine —
strict Sync Layer (ADR-039, principiul 1: servirea live nu depinde niciodată
de infrastructura de sincronizare/învățare).

Ordinea obligatorie a oricărei cereri, identică cu
`football_providers.ApiFootballProvider._get()` (tipar deja dovedit, nu
reinventat): health check (key_manager) → L0 RAM cache (Request Manager) →
L1/L2 cache (cache_manager) → gating de buget (should_request) → dedup
in-flight → HTTP → record_request + record_response_headers → record_result
(ADR-041 Faza 1, punctul unic de scriere în `provider_metrics` pentru cod NOU
de Sync Layer — vezi `request_manager.RequestManager.record_result`) →
scriere cache la succes.

Două endpoint-uri, confirmate live:
    - `matches/day/full`  — toate meciurile globale pentru o zi (1 apel), NU
      conține xG/lineup (confirmat live, POC dedicat).
    - `matches/view/full` — un singur meci, conține TOT (stats/xG/lineup/
      manageri/arbitru/stadion/evenimente/dominance_index).
================================================================================
"""
from __future__ import annotations

import logging
import time

from cache_manager import get_cache
from key_manager import get_key_manager
from request_manager import get_request_manager

logger = logging.getLogger("FootballOracle.SyncLayer.SoccerFootballInfoClient")

PROVIDER_ID = "soccerfootballinfo"
BASE_URL = "https://soccer-football-info.p.rapidapi.com"

# [ADAUGAT 2026-10-20 — instrumentare, NU reparatie]
# `provider_call_log` arata 75 de apeluri, 0 reusite, 100% HTTP 400, intre
# 11 si 19 octombrie. Ultimul succes (din `api_cache`) e 10 oct 08:20:04;
# primul 400 logat e 11 oct 08:37:03 — deci ruptura e incadrata in ~24h, iar
# `git log` nu are NICIUN commit intre 8 si 12 oct, deci nu e o schimbare
# de-a noastra. Ce lipsea ca sa stim DE CE: corpul raspunsului. Codul logheaza
# doar statusul, iar un 400 de la RapidAPI isi spune motivul in corp
# ("You are not subscribed to this API", parametru respins, plan expirat) —
# distinctii care cer remedii DIFERITE.
#
# Se logheaza doar corpul RASPUNSULUI, niciodata cererea sau header-ele: cheia
# RapidAPI circula exclusiv in header-ul de cerere, deci nu poate ajunge aici.
# Trunchiat, fiindcă un HTML de eroare poate avea kilobytes.
_LUNGIME_MAXIMA_CORP_DIAGNOSTIC = 400


def _corp_diagnostic(resp) -> str:
    """Corpul unui raspuns eșuat, trunchiat si pe o singura linie.

    Nu arunca NICIODATA: e chemata pe calea de eroare, deci o excepție aici ar
    masca defectul pe care tocmai incearca sa-l explice."""
    try:
        text = resp.text or ""
    except Exception:  # pragma: no cover — corp necitibil (conexiune rupta)
        return "<corp necitibil>"
    text = " ".join(text.split())
    if not text:
        return "<corp gol>"
    if len(text) > _LUNGIME_MAXIMA_CORP_DIAGNOSTIC:
        return text[:_LUNGIME_MAXIMA_CORP_DIAGNOSTIC] + "…[trunchiat]"
    return text


class SoccerFootballInfoClient:
    """Client generic — NU cunoaște normalizarea către `match_history`
    (asta trăiește în adaptor, `soccerfootballinfo_match_statistics_adapter.py`).
    Strict fetch + cache + rate limiting, tiparul deja dovedit de
    `ApiFootballProvider._get()`."""

    def __init__(self, key_manager=None, cache=None, request_manager=None):
        self._key_manager = key_manager or get_key_manager()
        self._cache = cache or get_cache()
        self._request_manager = request_manager or get_request_manager()
        self._session = None  # lazy — nu deschidem conexiuni la import

    def _get_session(self):
        if self._session is None:
            from requests import Session
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry
            s = Session()
            r = Retry(total=3, backoff_factor=0.5,
                      status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=["GET"], raise_on_status=False)
            a = HTTPAdapter(max_retries=r)
            s.mount("https://", a); s.mount("http://", a)
            self._session = s
        return self._session

    def _healthy(self) -> bool:
        return self._key_manager.is_available(PROVIDER_ID)

    def _get(self, path: str, params: dict, cache_category: str, cache_key: str) -> dict | None:
        if not self._healthy():
            logger.debug("[SoccerFootballInfo] provider indisponibil (fără cheie activă) — sar peste %s", path)
            return None

        ram_hit = self._request_manager.get_ram(PROVIDER_ID, cache_category, cache_key)
        if ram_hit is not None:
            return ram_hit

        cached = self._cache.get_raw(cache_category, cache_key)
        if cached is not None:
            self._request_manager.set_ram(PROVIDER_ID, cache_category, cache_key, cached)
            return cached

        if not self._request_manager.should_request(PROVIDER_ID):
            return None

        acquired = self._request_manager.try_acquire_inflight(PROVIDER_ID, cache_category, cache_key)
        if not acquired:
            logger.debug("[SoccerFootballInfo] cerere deja în curs pentru %s/%s — sar peste duplicat", cache_category, cache_key)
            return None

        try:
            headers = self._key_manager.get_headers(PROVIDER_ID)
            if headers is None:
                return None

            start = time.monotonic()
            success = False
            data = None
            response_headers = None
            status_code = None
            caught_exc = None
            try:
                session = self._get_session()
                resp = session.get(f"{BASE_URL}/{path}", headers=headers, params=params, timeout=12)
                success = resp.ok
                status_code = resp.status_code
                response_headers = resp.headers
                if success:
                    data = resp.json()
                else:
                    logger.warning("[SoccerFootballInfo] HTTP %s pentru %s — corp: %s",
                                   resp.status_code, path, _corp_diagnostic(resp))
            except Exception as exc:
                logger.error("[SoccerFootballInfo] Eroare request %s: %s", path, exc)
                caught_exc = exc
            latency_ms = (time.monotonic() - start) * 1000

            self._key_manager.record_request(PROVIDER_ID)
            if response_headers is not None:
                self._request_manager.record_response_headers(PROVIDER_ID, response_headers)

            # ADR-041 Faza 1 — punct unic de scriere pentru cod NOU de Sync
            # Layer. [ADAUGAT ADR-041 Faza 2, Sprint 1.1 #3] status_code/exc
            # -- clasificate de RequestManager.record_result() insusi.
            self._request_manager.record_result(PROVIDER_ID, path, success, latency_ms,
                                                  status_code=status_code, exc=caught_exc)

            if success and data is not None:
                self._cache.set(cache_category, cache_key, data, provider=PROVIDER_ID)
                self._request_manager.set_ram(PROVIDER_ID, cache_category, cache_key, data)

            return data
        finally:
            self._request_manager.release_inflight(PROVIDER_ID, cache_category, cache_key)

    def get_matches_for_day(self, date_iso: str) -> dict | None:
        """`date_iso`: "YYYY-MM-DD". Un singur apel — toate meciurile globale
        din acea zi (confirmat live). NU conține xG/lineup (vezi docstring-ul
        modulului) — folosit strict pentru rezoluția match_id (vezi
        `soccerfootballinfo_event_resolver.py`)."""
        compact = date_iso.replace("-", "")
        return self._get("matches/day/full/", {"d": compact}, "soccerfootballinfo_day_full", compact)

    def get_match_detail(self, match_id: str) -> dict | None:
        """Conține TOT (stats/xG/lineup/manageri/arbitru/stadion) — confirmat
        live pe un meci real (Dinamo București 5-1 CS U Craiova, 2026-07-25)."""
        payload = self._get("matches/view/full/", {"i": match_id}, "soccerfootballinfo_match_detail", str(match_id))
        if not payload:
            return None
        result = payload.get("result")
        if not result:
            return None
        return result[0] if isinstance(result, list) else result


_client_instance: SoccerFootballInfoClient | None = None


def get_soccerfootballinfo_client() -> SoccerFootballInfoClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = SoccerFootballInfoClient()
    return _client_instance
