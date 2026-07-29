"""Teste pentru udal_extraction.py (UDAL Faza 1.5, ADR-042) — fără rețea."""
from __future__ import annotations

from bs4 import BeautifulSoup

from udal_extraction import CSS_RESOLVER, JSON_RESOLVER, extract


_HTML = """
<div class="match">
  <span class="home">Echipa A</span>
  <span class="away">Echipa B</span>
  <ul class="players">
    <li><span class="name">Jucator 1</span><span class="num">7</span></li>
    <li><span class="name">Jucator 2</span><span class="num">9</span></li>
  </ul>
</div>
"""


def test_css_scalar_extraction():
    soup = BeautifulSoup(_HTML, "html.parser")
    result = extract(soup, {"home_team": ".home", "away_team": ".away"}, CSS_RESOLVER)
    assert result == {"home_team": "Echipa A", "away_team": "Echipa B"}


def test_css_missing_scalar_is_none_not_approximated():
    soup = BeautifulSoup(_HTML, "html.parser")
    result = extract(soup, {"referee": ".referee-does-not-exist"}, CSS_RESOLVER)
    assert result == {"referee": None}


def test_css_nested_group_extraction():
    soup = BeautifulSoup(_HTML, "html.parser")
    result = extract(soup, {"teams": {"home_team": ".home", "away_team": ".away"}}, CSS_RESOLVER)
    assert result == {"teams": {"home_team": "Echipa A", "away_team": "Echipa B"}}


def test_css_list_extraction():
    soup = BeautifulSoup(_HTML, "html.parser")
    extraction_map = {"players": {"list": ".players li", "item": {"name": ".name", "number": ".num"}}}
    result = extract(soup, extraction_map, CSS_RESOLVER)
    assert result == {"players": [
        {"name": "Jucator 1", "number": "7"},
        {"name": "Jucator 2", "number": "9"},
    ]}


def test_css_empty_list_returns_empty():
    soup = BeautifulSoup(_HTML, "html.parser")
    extraction_map = {"injuries": {"list": ".injuries li", "item": {"player": ".name"}}}
    result = extract(soup, extraction_map, CSS_RESOLVER)
    assert result == {"injuries": []}


_JSON_PAYLOAD = {
    "teams": {"home": "Echipa A", "away": "Echipa B"},
    "statistics": {"home": {"possession": 55}},
    "players": [{"name": "Jucator 1", "rating": 8.1}, {"name": "Jucator 2", "rating": 7.4}],
}


def test_json_scalar_extraction():
    result = extract(_JSON_PAYLOAD, {"home_team": "teams.home"}, JSON_RESOLVER)
    assert result == {"home_team": "Echipa A"}


def test_json_nested_path_extraction():
    result = extract(_JSON_PAYLOAD, {"home_possession": "statistics.home.possession"}, JSON_RESOLVER)
    assert result == {"home_possession": "55"}


def test_json_missing_path_is_none():
    result = extract(_JSON_PAYLOAD, {"xg": "advanced_statistics.home.xg"}, JSON_RESOLVER)
    assert result == {"xg": None}


def test_json_list_extraction():
    extraction_map = {"players": {"list": "players", "item": {"name": "name", "rating": "rating"}}}
    result = extract(_JSON_PAYLOAD, extraction_map, JSON_RESOLVER)
    assert result == {"players": [
        {"name": "Jucator 1", "rating": "8.1"},
        {"name": "Jucator 2", "rating": "7.4"},
    ]}


def test_json_indexed_path_extraction():
    result = extract(_JSON_PAYLOAD, {"first_player_name": "players[0].name"}, JSON_RESOLVER)
    assert result == {"first_player_name": "Jucator 1"}


def test_json_out_of_range_index_is_none():
    result = extract(_JSON_PAYLOAD, {"tenth_player": "players[9].name"}, JSON_RESOLVER)
    assert result == {"tenth_player": None}


def test_invalid_node_raises_value_error():
    import pytest
    with pytest.raises(ValueError):
        extract({}, {"bad": 123}, CSS_RESOLVER)  # type: ignore[dict-item]
