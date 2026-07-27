"""
================================================================================
FOOTBALL ORACLE — FreeLF Event Resolver (Sync Layer, componentă reutilizabilă)
================================================================================
Rezolvă `event_id`-ul FreeLF pentru un meci deja ÎNCHEIAT — nevoie comună
oricărui viitor adaptor care depinde de acest ID (Match Statistics, azi;
Lineups/Injuries/Referees/Player Statistics, ulterior). Punct unic — niciun
adaptor nu reimplementă propria logică de rezoluție (decizie explicită,
proprietar produs, Sprint 1).

Nu duplică apelul HTTP — deleagă integral la
`oracle_api.FootballOracleAPI.resolve_freelf_finished_match_id()` (unde
trăiește deja cache-ul L1/L2 al răspunsului brut per dată+ligă). Acest
modul adaugă un nivel separat de cache — rezoluția PER MECI (nu per
dată+ligă) — pentru că `event_id`-ul, odată rezolvat, e un identificator
STABIL (tratat identic cu `team_id`, cf. audit Stable Identifiers,
API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md §10) — nu se re-rezolvă niciodată
inutil pentru același meci.

Reutilizează `cache_manager.CacheManager` (L1 disc + L2 Supabase, deja
generic — tabela `api_cache`) — zero migrare nouă, zero tabelă nouă.
================================================================================
"""
from __future__ import annotations

import logging

from cache_manager import get_cache
from mappings import normalize_team_name

logger = logging.getLogger("FootballOracle.SyncLayer.FreelfEventResolver")

CATEGORY = "freelf_event_resolution"


def _resolution_key(home_team: str, away_team: str, kickoff_date: str, league: str) -> str:
    home = normalize_team_name(home_team)
    away = normalize_team_name(away_team)
    return f"{league}|{home}|{away}|{kickoff_date}"


class FreelfEventResolver:
    """Serviciu Sync Layer. `resolve()` e singurul punct de intrare — orice
    adaptor viitor care are nevoie de `event_id` FreeLF pentru un meci
    încheiat îl apelează pe acesta, nu reimplementă rezoluția proprie."""

    def __init__(self, api=None, cache=None):
        if api is None:
            from oracle_api import FootballOracleAPI
            api = FootballOracleAPI()
        self._api = api
        self._cache = cache or get_cache()

    def resolve(self, home_team: str, away_team: str, kickoff_date: str, league: str) -> int | None:
        """Întoarce `event_id` (int) sau `None` (necunoscut — niciodată
        aproximat, Regula #8). Cache-uiește și rezultatul negativ, ca să nu
        repete inutil un lookup deja eșuat pentru același meci."""
        key = _resolution_key(home_team, away_team, kickoff_date, league)
        cached = self._cache.get_raw(CATEGORY, key)
        if cached is not None and isinstance(cached, dict) and "event_id" in cached:
            return cached["event_id"]

        event_id = self._api.resolve_freelf_finished_match_id(home_team, away_team, kickoff_date, league)
        self._cache.set(CATEGORY, key, {"event_id": event_id}, provider="freelivefootball")
        return event_id


_resolver_instance: FreelfEventResolver | None = None


def get_freelf_event_resolver() -> FreelfEventResolver:
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = FreelfEventResolver()
    return _resolver_instance
