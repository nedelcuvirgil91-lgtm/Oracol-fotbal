"""
================================================================================
FOOTBALL ORACLE — Rate Limit Manager (R4.1, ADR-038)
================================================================================
Urmareste bugetul REAL (zilnic + per-minut) din header-ele oficiale de
raspuns API-Football (audit §5/§7, confirmat oficial de doua ori):
    x-ratelimit-requests-limit / x-ratelimit-requests-remaining  (zilnic)
    X-RateLimit-Limit / X-RateLimit-Remaining                    (per-minut)

Aditiv, nu redesign: aproximarea lunara existenta in key_manager.py
(key_manager.py:71-79, deja documentata acolo ca aproximare cunoscuta) ramane
neatinsa - acest modul e o sursa suplimentara de adevar, mai precisa, activa
DOAR dupa primul raspuns real care include header-ele. Fail-open pana atunci:
niciun comportament de azi nu se schimba pentru un provider care nu trimite
niciodata aceste header-e, sau inainte de primul apel real.

Stare in-memory, per proces - suficienta pentru un singur ciclu de sincronizare
(batch nocturn sau sesiune Streamlit); nu persista intre procese. Scop ingust,
confirmat de audit (§14): preveni depasirea sustinuta a plafonului per-minut
in interiorul UNUI singur proces care evalueaza mai multe meciuri la rand -
risc real, confirmat oficial ("access can be temporarily or permanently
blocked... without prior warning").

[ADAUGAT ADR-041 Faza 1] Clasa a fost ÎNTOTDEAUNA generică per `provider`
(`_state: dict[str, _ProviderRateState]`, nicio ramură hardcodată la
API-Football) — extinderea la Soccer Football Info
(`soccerfootballinfo_client.py`) nu a cerut nicio schimbare aici, doar un al
doilea apelant real prin `RequestManager` (același header-e
`x-ratelimit-*`, confirmate live 2026-07-27: 200/zi, 4/s). Orice provider
viitor care trece prin `RequestManager` capătă automat același gating, fără
cod nou în acest modul.
================================================================================
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("FootballOracle.RateLimitManager")

# Fereastra oficiala de reset a plafonului per-minut (confirmat oficial,
# audit §5: "10 requests per minute" pe planul Free).
_PER_MINUTE_WINDOW_SECONDS = 60.0

_DAILY_LIMIT_HEADER = "x-ratelimit-requests-limit"
_DAILY_REMAINING_HEADER = "x-ratelimit-requests-remaining"
_MINUTE_LIMIT_HEADER = "x-ratelimit-limit"
_MINUTE_REMAINING_HEADER = "x-ratelimit-remaining"


@dataclass
class _ProviderRateState:
    daily_limit: int | None = None
    daily_remaining: int | None = None
    daily_updated_at: float = 0.0
    minute_limit: int | None = None
    minute_remaining: int | None = None
    minute_updated_at: float = 0.0


def _first_int(headers, name: str) -> int | None:
    # Header-urile HTTP nu disting majuscule - `requests.Response.headers`
    # normalizeaza deja asta, dar nu presupunem (in teste poate fi un dict
    # simplu) - cautare case-insensitive explicita.
    if not headers:
        return None
    for k, v in headers.items():
        if k.lower() == name:
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
    return None


class RateLimitManager:
    """Sursa de adevar pentru buget REAL, per provider, din header-ele de
    raspuns - nu doar contorizare locala aproximativa."""

    def __init__(self):
        self._state: dict[str, _ProviderRateState] = {}

    def record_response_headers(self, provider: str, headers) -> None:
        if not headers:
            return
        state = self._state.setdefault(provider, _ProviderRateState())
        now = time.monotonic()

        daily_limit = _first_int(headers, _DAILY_LIMIT_HEADER)
        daily_remaining = _first_int(headers, _DAILY_REMAINING_HEADER)
        if daily_limit is not None:
            state.daily_limit = daily_limit
        if daily_remaining is not None:
            state.daily_remaining = daily_remaining
            state.daily_updated_at = now

        minute_limit = _first_int(headers, _MINUTE_LIMIT_HEADER)
        minute_remaining = _first_int(headers, _MINUTE_REMAINING_HEADER)
        if minute_limit is not None:
            state.minute_limit = minute_limit
        if minute_remaining is not None:
            state.minute_remaining = minute_remaining
            state.minute_updated_at = now

    def can_request(self, provider: str) -> bool:
        """"Ar trebui sa existe cererea?" (audit §4/§16), varianta de buget.
        Fail-open daca nu exista niciun header citit inca pentru acest
        provider - comportament neschimbat fata de azi pana la prima
        confirmare reala din raspuns."""
        state = self._state.get(provider)
        if state is None:
            return True
        if state.daily_remaining is not None and state.daily_remaining <= 0:
            logger.warning(
                "[RateLimit] %s: cota zilnica epuizata (confirmat din header), cererea e blocata.",
                provider,
            )
            return False
        if state.minute_remaining is not None and state.minute_remaining <= 0:
            age = time.monotonic() - state.minute_updated_at
            if age < _PER_MINUTE_WINDOW_SECONDS:
                logger.warning(
                    "[RateLimit] %s: plafon per-minut epuizat (confirmat din header, acum %.0fs), cererea e blocata.",
                    provider, age,
                )
                return False
        return True

    def status(self, provider: str) -> dict:
        state = self._state.get(provider)
        if state is None:
            return {"provider": provider, "known": False}
        return {
            "provider": provider, "known": True,
            "daily_limit": state.daily_limit, "daily_remaining": state.daily_remaining,
            "minute_limit": state.minute_limit, "minute_remaining": state.minute_remaining,
        }

    def reset(self) -> None:
        """Doar pentru teste - proces real traieste cat un ciclu de sync."""
        self._state = {}


_rlm_instance: RateLimitManager | None = None


def get_rate_limit_manager() -> RateLimitManager:
    global _rlm_instance
    if _rlm_instance is None:
        _rlm_instance = RateLimitManager()
    return _rlm_instance
