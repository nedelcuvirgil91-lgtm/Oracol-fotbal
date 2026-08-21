"""Teste pentru fallback-ul de ULTIMĂ INSTANȚĂ pe scheduled_fixtures din
oracle_api.get_matches_for_week(), adăugat 2026-08-10 după incidentul live
(ESPN a întors zero rezultate pe toate cele 98 de interogări ale cascadei
live, deși scheduled_fixtures avea deja 76 de meciuri pentru aceeași
fereastră — 62 pierdute complet).

Contract testat: fallback-ul se declanșează STRICT pentru ligile rămase
fără niciun meci și după Level DB (match_history) ȘI cascada live — nu
înlocuiește niciodată o sursă care a funcționat deja. Urmează tiparul de
mocking din test_oracle_api_scheduled_fixtures_shadow.py
(FootballOracleAPI.__new__, fără rețea)."""
from __future__ import annotations

from datetime import date, timedelta

import oracle_api

# [REPARAT 2026-08-21] Datele erau hardcodate ("2026-08-15") si au iesit din
# fereastra `days_ahead=7` odata cu trecerea calendarului — toate cele 5 teste
# picau de la o zi la alta, fara nicio schimbare de cod. Un test care se strica
# singur cu timpul nu mai protejeaza nimic: e zgomot rosu permanent, care face
# suita necitibila. Datele se calculeaza acum RELATIV la ziua rularii, deci
# contractul testat (fallback-ul se declanseaza doar pentru ligile ramase fara
# niciun meci) ramane verificat oricand. Acelasi tipar ca in
# tests/test_oracle_api_level_db_dedup.py.


def _day(offset: int = 2) -> str:
    """O data din fereastra viitoare de 7 zile, relativa la ziua rularii."""
    return (date.today() + timedelta(days=offset)).isoformat()


def _utc(offset: int = 2) -> str:
    return f"{_day(offset)}T18:00:00Z"


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

    api._fetch_events_odds_api = lambda sport_key, days_ahead=7: []
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_espn = lambda league, target_date: []
    api._fetch_matches_tsdb = lambda league_id, league_name: []
    api._fetch_matches_api_football = lambda league, date_from, date_to: []
    api._generate_demo_matches = lambda competitions: []
    api._attach_odds = lambda matches: matches
    api._attach_primary_odds_from_history = lambda matches: matches
    api._attach_flashscore_odds_fallback = lambda matches: matches
    api._shadow_evaluate_selection_engine = lambda comps, matches: None
    api._shadow_evaluate_scheduled_fixtures = lambda matches, d_from, d_to: None
    return api


def _disable_history(monkeypatch, covered_leagues: set[str] | None = None,
                      db_matches: list[dict] | None = None):
    import database.queries as queries
    monkeypatch.setattr(
        queries, "get_matches_for_week_from_history",
        lambda comps, d_from, d_to: (db_matches or [], covered_leagues or set()),
    )


def _stub_live(api, matches_by_league: dict[str, list[dict]]):
    def _fetch_live(days_ahead, competitions):
        out = []
        for league in competitions:
            out.extend(matches_by_league.get(league, []))
        return out
    api._fetch_live_week_matches = _fetch_live


def _stub_scheduled_fixtures(monkeypatch, matches_by_league: dict[str, list[dict]]):
    import database.queries as queries
    calls = []

    def _fake(leagues, d_from, d_to):
        calls.append(list(leagues))
        out = []
        covered = set()
        for league in leagues:
            rows = matches_by_league.get(league, [])
            if rows:
                covered.add(league)
                out.extend(rows)
        return out, covered

    monkeypatch.setattr(queries, "get_matches_for_week_from_scheduled_fixtures", _fake)
    return calls


def _sched_match(league: str, home="X", away="Y") -> dict:
    return {
        "fixture_id": f"scheduled_{league}", "home_team": home, "away_team": away,
        "kickoff_date": _day(), "kickoff_utc": _utc(),
        "league": league, "source": "scheduled_fixtures",
    }


def test_fallback_not_called_when_db_history_covers_league(monkeypatch):
    _disable_history(monkeypatch, covered_leagues={"Romania SuperLiga"},
                      db_matches=[{
                          "fixture_id": "hist_1", "home_team": "A", "away_team": "B",
                          "kickoff_date": _day(), "kickoff_utc": _utc(),
                          "league": "Romania SuperLiga", "source": "match_history",
                      }])
    api = _api_no_network()
    _stub_live(api, {})
    calls = _stub_scheduled_fixtures(monkeypatch, {"Romania SuperLiga": [_sched_match("Romania SuperLiga")]})

    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert calls == []
    assert len(matches) == 1
    assert matches[0]["fixture_id"] == "hist_1"


def test_fallback_not_called_when_live_cascade_covers_league(monkeypatch):
    _disable_history(monkeypatch, covered_leagues=set(), db_matches=[])
    api = _api_no_network()
    _stub_live(api, {"Romania SuperLiga": [{
        "fixture_id": "espn_1", "home_team": "A", "away_team": "B",
        "kickoff_date": _day(), "kickoff_utc": _utc(),
        "league": "Romania SuperLiga", "source": "espn",
    }]})
    calls = _stub_scheduled_fixtures(monkeypatch, {"Romania SuperLiga": [_sched_match("Romania SuperLiga")]})

    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert calls == []
    assert len(matches) == 1
    assert matches[0]["fixture_id"] == "espn_1"


def test_fallback_fires_when_db_and_live_both_empty_for_league(monkeypatch):
    _disable_history(monkeypatch, covered_leagues=set(), db_matches=[])
    api = _api_no_network()
    _stub_live(api, {})
    calls = _stub_scheduled_fixtures(monkeypatch, {"MLS": [_sched_match("MLS", "Houston Dynamo", "Seattle Sounders")]})

    matches = api.get_matches_for_week(days_ahead=7, competitions=["MLS"])

    assert calls == [["MLS"]]
    assert len(matches) == 1
    assert matches[0]["source"] == "scheduled_fixtures"
    assert matches[0]["home_team"] == "Houston Dynamo"


def test_fallback_restricted_to_still_gap_leagues_only(monkeypatch):
    """Doua ligi in gap dupa DB; live acopera doar una — fallback-ul trebuie
    apelat STRICT pentru cealalta, nu pentru amandoua."""
    _disable_history(monkeypatch, covered_leagues=set(), db_matches=[])
    api = _api_no_network()
    _stub_live(api, {"Romania SuperLiga": [{
        "fixture_id": "espn_1", "home_team": "A", "away_team": "B",
        "kickoff_date": _day(), "kickoff_utc": _utc(),
        "league": "Romania SuperLiga", "source": "espn",
    }]})
    calls = _stub_scheduled_fixtures(monkeypatch, {
        "Romania SuperLiga": [_sched_match("Romania SuperLiga")],
        "MLS": [_sched_match("MLS")],
    })

    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga", "MLS"])

    assert calls == [["MLS"]]
    by_league = {m["league"]: m for m in matches}
    assert by_league["Romania SuperLiga"]["source"] == "espn"
    assert by_league["MLS"]["source"] == "scheduled_fixtures"


def test_fallback_matches_merged_via_dedup_not_duplicated(monkeypatch):
    """Daca scheduled_fixtures intoarce un meci deja prezent (aceeasi
    cheie home/away/data), nu trebuie sa apara duplicat."""
    _disable_history(monkeypatch, covered_leagues=set(), db_matches=[])
    api = _api_no_network()
    _stub_live(api, {})
    dup = _sched_match("MLS", "Houston Dynamo", "Seattle Sounders")
    calls = _stub_scheduled_fixtures(monkeypatch, {"MLS": [dup, dict(dup, fixture_id="scheduled_dup2")]})

    matches = api.get_matches_for_week(days_ahead=7, competitions=["MLS"])

    assert calls == [["MLS"]]
    assert len(matches) == 1


def test_fallback_never_called_when_no_gap_leagues_at_all(monkeypatch):
    """Daca DB acopera toate ligile cerute, nici macar cascada live nu
    trebuie apelata — deci fallback-ul pe scheduled_fixtures cu atat mai
    putin."""
    _disable_history(monkeypatch, covered_leagues={"Romania SuperLiga"},
                      db_matches=[{
                          "fixture_id": "hist_1", "home_team": "A", "away_team": "B",
                          "kickoff_date": _day(), "kickoff_utc": _utc(),
                          "league": "Romania SuperLiga", "source": "match_history",
                      }])
    api = _api_no_network()
    live_calls = []
    api._fetch_live_week_matches = lambda days_ahead, competitions: (
        live_calls.append(competitions) or []
    )
    calls = _stub_scheduled_fixtures(monkeypatch, {})

    api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert live_calls == []
    assert calls == []
