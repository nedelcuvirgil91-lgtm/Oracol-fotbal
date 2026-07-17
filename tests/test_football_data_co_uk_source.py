"""
Teste pentru importer-ul football-data.co.uk — fara retea (requests.get
mock-uit), fara nicio referinta specifica unei ligi in datele de test
(codul de division e parametru, nu presupunere).
"""
from datetime import datetime, timedelta, timezone

import sync.sources.football_data_co_uk as src


_HEADER = "Division,MatchDate,HomeTeam,AwayTeam,FTHome,FTAway,OddHome,OddDraw,OddAway,MaxHome,MaxDraw,MaxAway"

_STATS_HEADER = (
    "Division,MatchDate,HomeTeam,AwayTeam,FTHome,FTAway,HTHome,HTAway,"
    "HomeShots,AwayShots,HomeTarget,AwayTarget,HomeFouls,AwayFouls,"
    "HomeCorners,AwayCorners,HomeYellow,AwayYellow,HomeRed,AwayRed"
)


def _stats_csv_text(*rows: str) -> str:
    return "\n".join([_STATS_HEADER, *rows])


def _iso_date(days_ago: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


class _FakeResponse:
    def __init__(self, text: str):
        self.content = text.encode("utf-8")
    def raise_for_status(self):
        pass


def _csv_text(*rows: str) -> str:
    return "\n".join([_HEADER, *rows])


def test_filters_by_division_code(monkeypatch):
    recent = _iso_date(10)
    text = _csv_text(
        f"X0,{recent},Team A,Team B,2,1,1.9,3.4,4.2,2.0,3.5,4.5",
        f"Y0,{recent},Team C,Team D,1,1,2.0,3.0,3.5,2.1,3.2,3.6",
    )
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text))

    rows = src.fetch_football_data_co_uk_rows("X0", None, "2000-01-01")
    assert len(rows) == 2  # X0 are 2 bookmakeri validi (Bet365 + Market_Max)
    assert all(r["home_team_raw"] == "Team A" for r in rows)


def test_filters_by_min_date(monkeypatch):
    old = _iso_date(3000)
    recent = _iso_date(5)
    text = _csv_text(
        f"X0,{old},Old A,Old B,1,0,1.9,3.4,4.2,2.0,3.5,4.5",
        f"X0,{recent},New A,New B,2,2,1.9,3.4,4.2,2.0,3.5,4.5",
    )
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text))

    rows = src.fetch_football_data_co_uk_rows("X0", None, _iso_date(365))
    teams = {r["home_team_raw"] for r in rows}
    assert "New A" in teams
    assert "Old A" not in teams


def test_missing_score_is_skipped_not_guessed(monkeypatch):
    recent = _iso_date(5)
    text = _csv_text(
        f"X0,{recent},Team A,Team B,,,1.9,3.4,4.2,2.0,3.5,4.5",  # scor lipsa
    )
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text))

    rows = src.fetch_football_data_co_uk_rows("X0", None, "2000-01-01")
    assert rows == []


def test_invalid_odds_skipped_per_bookmaker():
    """Un bookmaker cu cota invalida (<=1 sau lipsa) nu produce rand -- nu se
    scrie partial, nu se aproximeaza."""
    assert src._is_valid_price(1.5) is True
    assert src._is_valid_price(1.0) is False
    assert src._is_valid_price(0.5) is False
    assert src._is_valid_price(None) is False
    assert src._is_valid_price("") is False
    assert src._is_valid_price("abc") is False


def test_source_hash_deterministic_per_row(monkeypatch):
    recent = _iso_date(5)
    text = _csv_text(f"X0,{recent},Team A,Team B,2,1,1.9,3.4,4.2,2.0,3.5,4.5")
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text))

    rows1 = src.fetch_football_data_co_uk_rows("X0", None, "2000-01-01")
    rows2 = src.fetch_football_data_co_uk_rows("X0", None, "2000-01-01")
    assert rows1[0]["source_hash"] == rows2[0]["source_hash"]
    assert len(rows1[0]["source_hash"]) == 64  # sha256 hex


def test_different_row_content_produces_different_hash(monkeypatch):
    recent = _iso_date(5)
    text_a = _csv_text(f"X0,{recent},Team A,Team B,2,1,1.9,3.4,4.2,2.0,3.5,4.5")
    text_b = _csv_text(f"X0,{recent},Team A,Team B,3,1,1.9,3.4,4.2,2.0,3.5,4.5")  # scor diferit

    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text_a))
    rows_a = src.fetch_football_data_co_uk_rows("X0", None, "2000-01-01")
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text_b))
    rows_b = src.fetch_football_data_co_uk_rows("X0", None, "2000-01-01")

    assert rows_a[0]["source_hash"] != rows_b[0]["source_hash"]


def test_match_stats_extracts_one_row_per_match(monkeypatch):
    recent = _iso_date(10)
    text = _stats_csv_text(
        f"X0,{recent},Team A,Team B,2,1,1,0,12,8,5,3,10,9,6,4,2,1,0,0",
    )
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text))

    rows = src.fetch_football_data_co_uk_match_stats("X0", None, "2000-01-01")
    assert len(rows) == 1
    r = rows[0]
    assert r["home_shots"] == 12 and r["away_shots"] == 8
    assert r["home_shots_on_target"] == 5 and r["away_shots_on_target"] == 3
    assert r["home_fouls"] == 10 and r["away_fouls"] == 9
    assert r["home_corners"] == 6 and r["away_corners"] == 4
    assert r["home_yellow_cards"] == 2 and r["away_yellow_cards"] == 1
    assert r["home_red_cards"] == 0 and r["away_red_cards"] == 0
    assert r["home_ht_goals"] == 1 and r["away_ht_goals"] == 0


def test_match_stats_missing_field_omitted_not_zeroed(monkeypatch):
    """Un camp lipsa/nevalid in sursa nu apare deloc in rezultat -- nu e
    scris ca 0 sau aproximat."""
    recent = _iso_date(10)
    text = _stats_csv_text(
        f"X0,{recent},Team A,Team B,2,1,,,12,8,,,,,,,,,,",
    )
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text))

    rows = src.fetch_football_data_co_uk_match_stats("X0", None, "2000-01-01")
    assert len(rows) == 1
    r = rows[0]
    assert r["home_shots"] == 12 and r["away_shots"] == 8
    for missing_col in ("home_shots_on_target", "away_shots_on_target", "home_fouls",
                         "home_corners", "home_yellow_cards", "home_red_cards", "home_ht_goals"):
        assert missing_col not in r


def test_match_stats_missing_score_skipped(monkeypatch):
    recent = _iso_date(10)
    text = _stats_csv_text(
        f"X0,{recent},Team A,Team B,,,1,0,12,8,5,3,10,9,6,4,2,1,0,0",
    )
    monkeypatch.setattr(src.requests, "get", lambda *a, **k: _FakeResponse(text))

    rows = src.fetch_football_data_co_uk_match_stats("X0", None, "2000-01-01")
    assert rows == []
