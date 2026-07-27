"""Teste pentru soccerfootballinfo_match_statistics_adapter.py (Sprint 1 v6,
ADR-041 Faza 1). Fără rețea — resolver/client injectate ca fake-uri, tipar
identic cu test_match_statistics_adapter.py (FreeLF), scope mult mai larg:
posesie, xG, șuturi (total/pe poartă/pe lângă), cornere, faulturi, ofsaiduri,
cartonașe, penalty-uri, schimbări, lineup, manageri, arbitru, stadion,
provider_raw_json."""
from __future__ import annotations

from soccerfootballinfo_match_statistics_adapter import SoccerFootballInfoMatchStatisticsAdapter


class _FakeResolver:
    def __init__(self, match_id):
        self._match_id = match_id
        self.calls: list = []

    def resolve(self, home_team, away_team, kickoff_date, league):
        self.calls.append((home_team, away_team, kickoff_date, league))
        return self._match_id


class _FakeClient:
    def __init__(self, detail):
        self._detail = detail
        self.calls: list = []

    def get_match_detail(self, match_id):
        self.calls.append(match_id)
        return self._detail


_DEFAULT = object()


def _detail_payload():
    return {
        "referee": {"name": "Istvan Kovacs"},
        "stadium": {"name": "National Arena"},
        "teamA": {
            "possession": 58, "xG": {"live": 2.1, "kickoff": 1.4},
            "shoots": {"t": 14, "on": 7, "off": 5},
            "corners": {"t": 6}, "fouls": {"t": 9, "y_c": 2, "r_c": 0},
            "attacks": {"o_s": 3}, "penalties": 1, "substitutions": 4,
            "lineup": {"formation": "4-3-3", "starters": ["A", "B"]},
            "manager": {"name": "Nuno Campos"},
        },
        "teamB": {
            "possession": 42, "xG": {"live": 0.8, "kickoff": 1.1},
            "shoots": {"t": 8, "on": 3, "off": 4},
            "corners": {"t": 2}, "fouls": {"t": 11, "y_c": 3, "r_c": 1},
            "attacks": {"o_s": 1}, "penalties": 0, "substitutions": 3,
            "lineup": {"formation": "4-4-2", "starters": ["C", "D"]},
            "manager": {"name": "Filipe Coelho"},
        },
    }


def _adapter(match_id="8f7fca2d606aef7f", detail=_DEFAULT):
    if detail is _DEFAULT:
        detail = _detail_payload()
    return SoccerFootballInfoMatchStatisticsAdapter(
        resolver=_FakeResolver(match_id), client=_FakeClient(detail),
    )


_PARAMS = {"home_team": "Dinamo Bucuresti", "away_team": "CS U Craiova",
           "kickoff_date": "2026-07-25", "league": "Romania SuperLiga"}


def test_fetch_returns_none_when_match_id_unresolved():
    adapter = _adapter(match_id=None)
    assert adapter.fetch(_PARAMS) is None


def test_fetch_returns_none_when_no_detail():
    adapter = _adapter(detail=None)
    assert adapter.fetch(_PARAMS) is None


def test_fetch_calls_get_match_detail_with_resolved_id():
    adapter = _adapter(match_id="abc999")
    adapter.fetch(_PARAMS)
    assert adapter._client.calls == ["abc999"]


def test_normalize_maps_full_field_set():
    adapter = _adapter()
    raw = adapter.fetch(_PARAMS)
    records = adapter.normalize(raw)
    assert len(records) == 1
    r = records[0]
    assert r["home_possession"] == 58
    assert r["away_possession"] == 42
    assert r["home_xg_actual"] == 2.1  # preferă xG.live peste xG.kickoff
    assert r["away_xg_actual"] == 0.8
    assert r["home_shots"] == 14 and r["home_shots_on_target"] == 7 and r["home_shots_off_target"] == 5
    assert r["away_shots"] == 8 and r["away_shots_on_target"] == 3 and r["away_shots_off_target"] == 4
    assert r["home_corners"] == 6 and r["away_corners"] == 2
    assert r["home_fouls"] == 9 and r["away_fouls"] == 11
    assert r["home_offsides"] == 3 and r["away_offsides"] == 1
    assert r["home_yellow_cards"] == 2 and r["home_red_cards"] == 0
    assert r["away_yellow_cards"] == 3 and r["away_red_cards"] == 1
    assert r["home_penalties"] == 1 and r["away_penalties"] == 0
    assert r["home_substitutions"] == 4 and r["away_substitutions"] == 3
    assert r["home_lineup"] == {"formation": "4-3-3", "starters": ["A", "B"]}
    assert r["away_lineup"] == {"formation": "4-4-2", "starters": ["C", "D"]}
    assert r["home_manager"] == "Nuno Campos"
    assert r["away_manager"] == "Filipe Coelho"
    assert r["referee"] == "Istvan Kovacs"
    assert r["stadium"] == "National Arena"
    assert r["stats_source"] == "soccerfootballinfo"
    assert r["provider_raw_json"]["provider"] == "soccerfootballinfo"
    assert r["provider_raw_json"]["endpoint"] == "matches/view/full"
    assert r["provider_raw_json"]["raw"] == _detail_payload()


def test_normalize_falls_back_to_kickoff_xg_when_live_missing():
    detail = _detail_payload()
    detail["teamA"]["xG"] = {"kickoff": 1.4}
    adapter = _adapter(detail=detail)
    raw = adapter.fetch(_PARAMS)
    r = adapter.normalize(raw)[0]
    assert r["home_xg_actual"] == 1.4


def test_normalize_empty_when_no_raw_payload():
    adapter = _adapter()
    assert adapter.normalize(None) == []


def test_validate_rejects_missing_natural_key():
    adapter = _adapter()
    records = [{"home_team": "", "away_team": "CS U Craiova", "kickoff_date": "2026-07-25",
                "home_possession": 58}]
    assert adapter.validate(records) == []


def test_validate_rejects_rows_with_no_useful_value():
    adapter = _adapter()
    records = [{"home_team": "Dinamo Bucuresti", "away_team": "CS U Craiova", "kickoff_date": "2026-07-25",
                "home_possession": None, "away_possession": None,
                "home_xg_actual": None, "away_xg_actual": None,
                "home_shots": None, "away_shots": None,
                "home_corners": None, "away_corners": None}]
    assert adapter.validate(records) == []


def test_validate_accepts_row_with_at_least_one_core_value():
    adapter = _adapter()
    records = [{"home_team": "Dinamo Bucuresti", "away_team": "CS U Craiova", "kickoff_date": "2026-07-25",
                "home_possession": 58, "away_possession": None,
                "home_xg_actual": None, "away_xg_actual": None,
                "home_shots": None, "away_shots": None,
                "home_corners": None, "away_corners": None}]
    assert len(adapter.validate(records)) == 1


def test_persist_calls_upsert_match_per_record(monkeypatch):
    calls: list = []
    monkeypatch.setattr("database.queries.upsert_match", lambda row: (calls.append(row), True)[1])
    adapter = _adapter()
    records = [{"home_team": "Dinamo Bucuresti", "away_team": "CS U Craiova", "kickoff_date": "2026-07-25",
                "home_possession": 58}]
    ok = adapter.persist(records)
    assert ok is True
    assert calls == records


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    monkeypatch.setattr("database.queries.upsert_match", lambda row: False)
    adapter = _adapter()
    records = [{"home_team": "Dinamo Bucuresti", "away_team": "CS U Craiova", "kickoff_date": "2026-07-25",
                "home_possession": 58}]
    assert adapter.persist(records) is False


def test_coverage_check_always_true():
    adapter = _adapter()
    assert adapter.coverage_check({}) is True


def test_provider_id_is_soccerfootballinfo():
    assert SoccerFootballInfoMatchStatisticsAdapter.provider_id == "soccerfootballinfo"


def test_end_to_end_fetch_normalize_validate(monkeypatch):
    calls: list = []
    monkeypatch.setattr("database.queries.upsert_match", lambda row: (calls.append(row), True)[1])
    adapter = _adapter()
    raw = adapter.fetch(_PARAMS)
    records = adapter.validate(adapter.normalize(raw))
    assert adapter.persist(records) is True
    assert len(calls) == 1
    assert calls[0]["home_team"]  # normalizat, nevid
