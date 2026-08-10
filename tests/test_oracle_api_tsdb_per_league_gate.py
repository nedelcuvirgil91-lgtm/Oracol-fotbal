"""Test de regresie pentru BUG-014B (fix interimar, operațional, separat de
ADR-034): pasul 5 (TheSportsDB) din get_matches_for_week() trebuie să
folosească o condiție PER LIGĂ, nu globală (len(matches)<5).

Reproduce exact cazul real, verificat live 2026-07-18: World Cup 2026
produce ≥5 meciuri, Romania SuperLiga produce 0 înainte de TSDB — cu
gate-ul VECHI (global), TSDB nu era niciodată apelat pentru Romania. Acest
test pică pe codul vechi (verificat manual înainte de patch) și trece după
fix — urmează exact tiparul deja existent în
tests/test_oracle_api_apifootball_fallback.py (FootballOracleAPI.__new__,
ocolind rețeaua reală).

[REPARAT — 2026-08-10] Datele erau hardcodate la "2026-07-18" (ziua în
care testul a fost scris) — get_matches_for_week() filtrează rezultatele
la fereastra azi..azi+7, deci testele au început să pice silențios odată
ce "azi" a trecut de acea dată (test rot, nu bug de producție). Rescrise
cu date relative la date.today(), ca în test_oracle_api_scheduled_
fixtures_shadow.py. Adăugat și monkeypatch explicit pentru Level DB
(get_matches_for_week_from_history) și fallback-ul de ultimă instanță
(get_matches_for_week_from_scheduled_fixtures), ca testele să rămână
determinist izolate de orice client Supabase real (chiar dacă azi, fără
credențiale în sandbox, degradează oricum la gol)."""
from __future__ import annotations

from datetime import date

import oracle_api

_TODAY = date.today().isoformat()


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


def _no_db_fallback(monkeypatch):
    """Level DB + fallback-ul de ultimă instanță pe scheduled_fixtures —
    goale explicit, ca testul să exercite doar cascada live (obiectul
    acestui fișier)."""
    import database.queries as queries
    monkeypatch.setattr(queries, "get_matches_for_week_from_history", lambda comps, d_from, d_to: ([], set()))
    monkeypatch.setattr(queries, "get_matches_for_week_from_scheduled_fixtures", lambda leagues, d_from, d_to: ([], set()))


def test_tsdb_called_for_league_with_zero_matches_even_when_other_leagues_fill_global_threshold(monkeypatch):
    """Reproduce cazul real: World Cup 2026 (>=5 meciuri) + Romania
    SuperLiga (0 meciuri de la Odds API/FreeLF/football-data/ESPN) —
    TSDB TREBUIE apelat pentru Romania SuperLiga, indiferent de cate
    meciuri au adunat deja alte ligi."""
    _no_db_fallback(monkeypatch)
    api = _api_no_network()

    world_cup_matches = [{
        "fixture_id": f"wc_{i}", "home_team": f"WC-Home-{i}", "away_team": f"WC-Away-{i}",
        "kickoff_date": _TODAY, "kickoff_utc": f"{_TODAY}T{10+i}:00:00Z",
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
                "kickoff_date": _TODAY, "kickoff_utc": f"{_TODAY}T15:30:00Z",
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
    _no_db_fallback(monkeypatch)
    api = _api_no_network()

    def _fake_odds_api(sport_key: str, days_ahead: int = 7):
        if sport_key == "soccer_fifa_world_cup":
            return [{
                "fixture_id": "wc_1", "home_team": "France", "away_team": "England",
                "kickoff_date": _TODAY, "kickoff_utc": f"{_TODAY}T21:00:00Z",
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


def test_tsdb_not_called_for_romania_when_romania_already_has_a_match(monkeypatch):
    """Cazul cerut explicit la review: daca Romania SuperLiga ÎNSĂȘI are deja
    un meci (de ex. de la ESPN, cand va reveni sa acopere liga), TSDB nu
    trebuie apelat deloc pentru ea - fara apeluri irosite catre un provider
    de rezerva cand nu e nevoie."""
    _no_db_fallback(monkeypatch)
    api = _api_no_network()

    api._fetch_events_odds_api = lambda sport_key, days_ahead=7: []
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []

    def _fake_espn(league: str, target_date: str):
        if league == "Romania SuperLiga" and target_date == _TODAY:
            return [{
                "fixture_id": "espn_1", "home_team": "Oțelul Galați", "away_team": "CFR Cluj",
                "kickoff_date": _TODAY, "kickoff_utc": f"{_TODAY}T15:30:00Z",
                "league": "Romania SuperLiga", "source": "espn",
            }]
        return []

    api._fetch_matches_espn = _fake_espn

    tsdb_calls: list[str] = []

    def _fake_tsdb(league_id: str, league_name: str):
        tsdb_calls.append(league_name)
        return []

    api._fetch_matches_tsdb = _fake_tsdb

    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert "Romania SuperLiga" not in tsdb_calls, (
        f"TSDB nu ar trebui apelat pentru Romania SuperLiga - liga deja are meci de la ESPN. "
        f"Apeluri TSDB inregistrate: {tsdb_calls}"
    )
    romania_matches = [m for m in matches if m.get("league") == "Romania SuperLiga"]
    assert len(romania_matches) == 1
    assert romania_matches[0]["source"] == "espn"  # nu suprascris/duplicat de TSDB


def test_tsdb_gate_is_strictly_per_league_not_shared_across_leagues(monkeypatch):
    """Cerut explicit la review: patch-ul nu are voie sa afecteze
    comportamentul altor ligi (Premier League, La Liga etc). Trei ligi
    simultan, fiecare cu stare diferita - fiecare trebuie evaluata STRICT
    independent, fara nicio scurgere intre ele."""
    _no_db_fallback(monkeypatch)
    api = _api_no_network()

    def _fake_odds_api(sport_key: str, days_ahead: int = 7):
        # Doar Premier League are deja meci de la Odds API.
        if sport_key == "soccer_epl":
            return [{
                "fixture_id": "pl_1", "home_team": "Arsenal", "away_team": "Chelsea",
                "kickoff_date": _TODAY, "kickoff_utc": f"{_TODAY}T18:00:00Z",
                "league": "Premier League", "source": "the-odds-api",
            }]
        return []  # La Liga si Romania SuperLiga -> 0 de la Odds API

    api._fetch_events_odds_api = _fake_odds_api
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_espn = lambda league, target_date: []  # nimeni nu are de la ESPN

    tsdb_calls: list[str] = []

    def _fake_tsdb(league_id: str, league_name: str):
        tsdb_calls.append(league_name)
        if league_name == "La Liga":
            return [{
                "fixture_id": "ll_1", "home_team": "Real Madrid", "away_team": "Barcelona",
                "kickoff_date": _TODAY, "kickoff_utc": f"{_TODAY}T20:00:00Z",
                "league": "La Liga", "source": "thesportsdb",
            }]
        if league_name == "Romania SuperLiga":
            return [{
                "fixture_id": "ro_1", "home_team": "Oțelul Galați", "away_team": "CFR Cluj",
                "kickoff_date": _TODAY, "kickoff_utc": f"{_TODAY}T15:30:00Z",
                "league": "Romania SuperLiga", "source": "thesportsdb",
            }]
        return []

    api._fetch_matches_tsdb = _fake_tsdb

    matches = api.get_matches_for_week(
        days_ahead=7, competitions=["Premier League", "La Liga", "Romania SuperLiga"],
    )

    # Premier League deja avea meci -> TSDB NU apelat pentru ea.
    assert "Premier League" not in tsdb_calls
    # La Liga si Romania SuperLiga aveau 0 -> TSDB apelat pentru AMBELE,
    # independent, fara ca starea uneia sa influenteze cealalta.
    assert "La Liga" in tsdb_calls
    assert "Romania SuperLiga" in tsdb_calls

    by_league = {m.get("league"): m for m in matches if m.get("league") in
                 ("Premier League", "La Liga", "Romania SuperLiga")}
    assert by_league["Premier League"]["source"] == "the-odds-api"  # neschimbat
    assert by_league["La Liga"]["source"] == "thesportsdb"
    assert by_league["Romania SuperLiga"]["source"] == "thesportsdb"
