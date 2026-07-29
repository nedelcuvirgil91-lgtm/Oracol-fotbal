"""Teste pentru functiile Foundation Data Layer din providers/flashscore/
normalizer.py (migratia 035) - contra fixture-ului real cu toate cele 7
tab-uri (docs/06_UDAL/poc_evidence/flashscore_full_tabs_poc/, POC live
aprobat explicit "TASK APROBAT - POC LIVE (1 singur meci)"), fara retea
live. Fiecare asertie verificata manual contra capturii trimise de
utilizator si raportului UDAL_FLASHSCORE_FULL_TABS_POC_REPORT.md."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from providers.flashscore.normalizer import (
    normalize_match_context,
    normalize_match_statistics,
    normalize_match_statistics_extended,
    normalize_odds,
    normalize_player_match_stats_table,
    normalize_standings,
)

FIXTURE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_full_tabs_poc"


@pytest.fixture(scope="module")
def full_tabs_pages() -> dict[str, str]:
    return {f.stem: f.read_text(encoding="utf-8") for f in FIXTURE_DIR.glob("*.html")}


def test_fixture_has_all_7_tabs(full_tabs_pages):
    assert set(full_tabs_pages) == {
        "summary", "stats", "lineups", "player_stats", "odds", "h2h", "standings",
    }


def test_normalize_match_statistics_prefers_dedicated_stats_tab(full_tabs_pages):
    """Cand tab-ul 'stats' e disponibil (spre deosebire de fixture-urile
    din primul POC, care aveau doar 'summary'), cele 9 statistici din
    captura utilizatorului + fouls devin reale, nu None."""
    result = normalize_match_statistics(full_tabs_pages)
    assert result["home_team"] == "Dinamo Bucuresti"
    assert result["away_team"] == "Univ. Craiova"
    assert result["referee"] == "Kovacs I. (Rou)"
    assert result["stadium"] == "Stadionul Arcul de Triumf (Bucharest)"
    assert result["attendance"] == 7128
    assert result["capacity"] == 8207
    assert result["home_xg_actual"] == pytest.approx(3.41)
    assert result["away_xg_actual"] == pytest.approx(0.88)
    assert result["home_possession"] == 47.0
    assert result["away_possession"] == 53.0
    assert result["home_shots"] == 18.0
    assert result["away_shots"] == 9.0
    assert result["home_shots_on_target"] == 7.0
    assert result["away_shots_on_target"] == 5.0
    assert result["home_corners"] == 8.0
    assert result["away_corners"] == 1.0
    assert result["home_fouls"] == 13.0
    assert result["away_fouls"] == 9.0
    assert result["home_yellow_cards"] == 2.0
    assert result["away_yellow_cards"] == 1.0
    assert result["home_red_cards"] == 0.0
    assert result["away_red_cards"] == 1.0
    assert result["home_offsides"] == 6.0
    assert result["away_offsides"] == 1.0
    assert result["home_goalkeeper_saves"] == 4.0
    assert result["away_goalkeeper_saves"] == 2.0


def test_normalize_match_statistics_lineups_still_populated(full_tabs_pages):
    result = normalize_match_statistics(full_tabs_pages)
    assert len(result["home_lineup"]) == 23
    assert len(result["away_lineup"]) == 23


def test_normalize_match_statistics_extended_excludes_mapped_labels(full_tabs_pages):
    """EAV nu trebuie sa duplice campurile deja acoperite de
    STAT_LABEL_TO_FIELDS/coloane match_history - doar categoriile fara
    coloana dedicata."""
    rows = normalize_match_statistics_extended(full_tabs_pages, match_id=999)
    assert len(rows) == 26
    keys = {r["stat_key"] for r in rows}
    for mapped_label_key in ("expected_goals_xg", "ball_possession", "total_shots",
                              "shots_on_target", "corner_kicks", "fouls",
                              "yellow_cards", "red_cards", "offsides", "goalkeeper_saves"):
        assert mapped_label_key not in keys


def test_normalize_match_statistics_extended_real_values(full_tabs_pages):
    rows = normalize_match_statistics_extended(full_tabs_pages, match_id=999)
    by_key = {r["stat_key"]: r for r in rows}
    assert by_key["big_chances"]["home_value_numeric"] == 6.0
    assert by_key["big_chances"]["away_value_numeric"] == 2.0
    assert by_key["big_chances"]["match_id"] == 999
    assert by_key["big_chances"]["source"] == "flashscore"
    passes = by_key["passes"]
    assert passes["home_value_raw"] == "85%(314/371)"
    assert passes["home_value_numeric"] == 85.0
    xgot = by_key["xg_on_target_xgot"]
    assert xgot["home_value_numeric"] == pytest.approx(3.60)
    assert xgot["away_value_numeric"] == pytest.approx(1.81)


def test_normalize_match_statistics_extended_no_pages(full_tabs_pages):
    assert normalize_match_statistics_extended({}, match_id=999) == []


def test_normalize_player_match_stats_table_row_count_and_columns(full_tabs_pages):
    rows = normalize_player_match_stats_table(full_tabs_pages)
    assert len(rows) == 32
    for row in rows:
        assert set(row) == {"player_name", "position", "rating", "extended_stats"}
        assert len(row["extended_stats"]) == 7


def test_normalize_player_match_stats_table_real_values(full_tabs_pages):
    rows = normalize_player_match_stats_table(full_tabs_pages)
    top = rows[0]
    assert top["player_name"] == "Pop A."
    assert top["position"] == "Striker"
    assert top["rating"] == pytest.approx(8.7)
    by_key = {s["stat_key"]: s for s in top["extended_stats"]}
    assert by_key["total_shots"]["value_numeric"] == 4.0
    assert by_key["xg"]["value_numeric"] == pytest.approx(0.85)
    assert by_key["accurate_passes"]["value_raw"] == "12/17 (71%)"
    assert by_key["accurate_passes"]["value_numeric"] == 12.0


def test_normalize_player_match_stats_table_splits_unabbreviated_names(full_tabs_pages):
    """Regresie directa: bug real gasit prin testul de idempotenta -
    2 din 32 randuri reale au nume NEabreviate, fara punct ("Teles
    Wingback", "Heriberto Tavares Forward") - vechiul regex bazat pe
    punct le lasa nesplitate (position=None), rupand join-ul cu roster-ul
    la persist(). Fix: potrivire pe vocabularul REAL de pozitii
    (sufix), nu pe punct."""
    rows = normalize_player_match_stats_table(full_tabs_pages)
    by_name = {r["player_name"]: r for r in rows}
    assert by_name["Teles"]["position"] == "Wingback"
    assert by_name["Heriberto Tavares"]["position"] == "Forward"
    assert all(r["position"] is not None for r in rows)


def test_normalize_player_match_stats_table_no_team_column(full_tabs_pages):
    """Documentat explicit ca limitare cunoscuta (nu bug): tabelul nu are
    coloana de echipa - team se rezolva la persist() prin join dupa nume."""
    rows = normalize_player_match_stats_table(full_tabs_pages)
    for row in rows:
        assert "team" not in row


def test_normalize_match_context_segments_into_3_real_categories(full_tabs_pages):
    rows = normalize_match_context(
        full_tabs_pages, match_id=999, home_team="Dinamo Bucuresti", away_team="Univ. Craiova",
    )
    counts = Counter(r["category"] for r in rows)
    assert counts == {"h2h_overall": 5, "recent_form_home": 5, "recent_form_away": 5}


def test_normalize_match_context_real_values(full_tabs_pages):
    rows = normalize_match_context(
        full_tabs_pages, match_id=999, home_team="Dinamo Bucuresti", away_team="Univ. Craiova",
    )
    most_recent_home_form = next(
        r for r in rows if r["category"] == "recent_form_home" and r["meeting_order"] == 0
    )
    assert most_recent_home_form["meeting_date"] == "2026-07-25"
    assert most_recent_home_form["home_team"] == "Dinamo Bucuresti"
    assert most_recent_home_form["away_team"] == "Univ. Craiova"
    assert most_recent_home_form["home_score"] == 5
    assert most_recent_home_form["away_score"] == 1
    assert most_recent_home_form["source"] == "flashscore"
    assert most_recent_home_form["context_match_id"] == 999


def test_normalize_match_context_populates_competition_code(full_tabs_pages):
    """[TASK APROBAT M1, regula 5/6] competition_code era un gol de
    populare documentat explicit in raportul anterior - element real
    (.h2h__event, text scurt "SL") gasit prin verificare directa pe
    fixture, acum extras."""
    rows = normalize_match_context(
        full_tabs_pages, match_id=999, home_team="Dinamo Bucuresti", away_team="Univ. Craiova",
    )
    assert all(r["competition_code"] for r in rows)
    assert rows[0]["competition_code"] == "SL"


def test_normalize_match_context_no_h2h_tab_returns_empty():
    assert normalize_match_context({}, match_id=999, home_team="A", away_team="B") == []


def test_normalize_standings_row_count_and_order(full_tabs_pages):
    rows = normalize_standings(full_tabs_pages, competition="SuperLiga")
    assert len(rows) == 16
    assert rows[0]["team"] == "FCSB"
    assert rows[0]["rank"] == 1
    assert rows[1]["team"] == "FC Rapid Bucuresti"


def test_normalize_standings_real_values(full_tabs_pages):
    rows = normalize_standings(full_tabs_pages, competition="SuperLiga")
    fcsb = rows[0]
    assert fcsb["competition"] == "SuperLiga"
    assert fcsb["played"] == 2
    assert fcsb["won"] == 2
    assert fcsb["drawn"] == 0
    assert fcsb["lost"] == 0
    assert fcsb["goals_for"] == 4
    assert fcsb["goals_against"] == 0
    assert fcsb["goal_diff"] == 4
    assert fcsb["points"] == 6
    assert fcsb["source"] == "flashscore"


def test_normalize_standings_no_standings_tab_returns_empty():
    assert normalize_standings({}, competition="SuperLiga") == []


# ════════════════════════════════════════════════════════════════════════
# normalize_odds — Odds tab (gol inchis, TASK APROBAT M1 regula 6)
# ════════════════════════════════════════════════════════════════════════

def test_normalize_odds_real_values(full_tabs_pages):
    rows = normalize_odds(full_tabs_pages)
    assert len(rows) == 3
    by_bookmaker = {r["bookmaker"]: r for r in rows}
    assert by_bookmaker["bet365.us"]["home"] == 2.50
    assert by_bookmaker["bet365.us"]["draw"] == 3.10
    assert by_bookmaker["bet365.us"]["away"] == 2.60
    assert by_bookmaker["DraftKings"]["home"] == 2.65
    for r in rows:
        assert r["source"] == "flashscore"


def test_normalize_odds_excludes_bookmaker_without_market(full_tabs_pages):
    """Fanduel apare in randul de bookmaker dar fara nicio cota reala
    pentru acest meci (gasit pe fixture) - exclus, nu aproximat cu 0."""
    rows = normalize_odds(full_tabs_pages)
    assert "Fanduel" not in {r["bookmaker"] for r in rows}


def test_normalize_odds_no_odds_tab_returns_empty():
    assert normalize_odds({}) == []
