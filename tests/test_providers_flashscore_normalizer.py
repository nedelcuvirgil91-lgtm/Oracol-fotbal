"""Teste pentru providers/flashscore/normalizer.py (M0) - contra fixture-urilor
REALE capturate in POC (docs/06_UDAL/poc_evidence/flashscore_10matches/),
fara retea live. Fiecare asertie corespunde unei valori verificate manual
pe fixture, nu unei presupuneri (vezi normalizer.py, docstring modul)."""
from __future__ import annotations

from pathlib import Path

import pytest

from providers.flashscore.normalizer import (
    normalize_match_events, normalize_match_statistics, normalize_player_match_stats,
)

FIXTURE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_10matches"

SUPERLIGA_1_PREFIX = "superliga_1_rapid-bucuresti-YFCpigVG_?mid=EeqI7WJc"
UCL_6_PREFIX = "ucl_6_shamrock-rovers-KIN6lmnH_?mid=f9yUru7s"

ALL_10_PREFIXES = [
    "superliga_1_rapid-bucuresti-YFCpigVG_?mid=EeqI7WJc",
    "superliga_2_voluntari-WIoSeFi4_?mid=631P5AlA",
    "superliga_3_miercurea-ciuc-A5gTQ7pG_?mid=IPgBd6Bd",
    "superliga_4_universitatea-cluj-Us6gkXaT_?mid=vHaX3lJM",
    "superliga_5_univ-craiova-bsd9fGaK_?mid=AJtcK933",
    "ucl_6_shamrock-rovers-KIN6lmnH_?mid=f9yUru7s",
    "ucl_7_sturm-graz-zsktjfsD_?mid=0M0wdHSH",
    "ucl_8_kf-egnatia-CjYs7BO9_?mid=WxPrLDQE",
    "ucl_9_thun-4WElAd9p_?mid=rqFko0Ea",
    "ucl_10_mjallby-S0XtXM1E_?mid=4CbLusAN",
]


def _load_pages(prefix: str) -> dict[str, str]:
    pages: dict[str, str] = {}
    for f in FIXTURE_DIR.glob(f"{prefix}__*.html"):
        tab = f.stem.rsplit("__", 1)[-1]
        pages[tab] = f.read_text(encoding="utf-8")
    return pages


@pytest.fixture(scope="module")
def superliga_1_pages() -> dict[str, str]:
    return _load_pages(SUPERLIGA_1_PREFIX)


@pytest.fixture(scope="module")
def ucl_6_pages() -> dict[str, str]:
    return _load_pages(UCL_6_PREFIX)


def test_fixtures_exist_and_have_expected_tabs(superliga_1_pages):
    assert set(superliga_1_pages) >= {"summary", "lineups", "h2h", "odds", "standings"}


def test_normalize_match_statistics_team_names_not_duplicated(superliga_1_pages):
    """Regresie directa: bug real gasit prin testare - numele echipei
    apare de 2 ori pe pagina (header compact + principal), fara dedup
    away_team ar fi devenit egal cu home_team."""
    result = normalize_match_statistics(superliga_1_pages)
    assert result["home_team"] == "FC Botosani"
    assert result["away_team"] == "FC Rapid Bucuresti"
    assert result["home_team"] != result["away_team"]


def test_normalize_match_statistics_kickoff_iso(superliga_1_pages):
    result = normalize_match_statistics(superliga_1_pages)
    assert result["kickoff_date"] == "2026-07-27T18:30:00"


def test_normalize_match_statistics_real_values(superliga_1_pages):
    """Fiecare valoare verificata manual, direct pe fixture (vezi sesiunea
    de verificare) - nu presupusa."""
    result = normalize_match_statistics(superliga_1_pages)
    assert result["referee"] == "Barbu M. (Rou)"
    assert result["stadium"] == "Stadionul Municipal (Botoşani)"
    assert result["home_possession"] == 58.0
    assert result["away_possession"] == 42.0
    assert result["home_shots"] == 12.0
    assert result["away_shots"] == 13.0
    assert result["home_xg_actual"] == pytest.approx(1.42)
    assert result["away_xg_actual"] == pytest.approx(1.21)
    assert result["stats_source"] == "flashscore"


def test_normalize_match_statistics_no_fabricated_fields(superliga_1_pages):
    """Camp fara dovada directa (corners/fouls/cards/offsides/saves/
    attendance) NU trebuie sa apara deloc in rezultat - scope M0 explicit
    (vezi docstring normalizer.py) - nicio stare necunoscuta aproximata."""
    result = normalize_match_statistics(superliga_1_pages)
    for forbidden in ("home_corners", "away_corners", "home_fouls", "away_fouls",
                       "home_yellow_cards", "away_yellow_cards", "home_offsides",
                       "away_offsides", "home_goalkeeper_saves", "away_goalkeeper_saves"):
        assert forbidden not in result


def test_normalize_match_statistics_missing_widget_returns_none_not_zero(ucl_6_pages):
    """xG lipsa real (confirmat - calificari UCL, widget fara acea
    categorie) -> None, niciodata 0 sau alta valoare aproximata."""
    result = normalize_match_statistics(ucl_6_pages)
    assert result["home_xg_actual"] is None
    assert result["away_xg_actual"] is None
    assert result["home_possession"] == 61.0


def test_normalize_lineups_name_wrapper_button_and_link_both_handled(superliga_1_pages, ucl_6_pages):
    """Regresie directa: bug real gasit - wrapper-ul numelui e <button>
    pentru unii jucatori, <a href='/player/...'> pentru altii (profil
    existent) - ambele cazuri trebuie sa produca acelasi rezultat corect."""
    r1 = normalize_match_statistics(superliga_1_pages)
    r2 = normalize_match_statistics(ucl_6_pages)
    assert len(r1["home_lineup"]) > 15
    assert len(r2["home_lineup"]) > 15
    assert any(p["name"] == "Anestis G." and p["shirt_number"] == 99 for p in r1["home_lineup"])
    assert any(p["name"] == "McGinty E." and p["shirt_number"] == 1 for p in r2["home_lineup"])


def test_normalize_lineups_role_marker_not_captured_as_name(ucl_6_pages):
    """Regresie: '(G)'/'(C)' (marcaje de rol, acelasi testid ca numele)
    nu trebuie sa apara niciodata ca nume de jucator."""
    result = normalize_match_statistics(ucl_6_pages)
    all_names = [p["name"] for p in result["home_lineup"] + result["away_lineup"]]
    assert all(not n.startswith("(") for n in all_names)


def test_normalize_player_match_stats_real_values(superliga_1_pages):
    rows = normalize_player_match_stats(superliga_1_pages, match_id=123)
    assert len(rows) > 15
    assert all(r["match_id"] == 123 for r in rows)
    assert all(r["team"] in ("home", "away") for r in rows)
    assert all(r["source"] == "flashscore" for r in rows)
    anestis = next(r for r in rows if r["player_name"] == "Anestis G.")
    assert anestis["team"] == "home"
    assert anestis["shirt_number"] == 99


def test_normalize_match_events_only_substitutions_with_real_data(superliga_1_pages):
    """Scope M0 explicit: doar substitutii (structura de minut verificata
    curat) - goluri/cartonase deferred, nu ghicite (vezi normalizer.py)."""
    events = normalize_match_events(superliga_1_pages, match_id=123)
    assert len(events) == 9
    assert all(e["event_type"] == "substitution" for e in events)
    assert all(e["match_id"] == 123 for e in events)
    assert all(isinstance(e["minute"], int) and 0 < e["minute"] <= 120 for e in events)
    assert all(e["player_name"] and e["related_player_name"] for e in events)
    first = events[0]
    assert first["player_name"] == "Bayeye B. J."
    assert first["related_player_name"] == "Cret R."
    assert first["minute"] == 46


@pytest.mark.parametrize("prefix", ALL_10_PREFIXES)
def test_normalize_all_10_fixtures_produce_valid_match_and_no_crash(prefix):
    """Regresie de robustete pe toate cele 10 meciuri reale - nu doar
    esantionul verificat manual (2 meciuri) - trebuie sa functioneze
    identic pe restul, fara exceptii, fara campuri lipsa la nivel de
    structura (home_team/away_team/kickoff_date mereu prezente)."""
    pages = _load_pages(prefix)
    result = normalize_match_statistics(pages)
    assert result["home_team"], f"home_team lipsa pentru {prefix}"
    assert result["away_team"], f"away_team lipsa pentru {prefix}"
    assert result["home_team"] != result["away_team"]
    assert result["kickoff_date"] is not None
    pstats = normalize_player_match_stats(pages, match_id=1)
    assert len(pstats) > 0, f"niciun jucator extras pentru {prefix}"
    events = normalize_match_events(pages, match_id=1)
    assert all(e["event_type"] == "substitution" for e in events)
