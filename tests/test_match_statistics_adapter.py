"""Teste pentru match_statistics_adapter.py (Sprint 1, ADR-039). Fără
rețea — api/resolver injectate ca fake-uri. Verifică inclusiv scope-ul
aprobat explicit: DOAR possession/xg_actual, niciodată big_chance/
shots_on_target (owner rămas football_data_co_uk)."""
from __future__ import annotations

from match_statistics_adapter import MatchStatisticsAdapter


class _FakeResolver:
    def __init__(self, event_id):
        self._event_id = event_id
        self.calls: list = []

    def resolve(self, home_team, away_team, kickoff_date, league):
        self.calls.append((home_team, away_team, kickoff_date, league))
        return self._event_id


class _FakeApi:
    def __init__(self, stats):
        self._stats = stats
        self.calls: list = []

    def get_match_statistics(self, event_id):
        self.calls.append(event_id)
        return self._stats


_DEFAULT = object()


def _adapter(event_id=42, stats=_DEFAULT):
    if stats is _DEFAULT:
        stats = {
            "home_xg": 1.8, "away_xg": 0.9,
            "home_possession": 61.0, "away_possession": 39.0,
            "home_shots_ot": 5, "away_shots_ot": 2,
            "home_big_chance": 3, "away_big_chance": 1,
            "source": "freelivefootball-statistics",
        }
    return MatchStatisticsAdapter(api=_FakeApi(stats), resolver=_FakeResolver(event_id))


_PARAMS = {"home_team": "Arsenal", "away_team": "Chelsea",
           "kickoff_date": "2026-01-01", "league": "Premier League"}


def test_fetch_returns_none_when_event_id_unresolved():
    adapter = _adapter(event_id=None)
    assert adapter.fetch(_PARAMS) is None


def test_fetch_returns_none_when_no_stats():
    adapter = _adapter(stats=None)
    assert adapter.fetch(_PARAMS) is None


def test_fetch_calls_get_match_statistics_with_resolved_id():
    adapter = _adapter(event_id=999)
    adapter.fetch(_PARAMS)
    assert adapter._api.calls == [999]


def test_normalize_maps_only_approved_scope_fields():
    adapter = _adapter()
    raw = adapter.fetch(_PARAMS)
    records = adapter.normalize(raw)
    assert len(records) == 1
    r = records[0]
    assert r["home_possession"] == 61.0
    assert r["away_possession"] == 39.0
    assert r["home_xg_actual"] == 1.8
    assert r["away_xg_actual"] == 0.9
    assert r["stats_source"] == "freelivefootball"
    # Scope explicit aprobat — NICIODATĂ scrise de acest adaptor:
    assert "home_big_chance" not in r and "big_chance" not in r
    assert "home_shots_on_target" not in r and "shots_on_target" not in r
    assert "home_shots_ot" not in r


def test_normalize_empty_when_no_raw_payload():
    adapter = _adapter()
    assert adapter.normalize(None) == []


def test_validate_rejects_missing_natural_key():
    adapter = _adapter()
    records = [{"home_team": "", "away_team": "Chelsea", "kickoff_date": "2026-01-01",
                "home_possession": 50.0}]
    assert adapter.validate(records) == []


def test_validate_rejects_rows_with_no_useful_value():
    adapter = _adapter()
    records = [{"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-01-01",
                "home_possession": None, "away_possession": None,
                "home_xg_actual": None, "away_xg_actual": None}]
    assert adapter.validate(records) == []


def test_validate_accepts_row_with_at_least_one_value():
    adapter = _adapter()
    records = [{"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-01-01",
                "home_possession": 55.0, "away_possession": None,
                "home_xg_actual": None, "away_xg_actual": None}]
    assert len(adapter.validate(records)) == 1


def test_persist_calls_upsert_match_per_record(monkeypatch):
    calls: list = []
    monkeypatch.setattr("database.queries.upsert_match", lambda row: (calls.append(row), True)[1])
    adapter = _adapter()
    records = [{"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-01-01",
                "home_possession": 55.0}]
    ok = adapter.persist(records)
    assert ok is True
    assert calls == records


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    monkeypatch.setattr("database.queries.upsert_match", lambda row: False)
    adapter = _adapter()
    records = [{"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-01-01",
                "home_possession": 55.0}]
    assert adapter.persist(records) is False


def test_coverage_check_always_true():
    adapter = _adapter()
    assert adapter.coverage_check({}) is True


def test_provider_id_is_freelivefootball():
    assert MatchStatisticsAdapter.provider_id == "freelivefootball"


def test_end_to_end_fetch_normalize_validate(monkeypatch):
    calls: list = []
    monkeypatch.setattr("database.queries.upsert_match", lambda row: (calls.append(row), True)[1])
    adapter = _adapter()
    raw = adapter.fetch(_PARAMS)
    records = adapter.validate(adapter.normalize(raw))
    assert adapter.persist(records) is True
    assert len(calls) == 1
    assert calls[0]["home_team"]  # normalizat, nevid
