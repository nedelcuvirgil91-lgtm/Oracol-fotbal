from key_manager import get_key_manager
from football_providers import ApiFootballProvider


def _provider():
    return ApiFootballProvider(key_manager=get_key_manager())


class _FakeKeyManagerNoKey:
    """Simuleaza un provider fara nicio cheie configurata - izolat de starea
    reala globala (care acum ARE o cheie API-Football validă). Testeaza
    logica de gating, nu starea curenta a proiectului."""
    def is_available(self, provider_id): return False
    def get_headers(self, provider_id): return None
    def record_request(self, provider_id): pass


def test_health_check_gate_blocks_when_no_key_configured():
    """Regresie izolata: logica de gating trebuie sa blocheze orice request
    daca providerul nu are nicio cheie - indiferent de starea reala globala."""
    p = ApiFootballProvider(key_manager=_FakeKeyManagerNoKey())
    assert p._healthy() is False
    assert p.get_injuries("Arsenal", 42, "Premier League") == []
    assert p.get_coaches("Arsenal", 42) == []
    assert p.resolve_team_id("Arsenal") is None


def test_apifootball_key_now_configured_in_key_manager():
    """Confirma integrarea reala: cheia traieste DOAR in key_manager.py,
    niciodata hardcodata in football_providers.py sau alte module."""
    km = get_key_manager()
    assert km.is_available("apifootball") is True
    headers = km.get_headers("apifootball")
    assert headers is not None
    assert "x-apisports-key" in headers


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
    # World Cup 2026 are api_football="necunoscut" - nu trebuie blocat
    assert p._covered("World Cup 2026", "api_football") is True


def test_coverage_blocks_plan_restricted_romania_superliga():
    """Romania SuperLiga: league_id=283 confirmat live, dar planul Free
    blocheaza sezonul curent pe /fixtures (verificat live, run 29616468120/
    29616932623) - supported="plan_restricted" trebuie tratat ca False,
    NU ca "necunoscut" (nu e o stare nedeterminata, e confirmata)."""
    p = _provider()
    assert p._covered("Romania SuperLiga", "api_football") is False


def test_get_fixtures_makes_zero_http_calls_when_plan_restricted():
    """0 cereri irosite: get_fixtures() nu trebuie sa apeleze _get() deloc
    pentru Romania SuperLiga - gate-ul de coverage opreste inainte de HTTP."""
    p = _provider()
    calls = []
    p._get = lambda *a, **kw: calls.append(a) or {"response": []}
    result = p.get_fixtures("Romania SuperLiga", 283, "2026-07-17", "2026-07-24", season=2026)
    assert result == []
    assert calls == []


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


def test_get_injuries_sends_season_param():
    """Regresie directa pe descoperirea live: API-Football intoarce HTTP 200
    cu {"errors":{"season":"..."}} daca lipseste 'season'. Confirma ca
    parametrul e acum trimis, nu doar 'team'."""
    p = _provider()
    captured_params = {}
    original_get = p._get
    def spy_get(path, params, category, cache_key):
        captured_params.update(params)
        return {"response": []}
    p._get = spy_get
    p.get_injuries("Arsenal", 42, "Premier League", season=2025)
    assert captured_params.get("season") == 2025
    assert captured_params.get("team") == 42


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


def test_get_fixtures_sends_league_season_range_params():
    """World Cup 2026 ("necunoscut", nu "plan_restricted") - folosita aici
    doar ca liga acoperita, ca sa testam parametrii trimisi, nu semantica
    reala a competitiei."""
    p = _provider()
    captured_params = {}
    def spy_get(path, params, category, cache_key):
        captured_params.update(params)
        assert category == "matches"
        return {"response": []}
    p._get = spy_get
    p.get_fixtures("World Cup 2026", 1, "2026-07-18", "2026-07-25", season=2026)
    assert captured_params == {"league": 1, "season": 2026, "from": "2026-07-18", "to": "2026-07-25"}


def test_get_fixtures_blocked_for_unsupported_league():
    """football_data e explicit False pentru Romania SuperLiga - dar aici testam
    coverage pe categoria 'api_football', nu 'football_data'; folosim o liga
    complet necunoscuta pentru a confirma blocarea reala."""
    p = _provider()
    assert p.get_fixtures("Liga Complet Necunoscuta", 999, "2026-07-18", "2026-07-25", season=2026) == []


def test_normalize_fixture_confirmed_structure():
    p = _provider()
    sample = {
        "fixture": {"id": 1234567, "date": "2026-07-19T16:00:00+00:00",
                    "venue": {"city": "Bucuresti"}},
        "teams": {"home": {"id": 1, "name": "FCSB"}, "away": {"id": 2, "name": "CFR Cluj"}},
    }
    fx = p._normalize_fixture(sample, "Romania SuperLiga", 2026)
    assert fx["fixture_id"] == "apifootball_1234567"
    assert fx["home_team"] == "FCSB"
    assert fx["away_team"] == "CFR Cluj"
    assert fx["kickoff_date"] == "2026-07-19"
    assert fx["league"] == "Romania SuperLiga"
    assert fx["season"] == 2026
    assert fx["source"] == "apifootball"


def test_normalize_fixture_defensive_on_missing_fixture_id():
    p = _provider()
    wrong = {"fixture": {"date": "2026-07-19T16:00:00+00:00"},
              "teams": {"home": {"name": "FCSB"}, "away": {"name": "CFR Cluj"}}}
    assert p._normalize_fixture(wrong, "Romania SuperLiga", 2026) is None


def test_normalize_fixture_defensive_on_missing_teams():
    p = _provider()
    wrong = {"fixture": {"id": 1}, "teams": {}}
    assert p._normalize_fixture(wrong, "Romania SuperLiga", 2026) is None


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
