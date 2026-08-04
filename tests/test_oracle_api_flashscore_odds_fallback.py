"""Teste pentru oracle_api.FootballOracleAPI._attach_flashscore_odds_fallback()
(ADR-043 §Decizie pct. 3) — fără rețea.

Verifică: (1) implicit OPRIT — zero apel DB cu flag dezactivat (North Star
#3); (2) populează DOAR meciurile fără cote deja atașate de sursa primară;
(3) nu suprascrie niciodată cote deja existente; (4) degradare grațioasă
la orice eroare — `matches` returnat neschimbat; (5) wiring real în
`get_matches_for_week()`, imediat după `_attach_odds()`."""
from __future__ import annotations

from datetime import date

import oracle_api

_TODAY = date.today().isoformat()


def _api() -> oracle_api.FootballOracleAPI:
    return oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)


# ── _attach_flashscore_odds_fallback — direct, izolat ──────────────────────

def test_flag_disabled_by_default_never_calls_db(monkeypatch):
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(cfg, "is_enabled", lambda: False)
    import database.queries as q

    def _spy(*a, **kw):
        raise AssertionError("nu trebuie apelat cu flag OFF")
    monkeypatch.setattr(q, "get_odds_fallback_for_missing_fixtures", _spy)

    matches = [{"fixture_id": "fx1", "home_team": "A", "away_team": "B"}]
    result = _api()._attach_flashscore_odds_fallback(matches)
    assert result == matches


def test_flag_enabled_but_all_matches_already_have_odds_skips_db_call(monkeypatch):
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(cfg, "is_enabled", lambda: True)
    import database.queries as q

    def _spy(*a, **kw):
        raise AssertionError("nu trebuie apelat daca toate meciurile au deja cote")
    monkeypatch.setattr(q, "get_odds_fallback_for_missing_fixtures", _spy)

    matches = [{"fixture_id": "fx1", "home_odds": 1.8}]
    result = _api()._attach_flashscore_odds_fallback(matches)
    assert result == matches


def test_flag_enabled_no_fixture_id_skips_db_call(monkeypatch):
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(cfg, "is_enabled", lambda: True)
    import database.queries as q
    calls = []
    monkeypatch.setattr(q, "get_odds_fallback_for_missing_fixtures", lambda fids: calls.append(fids) or {})

    matches = [{"home_team": "A", "away_team": "B"}]
    result = _api()._attach_flashscore_odds_fallback(matches)
    assert result == matches
    assert calls == []


def test_flag_enabled_fills_odds_only_for_matches_missing_them(monkeypatch):
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(cfg, "is_enabled", lambda: True)
    import database.queries as q
    calls = []

    def _fake_get(fixture_ids):
        calls.append(fixture_ids)
        return {"fx2": {"bookmaker": "bet365", "home": 1.9, "draw": 3.3, "away": 4.2}}
    monkeypatch.setattr(q, "get_odds_fallback_for_missing_fixtures", _fake_get)

    matches = [
        {"fixture_id": "fx1", "home_odds": 1.8, "draw_odds": 3.2, "away_odds": 4.5, "bookmaker": "Unibet"},
        {"fixture_id": "fx2"},
    ]
    result = _api()._attach_flashscore_odds_fallback(matches)

    assert calls == [["fx2"]]
    # meciul cu cote deja atasate ramane complet neatins
    assert result[0] == {"fixture_id": "fx1", "home_odds": 1.8, "draw_odds": 3.2, "away_odds": 4.5, "bookmaker": "Unibet"}
    # meciul fara cote primeste fallback-ul
    assert result[1]["home_odds"] == 1.9
    assert result[1]["draw_odds"] == 3.3
    assert result[1]["away_odds"] == 4.2
    assert result[1]["bookmaker"] == "bet365"
    assert result[1]["odds_source"] == "Flashscore fallback (bet365)"


def test_flag_enabled_fixture_not_found_in_fallback_stays_without_odds(monkeypatch):
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(cfg, "is_enabled", lambda: True)
    import database.queries as q
    monkeypatch.setattr(q, "get_odds_fallback_for_missing_fixtures", lambda fixture_ids: {})

    matches = [{"fixture_id": "fx1"}]
    result = _api()._attach_flashscore_odds_fallback(matches)
    assert "home_odds" not in result[0]


def test_flag_enabled_db_exception_degrades_gracefully(monkeypatch):
    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(cfg, "is_enabled", lambda: True)
    import database.queries as q

    def _boom(fixture_ids):
        raise RuntimeError("boom")
    monkeypatch.setattr(q, "get_odds_fallback_for_missing_fixtures", _boom)

    matches = [{"fixture_id": "fx1"}]
    result = _api()._attach_flashscore_odds_fallback(matches)
    assert result == matches


# ── wiring real în get_matches_for_week() ───────────────────────────────────

def _api_no_network() -> oracle_api.FootballOracleAPI:
    api = _api()
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._freelf_exhausted = False
    api._active_sport_keys = set()
    api._api_football = None
    api._key_manager = None

    def _fixed_match(league: str, source: str, target_date: str) -> dict:
        return {
            "fixture_id": f"{source}_{league}_{target_date}", "home_team": "A", "away_team": "B",
            "kickoff_date": target_date, "kickoff_utc": f"{target_date}T18:00:00Z",
            "league": league, "source": source,
        }

    api._fetch_events_odds_api = lambda sport_key, days_ahead=7: []
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_espn = lambda league, target_date: (
        [_fixed_match(league, "espn", target_date)]
        if league == "Romania SuperLiga" and target_date == _TODAY else []
    )
    api._fetch_matches_tsdb = lambda league_id, league_name: []
    api._fetch_matches_api_football = lambda league, date_from, date_to: []
    api._generate_demo_matches = lambda competitions: []
    api._attach_odds = lambda matches: matches
    return api


def _disable_other_shadows(monkeypatch):
    import shadow_config
    monkeypatch.setattr(shadow_config, "is_enabled", lambda: False)
    import scheduled_fixtures_shadow_config
    monkeypatch.setattr(scheduled_fixtures_shadow_config, "is_enabled", lambda: False)


def test_get_matches_for_week_wires_fallback_after_attach_odds(monkeypatch):
    _disable_other_shadows(monkeypatch)

    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(cfg, "is_enabled", lambda: True)
    import database.queries as q
    monkeypatch.setattr(
        q, "get_odds_fallback_for_missing_fixtures",
        lambda fixture_ids: {fixture_ids[0]: {"bookmaker": "bet365", "home": 1.5, "draw": 3.5, "away": 6.0}},
    )

    api = _api_no_network()
    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert len(matches) == 1
    assert matches[0]["home_odds"] == 1.5
    assert matches[0]["odds_source"] == "Flashscore fallback (bet365)"


def test_get_matches_for_week_flag_off_leaves_matches_without_odds(monkeypatch):
    _disable_other_shadows(monkeypatch)

    import flashscore_odds_fallback_config as cfg
    monkeypatch.setattr(cfg, "is_enabled", lambda: False)
    import database.queries as q

    def _spy(*a, **kw):
        raise AssertionError("nu trebuie apelat cu flag OFF")
    monkeypatch.setattr(q, "get_odds_fallback_for_missing_fixtures", _spy)

    api = _api_no_network()
    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert len(matches) == 1
    assert "home_odds" not in matches[0]
