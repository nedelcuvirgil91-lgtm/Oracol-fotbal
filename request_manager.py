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
principiul 3). Scope strict API-Football pentru R4.1 (cum a cerut misiunea),
dar clasa nu hardcodeaza numele providerului - parametrizata explicit, ca
o eventuala extindere la alt provider sa fie o extensie, nu o rescriere.
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


_rm_instance: RequestManager | None = None


def get_request_manager() -> RequestManager:
    global _rm_instance
    if _rm_instance is None:
        _rm_instance = RequestManager(rate_limiter=get_rate_limit_manager())
    return _rm_instance
