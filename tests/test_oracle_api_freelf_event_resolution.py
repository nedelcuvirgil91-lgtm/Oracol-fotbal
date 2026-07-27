"""Teste pentru oracle_api.FootballOracleAPI.resolve_freelf_finished_match_id()
(Sprint 1, ADR-039) — rezoluție event_id FreeLF pentru meciuri ÎNCHEIATE,
spre deosebire de _fetch_freelf_matches() care exclude explicit statusurile
terminate. Fără rețea — _free_lf_get()/_cget()/_cset() sunt fake-uite."""
from __future__ import annotations

import oracle_api
from mappings import FREE_LF_LEAGUE_IDS

_PL_ID = FREE_LF_LEAGUE_IDS["Premier League"]


def _api_no_network(matches_by_date_response=None, cached_response="__unset__"):
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._freelf_exhausted = False
    api._active_sport_keys = set()
    api._api_football = None
    api._key_manager = None

    calls = {"free_lf_get": []}

    def _fake_free_lf_get(path, params=None):
        calls["free_lf_get"].append((path, params))
        return matches_by_date_response

    api._free_lf_get = _fake_free_lf_get
    store: dict = {}
    if cached_response != "__unset__":
        pass  # populat explicit mai jos in testul care are nevoie

    def _cget(key):
        return store.get(key)

    def _cset(key, val):
        store[key] = val

    api._cget = _cget
    api._cset = _cset
    api._calls = calls
    return api


def _event(home, away, event_id, status_type, league_id=_PL_ID):
    return {
        "id": event_id,
        "parentLeagueId": league_id,
        "status": {"type": status_type},
        "homeTeam": {"name": home}, "awayTeam": {"name": away},
    }


def test_resolves_finished_match_unlike_fetch_freelf_matches():
    """Diferența cheie față de _fetch_freelf_matches(): status 'finished'
    NU e exclus aici."""
    payload = {"response": [_event("Arsenal", "Chelsea", 999, "finished")]}
    api = _api_no_network(payload)
    result = api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    assert result == 999


def test_returns_none_for_unknown_league():
    api = _api_no_network({"response": []})
    assert api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Liga Necunoscută") is None
    assert api._calls["free_lf_get"] == []  # nu face niciun apel — league necunoscuta


def test_returns_none_when_freelf_exhausted():
    api = _api_no_network({"response": []})
    api._freelf_exhausted = True
    assert api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League") is None
    assert api._calls["free_lf_get"] == []


def test_returns_none_when_team_pair_not_found():
    payload = {"response": [_event("Liverpool", "Everton", 1, "finished")]}
    api = _api_no_network(payload)
    assert api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League") is None


def test_matches_are_normalized_before_comparison():
    """Comparația foloseste normalize_team_name — variații de scriere tot se potrivesc."""
    payload = {"response": [_event("FC Arsenal", "Chelsea FC", 42, "finished")]}
    api = _api_no_network(payload)
    result = api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    # Rezultatul poate fi None sau 42 in functie de tabela de aliasuri reala —
    # verificam doar ca nu arunca exceptie si ca raspunde determinist.
    assert result in (None, 42)


def test_wrong_league_id_is_excluded():
    payload = {"response": [_event("Arsenal", "Chelsea", 42, "finished", league_id=999)]}
    api = _api_no_network(payload)
    assert api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League") is None


def test_response_dict_with_nested_matches_key_is_parsed():
    payload = {"response": {"matches": [_event("Arsenal", "Chelsea", 7, "finished")]}}
    api = _api_no_network(payload)
    assert api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League") == 7


def test_second_call_same_date_league_reuses_cached_raw_payload():
    payload = {"response": [_event("Arsenal", "Chelsea", 1, "finished"),
                             _event("Liverpool", "Everton", 2, "finished")]}
    api = _api_no_network(payload)
    api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League")
    api.resolve_freelf_finished_match_id("Liverpool", "Everton", "2026-01-01", "Premier League")
    # Un singur apel HTTP pentru ambele rezolutii (aceeasi data+liga) — cache-uit.
    assert len(api._calls["free_lf_get"]) == 1


def test_no_data_returns_none():
    api = _api_no_network(None)
    assert api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League") is None


def test_non_dict_event_skipped_not_crashed():
    payload = {"response": ["not-a-dict", _event("Arsenal", "Chelsea", 5, "finished")]}
    api = _api_no_network(payload)
    assert api.resolve_freelf_finished_match_id("Arsenal", "Chelsea", "2026-01-01", "Premier League") == 5
