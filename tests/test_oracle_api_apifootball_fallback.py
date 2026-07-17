"""Teste pentru pasul 6 (API-Football fallback) din oracle_api.get_matches_for_week()
— fără rețea reală, urmând tiparul din test_oracle_api_odds.py (FootballOracleAPI.__new__,
ocolind _validate_api_keys()). Confirmă: (1) mecanismul e generic (condus de
mappings.API_FOOTBALL_LEAGUE_IDS, nu de nume de ligă hardcodat), (2) se declanșează
DOAR pentru ligi fără niciun meci de la providerii de mai sus, (3) nu afectează
ligile care deja au meciuri."""
from __future__ import annotations

import oracle_api


def _api_no_network() -> oracle_api.FootballOracleAPI:
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._freelf_exhausted = False
    api._active_sport_keys = set()
    api._api_football = None
    api._key_manager = None
    # Toți ceilalți provideri — surdinizați complet, ca să izolăm pasul 6.
    api._fetch_events_odds_api = lambda sport_key, days_ahead=7: []
    api._fetch_freelf_matches  = lambda target, league: []
    api._fetch_matches_fd      = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_espn    = lambda league, target_date: []
    api._fetch_matches_tsdb    = lambda league_id, league_name: []
    api._generate_demo_matches = lambda competitions: []
    api._attach_odds           = lambda matches: matches
    return api


def test_api_football_fallback_called_for_league_with_no_other_matches(monkeypatch):
    api = _api_no_network()
    calls = []

    def _fake_fetch(league, date_from, date_to):
        calls.append(league)
        return [{
            "fixture_id": "apifootball_1", "home_team": "FCSB", "away_team": "CFR Cluj",
            "kickoff_date": date_from, "kickoff_utc": f"{date_from}T18:00:00Z",
            "league": league, "source": "apifootball",
        }]

    api._fetch_matches_api_football = _fake_fetch
    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert calls == ["Romania SuperLiga"]
    assert len(matches) == 1
    assert matches[0]["source"] == "apifootball"


def test_api_football_fallback_skipped_when_league_not_in_mappings(monkeypatch):
    """Genericitate: o liga fara provider_ids["api_football"] in mappings.py
    nu declanseaza niciun apel — comportament condus DOAR de mappings.py."""
    api = _api_no_network()
    calls = []
    api._fetch_matches_api_football = lambda league, date_from, date_to: calls.append(league) or []

    api.get_matches_for_week(days_ahead=7, competitions=["Premier League"])

    assert calls == []


def test_api_football_fallback_skipped_when_league_already_has_matches(monkeypatch):
    """Daca un alt provider deja a gasit meciuri pentru acea liga, API-Football
    NU mai e apelat — evita cereri inutile (consum minim de quota)."""
    api = _api_no_network()
    api._fetch_matches_espn = lambda league, target_date: (
        [{"fixture_id": "espn_1", "home_team": "FCSB", "away_team": "CFR Cluj",
          "kickoff_date": target_date, "kickoff_utc": f"{target_date}T18:00:00Z",
          "league": league, "source": "espn"}]
        if league == "Romania SuperLiga" and target_date == __import__("datetime").date.today().isoformat()
        else []
    )
    calls = []
    api._fetch_matches_api_football = lambda league, date_from, date_to: calls.append(league) or []

    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert calls == []
    assert any(m["source"] == "espn" for m in matches)


def test_real_fetch_api_football_zero_http_calls_for_plan_restricted_league():
    """Integrare reala (nu stub) a _fetch_matches_api_football -> ApiFootballProvider
    -> _covered(): pentru Romania SuperLiga (supported="plan_restricted"), 0
    cereri HTTP - gate-ul de coverage opreste inainte de orice request.
    Confirma "0 cereri irosite" prin cod, nu doar prin comentariu."""
    import key_manager
    from football_providers import ApiFootballProvider

    api = _api_no_network()
    api._api_football = ApiFootballProvider(key_manager=key_manager.get_key_manager())
    http_calls = []
    api._api_football._get = lambda *a, **kw: http_calls.append(a) or {"response": []}

    result = api._fetch_matches_api_football("Romania SuperLiga", "2026-07-17", "2026-07-24")

    assert result == []
    assert http_calls == []
