"""
================================================================================
FOOTBALL ORACLE — Soccer Football Info Event Resolver (Sync Layer, ADR-041 Faza 1)
================================================================================
Rezolvă `match_id`-ul Soccer Football Info pentru un meci deja ÎNCHEIAT —
tipar identic cu `freelf_event_resolver.py` (decizie explicită, proprietar
produs: niciun adaptor nu reimplementă propria logică de rezoluție).

Nu duplică apelul HTTP — deleagă la
`soccerfootballinfo_client.SoccerFootballInfoClient.get_matches_for_day()`
(unde trăiește deja cache-ul L1/L2 al răspunsului brut per zi — un singur
apel acoperă toate meciurile globale ale zilei, reutilizat pentru orice număr
de rezoluții din aceeași zi, ex. backfill). Acest modul adaugă un nivel
separat de cache — rezoluția PER MECI — pentru că `match_id`-ul, odată
rezolvat, e un identificator STABIL (tratat identic cu `event_id`-ul FreeLF).
================================================================================
"""
from __future__ import annotations

import logging

from cache_manager import get_cache
from mappings import LEAGUE_PROVIDERS, normalize_team_name

logger = logging.getLogger("FootballOracle.SyncLayer.SoccerFootballInfoEventResolver")

CATEGORY = "soccerfootballinfo_event_resolution"
PROVIDER_ID = "soccerfootballinfo"


def _resolution_key(home_team: str, away_team: str, kickoff_date: str, league: str) -> str:
    home = normalize_team_name(home_team)
    away = normalize_team_name(away_team)
    return f"{league}|{home}|{away}|{kickoff_date}"


def _championship_id(league: str) -> str | None:
    league_def = LEAGUE_PROVIDERS.get(league)
    if league_def is None:
        return None
    return league_def.provider_ids.get(PROVIDER_ID)


class SoccerFootballInfoEventResolver:
    """Serviciu Sync Layer. `resolve()` e singurul punct de intrare — orice
    adaptor viitor care are nevoie de `match_id` Soccer Football Info pentru
    un meci încheiat îl apelează pe acesta, nu reimplementă rezoluția proprie."""

    def __init__(self, client=None, cache=None):
        if client is None:
            from soccerfootballinfo_client import get_soccerfootballinfo_client
            client = get_soccerfootballinfo_client()
        self._client = client
        self._cache = cache or get_cache()

    def resolve(self, home_team: str, away_team: str, kickoff_date: str, league: str) -> str | None:
        """Întoarce `match_id` (str) sau `None` (necunoscut — niciodată
        aproximat, Regula #8). Cache-uiește și rezultatul negativ, ca să nu
        repete inutil un lookup deja eșuat pentru același meci."""
        key = _resolution_key(home_team, away_team, kickoff_date, league)
        cached = self._cache.get_raw(CATEGORY, key)
        if cached is not None and isinstance(cached, dict) and "match_id" in cached:
            return cached["match_id"]

        match_id = self._resolve_live(home_team, away_team, kickoff_date, league)
        self._cache.set(CATEGORY, key, {"match_id": match_id}, provider=PROVIDER_ID)
        return match_id

    def _resolve_live(self, home_team: str, away_team: str, kickoff_date: str, league: str) -> str | None:
        championship_id = _championship_id(league)
        if championship_id is None:
            logger.debug("[SoccerFootballInfoEventResolver] ligă fără championship_id SFI: %r", league)
            return None

        payload = self._client.get_matches_for_day(kickoff_date)
        if not payload:
            return None
        matches = payload.get("result") or []
        if not isinstance(matches, list):
            return None

        home_norm = normalize_team_name(home_team)
        away_norm = normalize_team_name(away_team)

        for match in matches:
            championship = match.get("championship") or {}
            if str(championship.get("id")) != str(championship_id):
                continue
            if match.get("status") != "ENDED":
                continue
            team_a = (match.get("teamA") or {}).get("name", "")
            team_b = (match.get("teamB") or {}).get("name", "")
            if normalize_team_name(team_a) == home_norm and normalize_team_name(team_b) == away_norm:
                return match.get("id")
        return None


_resolver_instance: SoccerFootballInfoEventResolver | None = None


def get_soccerfootballinfo_event_resolver() -> SoccerFootballInfoEventResolver:
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = SoccerFootballInfoEventResolver()
    return _resolver_instance
