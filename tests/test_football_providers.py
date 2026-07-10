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
