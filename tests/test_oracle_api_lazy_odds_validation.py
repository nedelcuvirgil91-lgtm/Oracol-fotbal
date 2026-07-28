"""Teste pentru Sprint 3, Pasul 4 — validarea cheii Odds API
(_validate_api_keys / /sports) devine LAZY, nu mai rulează necondiționat în
FootballOracleAPI.__init__().

GĂSIT LA AUDIT (provider_call_log, live): 100% din cele 94 apeluri Odds API
logate erau /sports (validare), 0% cerere reală de odds/events/scores —
fiindcă orice construcție de FootballOracleAPI() (inclusiv din adaptoare
Sync Layer care nu ating niciodată Odds API, ex. TsdbTeamStatsAdapter,
FreelfH2hAdapter) declanșa validarea necondiționat.

Cerințe verificate aici:
(1) constructorul e side-effect free — 0 apeluri externe la construcție;
(2) validarea rulează DOAR din cele 3 metode care chiar consumă Odds API
    (_fetch_events_odds_api, _fetch_scores_odds_api, _fetch_odds);
(3) idempotentă per-instanță — a doua metodă Odds API apelată pe aceeași
    instanță nu mai repetă /sports;
(4) comportament funcțional neschimbat (dead_keys/active_sport_keys tot se
    populează, doar mutat în timp)."""
from __future__ import annotations

import inspect

import oracle_api


def _bare_api() -> oracle_api.FootballOracleAPI:
    """Instanță minimă, fără rețea — pattern identic cu test_oracle_api_odds.py."""
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = None
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._active_sport_keys = set()
    api._odds_keys_validated = False
    from key_manager import get_key_manager
    api._key_manager = get_key_manager()
    return api


def test_init_source_never_calls_validate_api_keys_unconditionally():
    """Gardă statică, regresie directă: __init__ nu mai are voie să conțină
    un apel necondiționat la _validate_api_keys()."""
    source = inspect.getsource(oracle_api.FootballOracleAPI.__init__)
    assert "self._validate_api_keys()" not in source, (
        "FootballOracleAPI.__init__ apelează încă _validate_api_keys() "
        "necondiționat — constructorul trebuie să rămână side-effect free "
        "(Sprint 3, Pasul 4)."
    )


def test_real_construction_triggers_zero_odds_api_calls(monkeypatch):
    """Construcție REALĂ (__init__, nu __new__) — 0 apeluri către
    _validate_api_keys()/Odds API, dovedit prin counter pe metoda de clasă."""
    calls: list[int] = []
    monkeypatch.setattr(
        oracle_api.FootballOracleAPI, "_validate_api_keys",
        lambda self: calls.append(1),
    )
    oracle_api.FootballOracleAPI()
    assert calls == []


def test_ensure_odds_keys_validated_calls_validate_exactly_once_per_instance():
    api = _bare_api()
    calls: list[int] = []
    api._validate_api_keys = lambda: calls.append(1)

    api._ensure_odds_keys_validated()
    api._ensure_odds_keys_validated()
    api._ensure_odds_keys_validated()

    assert len(calls) == 1
    assert api._odds_keys_validated is True


def test_fetch_events_odds_api_triggers_lazy_validation():
    api = _bare_api()
    calls: list[int] = []
    api._validate_api_keys = lambda: calls.append(1)
    api._get = lambda *a, **kw: None  # fără rețea reală pentru cererea propriu-zisă

    api._fetch_events_odds_api("soccer_epl")

    assert len(calls) == 1


def test_fetch_scores_odds_api_triggers_lazy_validation():
    api = _bare_api()
    calls: list[int] = []
    api._validate_api_keys = lambda: calls.append(1)
    api._get = lambda *a, **kw: None

    api._fetch_scores_odds_api("soccer_epl")

    assert len(calls) == 1


def test_fetch_odds_triggers_lazy_validation():
    api = _bare_api()
    calls: list[int] = []
    api._validate_api_keys = lambda: calls.append(1)
    api._get = lambda *a, **kw: None

    api._fetch_odds("soccer_epl")

    assert len(calls) == 1


def test_multiple_odds_methods_on_same_instance_validate_only_once():
    """Idempotență cross-metodă: _fetch_events_odds_api() urmat de
    _fetch_scores_odds_api() pe ACEEAȘI instanță nu repetă /sports."""
    api = _bare_api()
    calls: list[int] = []
    api._validate_api_keys = lambda: calls.append(1)
    api._get = lambda *a, **kw: None

    api._fetch_events_odds_api("soccer_epl")
    api._fetch_scores_odds_api("soccer_epl")
    api._fetch_odds("soccer_epl")

    assert len(calls) == 1


def test_tsdb_team_stats_adapter_construction_generates_zero_odds_api_traffic(monkeypatch):
    """Dovadă directă, cerută explicit: un adaptor care NU folosește
    niciodată Odds API (TheSportsDB team stats, R-Sync-8) nu mai declanșează
    nicio validare/cerere Odds API doar prin construcție."""
    from tsdb_team_stats_adapter import TsdbTeamStatsAdapter

    calls: list[int] = []
    monkeypatch.setattr(
        oracle_api.FootballOracleAPI, "_validate_api_keys",
        lambda self: calls.append(1),
    )
    TsdbTeamStatsAdapter()
    assert calls == []


def test_freelf_h2h_adapter_construction_generates_zero_odds_api_traffic(monkeypatch):
    """Aceeași dovadă pentru FreelfH2hAdapter (R-Sync-9) — H2H FreeLF nu
    atinge niciodată Odds API."""
    from freelf_h2h_adapter import FreelfH2hAdapter

    calls: list[int] = []
    monkeypatch.setattr(
        oracle_api.FootballOracleAPI, "_validate_api_keys",
        lambda self: calls.append(1),
    )
    FreelfH2hAdapter()
    assert calls == []


def test_dead_keys_still_populated_after_lazy_validation():
    """Comportament funcțional neschimbat: _dead_keys/_active_sport_keys tot
    se populează din _validate_api_keys() — doar momentul se mută, nu
    efectul."""
    api = _bare_api()

    def _fake_validate():
        api._active_sport_keys = {"soccer_epl"}
        api._dead_keys.add("soccer_laliga")

    api._validate_api_keys = _fake_validate
    api._get = lambda *a, **kw: None

    api._fetch_odds("soccer_laliga")  # deja "dead" după validare -> shortcircuit

    assert api._odds_keys_validated is True
    assert "soccer_laliga" in api._dead_keys
