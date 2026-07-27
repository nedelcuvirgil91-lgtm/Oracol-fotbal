"""
================================================================================
FOOTBALL ORACLE — Request Manager (R4.1, ADR-038)
================================================================================
Strat subtire care infasoara `ApiFootballProvider._get()` existent - NU il
rescrie. Adauga exact ce lipsea, confirmat de audit (§4/§7/§16):
    - L0 RAM cache (deduplicare in acelasi ciclu de evaluare / batch)
    - deduplicare cereri in-flight (aceeasi cheie, doi apelanti aproape
      simultani - defensiv, chiar daca executia curenta e single-threaded)
    - gating de buget real, prin RateLimitManager (rate_limit_manager.py)

Cache-ul disk+Supabase (L1/L2, cache_manager.py), coverage check
(football_providers._covered) si retry HTTP (urllib3.Retry) raman complet
neatinse - functioneaza deja, per regula "no defect, no rewrite" (ADR-038,
principiul 3). Scope inițial API-Football pentru R4.1 (cum a cerut misiunea),
dar clasa nu hardcodeaza numele providerului - parametrizata explicit, exact
ca extinderea la un al doilea provider (Soccer Football Info,
soccerfootballinfo_client.py, ADR-041 Faza 1) să fie o extensie prin
reutilizare, nu o rescriere. `RateLimitManager` (rate_limit_manager.py)
insusi e deja complet generic - stare `dict[str, _ProviderRateState]` cheiata
pe `provider`, fara nicio ramura hardcodata - orice provider nou care trece
prin `RequestManager` capata automat buget real per header-e, fara nicio
schimbare de cod in acest modul.
================================================================================
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock

from rate_limit_manager import get_rate_limit_manager

logger = logging.getLogger("FootballOracle.RequestManager")

# 5 minute - suficient pentru deduplicare in acelasi ciclu de evaluare
# (ex. aceeasi echipa apare in mai multe meciuri din acelasi batch), fara
# sa concureze cu TTL-urile reale de business din cache_manager.CATEGORY_TTL
# (ore/zile) - RAM ramane strict un nivel de deduplicare pe termen scurt,
# nu o sursa de adevar pe termen lung (aceea ramane L1/L2, neatinsa).
_RAM_TTL_SECONDS = 300.0


@dataclass
class _RamEntry:
    value: object
    expires_at: float


class RequestManager:
    """Gateway unic pentru cereri catre un provider - RAM cache + dedup
    in-flight + gating de buget, inainte ca apelul sa ajunga la cache-ul
    existent (L1/L2) sau la HTTP."""

    def __init__(self, rate_limiter=None):
        self._ram: dict[str, _RamEntry] = {}
        self._inflight: set[str] = set()
        self._lock = Lock()
        self._rate_limiter = rate_limiter

    @staticmethod
    def _ram_key(provider: str, category: str, key: str) -> str:
        return f"{provider}:{category}:{key}"

    def get_ram(self, provider: str, category: str, key: str):
        ram_key = self._ram_key(provider, category, key)
        entry = self._ram.get(ram_key)
        if entry is None:
            return None
        if time.monotonic() >= entry.expires_at:
            self._ram.pop(ram_key, None)
            return None
        return entry.value

    def set_ram(self, provider: str, category: str, key: str, value) -> None:
        if value is None:
            return
        ram_key = self._ram_key(provider, category, key)
        self._ram[ram_key] = _RamEntry(value=value, expires_at=time.monotonic() + _RAM_TTL_SECONDS)

    def should_request(self, provider: str) -> bool:
        """"Ar trebui sa existe cererea?" (audit §4/§16) - gating de buget,
        inainte de orice apel HTTP real. Fail-open daca nu exista rate
        limiter atasat (comportament neschimbat fata de azi)."""
        if self._rate_limiter is None:
            return True
        return self._rate_limiter.can_request(provider)

    def try_acquire_inflight(self, provider: str, category: str, key: str) -> bool:
        """True daca acest apel devine "owner"-ul cererii in-flight (poate
        continua spre cache L1/L2 + HTTP), False daca alt apelant e deja in
        curs pentru exact aceeasi cheie. Apelantul TREBUIE sa cheme
        `release_inflight` cu acelasi (provider, category, key) - de obicei
        din `finally`, ca sa nu ramana blocat permanent la eroare."""
        ram_key = self._ram_key(provider, category, key)
        with self._lock:
            if ram_key in self._inflight:
                return False
            self._inflight.add(ram_key)
            return True

    def release_inflight(self, provider: str, category: str, key: str) -> None:
        ram_key = self._ram_key(provider, category, key)
        with self._lock:
            self._inflight.discard(ram_key)

    def record_response_headers(self, provider: str, headers) -> None:
        if self._rate_limiter is not None:
            self._rate_limiter.record_response_headers(provider, headers)

    def record_result(
        self, provider: str, endpoint: str, success: bool, latency_ms: float,
        status_code: int | None = None, exc: Exception | None = None,
    ) -> None:
        """[ADAUGAT] ADR-041 Faza 1 — punct unic de scriere in provider_metrics
        pentru orice apel care trece prin RequestManager. oracle_api.py si
        football_providers.py apeleaza supabase_client.record_provider_call()
        direct, dinainte de acest modul — ramane neatins, nu se rescrie o cale
        deja functionala (regula "no defect, no rewrite", ADR-038). Orice
        adaptor NOU de Sync Layer (ADR-039) care trece prin RequestManager
        capata insa automat aceeasi scriere, fara sa reimplementeze un INSERT
        paralel — exact cerinta explicita: o singura cale de scriere pentru
        cod nou. Import leneș, best-effort — nu blocheaza fluxul daca
        Supabase e indisponibil (acelasi principiu de degradare gratioasa
        deja aplicat in tot proiectul).

        [ADAUGAT ADR-041 Faza 2, Sprint 1.1 #3] `status_code`/`exc` opționale
        — clasificate prin punctul unic reutilizat
        (provider_call_classification.classify_failure), doar la eșec."""
        try:
            failure_reason = None
            if not success:
                from provider_call_classification import classify_failure
                status_code, failure_reason = classify_failure(status_code, exc=exc)
            import supabase_client as _sb
            _sb.record_provider_call(provider, endpoint, success, latency_ms,
                                      http_status=status_code, failure_reason=failure_reason)
        except Exception:
            pass


_rm_instance: RequestManager | None = None


def get_request_manager() -> RequestManager:
    global _rm_instance
    if _rm_instance is None:
        _rm_instance = RequestManager(rate_limiter=get_rate_limit_manager())
    return _rm_instance
