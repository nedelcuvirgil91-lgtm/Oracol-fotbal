from key_manager import get_key_manager
from football_providers import ApiFootballProvider


def _provider():
    return ApiFootballProvider(key_manager=get_key_manager())


def test_apifootball_unavailable_without_key():
    km = get_key_manager()
    assert km.is_available("apifootball") is False


def test_get_injuries_blocked_by_health_check():
    p = _provider()
    assert p.get_injuries("Arsenal", 42, "Premier League") == []


def test_get_coaches_blocked_by_health_check():
    p = _provider()
    assert p.get_coaches("Arsenal", 42) == []


def test_oracle_api_cache_wired_to_cache_manager():
    """Regresie: _cget/_cset din oracle_api.py trebuie sa delege la
    CacheManager (L1/L2), NU la vechiul dict self._mem (deconectat, gasit
    prin audit dupa deploy - vezi log-ul cu apeluri ESPN repetate)."""
    import tempfile
    import cache_manager
    import oracle_api

    tmp_dir = tempfile.mkdtemp()
    api1 = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api1._cache_mgr = cache_manager.CacheManager(base_dir=tmp_dir)
    api1._mem = {}
    api1._ttl = 30
    api1._cset("espn_eng.1_2024-01-01", [{"x": 1}])

    # instanta NOUA - simuleaza un rerun Streamlit; inainte de fix, self._mem
    # gol ar fi facut cache-ul sa dispara complet intre instante
    api2 = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api2._cache_mgr = cache_manager.CacheManager(base_dir=tmp_dir)
    api2._mem = {}
    api2._ttl = 30
    assert api2._cget("espn_eng.1_2024-01-01") == [{"x": 1}]


def test_oracle_api_category_mapping():
    import oracle_api
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    assert api._category_for_key("freelf_standings_Premier League") == "standings"
    assert api._category_for_key("freelf_h2h_123") == "h2h"
    assert api._category_for_key("freelf_lineup_123_home") == "lineups"
    assert api._category_for_key("odds_soccer_epl") == "odds"
    assert api._category_for_key("espn_eng.1_2024-01-01") == "matches"
    assert api._provider_for_key("espn_eng.1_2024-01-01") == "espn"
    assert api._provider_for_key("freelf_standings_x") == "freelivefootball"


def test_coverage_blocks_unknown_league():
    p = _provider()
    assert p._covered("Liga Complet Necunoscuta", "api_football") is False


def test_coverage_allows_unknown_provider_state():
    p = _provider()
    # Romania SuperLiga are api_football="necunoscut" - nu trebuie blocat
    assert p._covered("Romania SuperLiga", "api_football") is True


def test_normalize_coach_confirmed_structure():
    p = _provider()
    sample = {
        "id": 40, "name": "T. Tuchel", "nationality": "Germany",
        "team": {"id": 10, "name": "England"},
        "career": [
            {"team": {"id": 10}, "start": "2025-01-01", "end": None},
            {"team": {"id": 90}, "start": "2023-01-01", "end": "2024-12-31"},
        ],
    }
    coach = p._normalize_coach(sample, "England")
    assert coach.name == "T. Tuchel"
    assert coach.appointed_date == "2025-01-01"
    assert coach.nationality == "Germany"
    assert coach.source_provider == "apifootball"


def test_normalize_injury_assumed_structure():
    p = _provider()
    sample = {
        "player": {"id": 999, "name": "M. Salah"},
        "team": {"id": 40, "name": "Liverpool"},
        "fixture": {"id": 12345},
        "type": "Injury", "reason": "Hamstring Strain",
    }
    injury = p._normalize_injury(sample, "Liverpool")
    assert injury.player_name == "M. Salah"
    assert injury.injury_type == "Injury"
    assert injury.reason == "Hamstring Strain"


def test_normalize_injury_defensive_on_wrong_shape():
    """Structura complet diferita de presupunere - NU trebuie sa arunce
    exceptie, trebuie sa marcheze 'necunoscut'."""
    p = _provider()
    wrong = {"unexpected_field": "ceva neasteptat"}
    injury = p._normalize_injury(wrong, "Liverpool")
    assert injury is not None
    assert injury.injury_type == "necunoscut"
    assert injury.reason == "necunoscut"


def test_placeholders_raise_not_implemented():
    p = _provider()
    try:
        p.get_player_stats()
        raise AssertionError("get_player_stats ar fi trebuit sa arunce NotImplementedError")
    except NotImplementedError:
        pass
    try:
        p.get_team_stats()
        raise AssertionError("get_team_stats ar fi trebuit sa arunce NotImplementedError")
    except NotImplementedError:
        pass
