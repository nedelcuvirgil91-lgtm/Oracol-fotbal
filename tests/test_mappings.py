from mappings import (
    LEAGUE_PROVIDERS, FD_COMPETITIONS, ESPN_LEAGUE_SLUGS, TSDB_LEAGUE_IDS,
    ODDS_SPORT_KEYS, FREE_LF_LEAGUE_IDS, SPORT_KEY_TO_LEAGUE,
    verify_league_coverage, normalize_league_name, normalize_team_name,
    LEAGUE_BASELINES, ELO_RATINGS_FALLBACK,
)

BOOTSTRAP_LEAGUES = [
    "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
    "Champions League", "Europa League", "Romania SuperLiga", "World Cup 2026",
]


def test_league_providers_has_all_bootstrap_leagues():
    for league in BOOTSTRAP_LEAGUES:
        assert league in LEAGUE_PROVIDERS, f"{league} lipsește din LEAGUE_PROVIDERS"


def test_league_providers_has_conference_league():
    assert "Conference League" in LEAGUE_PROVIDERS


def test_derived_dicts_match_league_providers():
    """Dictionarele vechi trebuie sa fie EXACT derivate din LEAGUE_PROVIDERS,
    nu divergente - exact bug-ul original descoperit prin audit."""
    for league, definition in LEAGUE_PROVIDERS.items():
        fd = definition.provider_ids.get("football_data")
        if fd is not None:
            assert FD_COMPETITIONS.get(league) == fd
        espn = definition.provider_ids.get("espn")
        if espn is not None:
            assert ESPN_LEAGUE_SLUGS.get(league) == espn
        tsdb = definition.provider_ids.get("tsdb")
        if tsdb is not None:
            assert TSDB_LEAGUE_IDS.get(league) == tsdb
        odds = definition.provider_ids.get("odds")
        if odds is not None:
            assert ODDS_SPORT_KEYS.get(league) == odds
            assert SPORT_KEY_TO_LEAGUE.get(odds) == league
        freelf = definition.provider_ids.get("freelf")
        if freelf is not None:
            assert FREE_LF_LEAGUE_IDS.get(league) == freelf


def test_europa_league_and_world_cup_in_fd_competitions():
    """Regresie directa pt bug-ul original: sync_results.py derives
    COMPETITION_TO_LEAGUE din FD_COMPETITIONS - EL/WC TREBUIE sa fie aici."""
    assert FD_COMPETITIONS.get("Europa League") == "EL"
    assert FD_COMPETITIONS.get("World Cup 2026") == "WC"


def test_romania_and_mls_correctly_marked_unsupported_by_football_data():
    assert LEAGUE_PROVIDERS["Romania SuperLiga"].supported["football_data"] is False
    assert LEAGUE_PROVIDERS["MLS"].supported["football_data"] is False


def test_verify_league_coverage_no_errors_on_bootstrap_leagues():
    result = verify_league_coverage(BOOTSTRAP_LEAGUES)
    assert result["errors"] == [], f"Erori neasteptate: {result['errors']}"


def test_verify_league_coverage_fails_on_missing_league():
    result = verify_league_coverage(["Liga Complet Inexistenta"])
    assert len(result["errors"]) == 1
    assert "Liga Complet Inexistenta" in result["errors"][0]


def test_conference_league_passes_coverage_with_required_providers():
    """espn+tsdb confirmate -> nu trebuie sa fie eroare, doar eventual warning
    pt providerii optionali (odds/freelf/api_football = necunoscut)."""
    result = verify_league_coverage(["Conference League"])
    assert result["errors"] == []
    assert len(result["warnings"]) > 0  # exista necunoscute (odds/freelf/api_football)


def test_normalize_league_name_conference_league_aliases():
    assert normalize_league_name("UECL") == "Conference League"
    assert normalize_league_name("UEFA Conference League") == "Conference League"


def test_normalize_team_name_previously_colliding_teams():
    """Regresie directa: cele 3 coliziuni gasite si reparate prin audit."""
    assert normalize_team_name("MANCHESTER UTD") == "Manchester United"
    assert normalize_team_name("INTER") == "Inter Milan"
    assert normalize_team_name("LEICESTER") == "Leicester City"
    assert normalize_team_name("Leicester City FC") == "Leicester City"


def test_league_baselines_and_elo_fallback_untouched():
    """Astea NU trebuiau atinse de refactorizare - verificare ca nu s-a stricat nimic."""
    assert len(LEAGUE_BASELINES) >= 10
    assert len(ELO_RATINGS_FALLBACK) >= 60
    assert LEAGUE_BASELINES.get("Premier League") == 1.35
