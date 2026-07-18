"""Test de regresie pentru BUG-014B (fix interimar, operațional, separat de
ADR-034): pasul 5 (TheSportsDB) din get_matches_for_week() trebuie să
folosească o condiție PER LIGĂ, nu globală (len(matches)<5).

Reproduce exact cazul real, verificat live 2026-07-18: World Cup 2026
produce ≥5 meciuri, Romania SuperLiga produce 0 înainte de TSDB — cu
gate-ul VECHI (global), TSDB nu era niciodată apelat pentru Romania. Acest
test pică pe codul vechi (verificat manual înainte de patch) și trece după
fix — urmează exact tiparul deja existent în
tests/test_oracle_api_apifootball_fallback.py (FootballOracleAPI.__new__,
ocolind rețeaua reală)."""
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
    api._fetch_matches_api_football = lambda league, date_from, date_to: []
    api._generate_demo_matches = lambda competitions: []
    api._attach_odds = lambda matches: matches
    return api


def test_tsdb_called_for_league_with_zero_matches_even_when_other_leagues_fill_global_threshold(monkeypatch):
    """Reproduce cazul real: World Cup 2026 (>=5 meciuri) + Romania
    SuperLiga (0 meciuri de la Odds API/FreeLF/football-data/ESPN) —
    TSDB TREBUIE apelat pentru Romania SuperLiga, indiferent de cate
    meciuri au adunat deja alte ligi."""
    api = _api_no_network()

    world_cup_matches = [{
        "fixture_id": f"wc_{i}", "home_team": f"WC-Home-{i}", "away_team": f"WC-Away-{i}",
        "kickoff_date": "2026-07-18", "kickoff_utc": f"2026-07-18T{10+i}:00:00Z",
        "league": "World Cup 2026", "source": "the-odds-api",
    } for i in range(6)]  # 6 meciuri - depaseste pragul vechi (5)

    def _fake_odds_api(sport_key: str, days_ahead: int = 7):
        if sport_key == "soccer_fifa_world_cup":
            return world_cup_matches
        return []  # Romania SuperLiga -> 0, exact ca in productie azi

    api._fetch_events_odds_api = _fake_odds_api
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_espn = lambda league, target_date: []  # ESPN gol, exact ca in productie azi

    tsdb_calls: list[tuple[str, str]] = []

    def _fake_tsdb(league_id: str, league_name: str):
        tsdb_calls.append((league_id, league_name))
        if league_name == "Romania SuperLiga":
            return [{
                "fixture_id": "tsdb_1", "home_team": "Oțelul Galați", "away_team": "CFR Cluj",
                "kickoff_date": "2026-07-18", "kickoff_utc": "2026-07-18T15:30:00Z",
                "league": "Romania SuperLiga", "source": "thesportsdb",
            }]
        return []

    api._fetch_matches_tsdb = _fake_tsdb

    matches = api.get_matches_for_week(days_ahead=7, competitions=["World Cup 2026", "Romania SuperLiga"])

    # TSDB TREBUIE apelat pentru Romania SuperLiga - inainte de patch, gate-ul
    # global (len(matches)<5, deja depasit de cele 6 meciuri World Cup) bloca
    # aceasta chemare complet.
    assert ("4691", "Romania SuperLiga") in tsdb_calls, (
        f"TSDB nu a fost apelat pentru Romania SuperLiga - gate-ul global inca "
        f"blocheaza pasul 5. Apeluri TSDB inregistrate: {tsdb_calls}"
    )

    romania_matches = [m for m in matches if m.get("league") == "Romania SuperLiga"]
    assert len(romania_matches) == 1
    assert romania_matches[0]["home_team"] == "Oțelul Galați"
    assert romania_matches[0]["away_team"] == "CFR Cluj"
    assert romania_matches[0]["source"] == "thesportsdb"


def test_tsdb_not_called_for_league_that_already_has_matches(monkeypatch):
    """Simetric fata de pasul 6 (API-Football): daca liga deja are meciuri
    de la providerii anteriori, TSDB nu mai e apelat pentru ea - evita
    apeluri irosite, exact tiparul existent la API-Football."""
    api = _api_no_network()

    def _fake_odds_api(sport_key: str, days_ahead: int = 7):
        if sport_key == "soccer_fifa_world_cup":
            return [{
                "fixture_id": "wc_1", "home_team": "France", "away_team": "England",
                "kickoff_date": "2026-07-18", "kickoff_utc": "2026-07-18T21:00:00Z",
                "league": "World Cup 2026", "source": "the-odds-api",
            }]
        return []

    api._fetch_events_odds_api = _fake_odds_api
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_espn = lambda league, target_date: []

    tsdb_calls: list[str] = []

    def _fake_tsdb(league_id: str, league_name: str):
        tsdb_calls.append(league_name)
        return []

    api._fetch_matches_tsdb = _fake_tsdb

    api.get_matches_for_week(days_ahead=7, competitions=["World Cup 2026"])

    assert "World Cup 2026" not in tsdb_calls, (
        "TSDB nu ar trebui apelat pentru World Cup 2026 - liga deja are meci de la Odds API"
    )
