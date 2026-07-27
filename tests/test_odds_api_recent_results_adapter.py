"""Teste pentru odds_api_recent_results_adapter.py (R-Sync-6, ADR-039).

A șasea implementare reală a SyncAdapter — fetch() delegă la
FootballOracleAPI.get_recent_completed_matches_raw() (Provider fals,
injectat, fără rețea reală). Sursă canonică unică pentru formă ȘI H2H
(audit R-Sync-6, opțiunea A)."""
from __future__ import annotations

from odds_api_recent_results_adapter import OddsApiRecentResultsAdapter


_RAW_SCORES = [
    {"home_team": "Arsenal", "away_team": "Chelsea", "home_score": 2, "away_score": 1,
     "kickoff_utc": "2026-08-01T15:00:00Z", "kickoff_date": "2026-08-01",
     "league": "Premier League", "source": "the-odds-api-scores"},
    {"home_team": "Liverpool", "away_team": "Arsenal", "home_score": 0, "away_score": 0,
     "kickoff_utc": "2026-08-02T15:00:00Z", "kickoff_date": "2026-08-02",
     "league": "Premier League", "source": "the-odds-api-scores"},
]


class _FakeOracleApi:
    def __init__(self, scores=None):
        self._scores = scores if scores is not None else list(_RAW_SCORES)
        self.calls: list = []

    def get_recent_completed_matches_raw(self, sport_key, days_back=3):
        self.calls.append(("get_recent_completed_matches_raw", sport_key, days_back))
        return self._scores


def test_fetch_delegates_to_api_with_sport_key():
    fake = _FakeOracleApi()
    adapter = OddsApiRecentResultsAdapter(api=fake)
    raw = adapter.fetch({"sport_key": "soccer_epl"})
    assert raw == _RAW_SCORES
    assert ("get_recent_completed_matches_raw", "soccer_epl", 3) in fake.calls


def test_normalize_handles_none_payload():
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())
    assert adapter.normalize(None) == []


def test_normalize_produces_multiple_records_per_call():
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({"sport_key": "soccer_epl"})
    records = adapter.normalize(raw)
    assert len(records) == 2
    assert records[0]["home_team"] == "Arsenal"
    assert records[0]["away_team"] == "Chelsea"
    assert records[0]["home_score"] == 2
    assert records[0]["kickoff_date"] == "2026-08-01"


def test_normalize_calls_canonical_normalize_team_name_explicitly(monkeypatch):
    import mappings

    calls = []

    def _fake_normalize(name):
        calls.append(name)
        return f"CANONICAL[{name}]"

    monkeypatch.setattr(mappings, "normalize_team_name", _fake_normalize)
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi(scores=[_RAW_SCORES[0]]))
    raw = adapter.fetch({"sport_key": "soccer_epl"})
    records = adapter.normalize(raw)

    assert calls == ["Arsenal", "Chelsea"]
    assert records[0]["home_team"] == "CANONICAL[Arsenal]"
    assert records[0]["away_team"] == "CANONICAL[Chelsea]"


def test_validate_excludes_records_without_teams():
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())
    records = [
        {"home_team": "Arsenal", "away_team": "", "kickoff_date": "2026-08-01",
         "home_score": 2, "away_score": 1, "league": "PL"},
    ]
    assert adapter.validate(records) == []


def test_validate_excludes_records_without_kickoff_date():
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())
    records = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "",
         "home_score": 2, "away_score": 1, "league": "PL"},
    ]
    assert adapter.validate(records) == []


def test_validate_excludes_records_with_missing_scores():
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())
    records = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-08-01",
         "home_score": None, "away_score": 1, "league": "PL"},
    ]
    assert adapter.validate(records) == []


def test_validate_accepts_valid_record():
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())
    records = [
        {"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-08-01",
         "home_score": 2, "away_score": 1, "league": "PL"},
    ]
    out = adapter.validate(records)
    assert len(out) == 1


def test_persist_calls_upsert_odds_recent_result_per_record(monkeypatch):
    calls = []

    def _fake_upsert(home_team, away_team, kickoff_date, league, home_score, away_score):
        calls.append((home_team, away_team, kickoff_date, home_score, away_score))
        return True

    monkeypatch.setattr("database.queries.upsert_odds_recent_result", _fake_upsert)
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())
    ok = adapter.persist([{
        "home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-08-01",
        "league": "Premier League", "home_score": 2, "away_score": 1,
    }])
    assert ok is True
    assert calls == [("Arsenal", "Chelsea", "2026-08-01", 2, 1)]


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    calls = []

    def _fake_upsert(home_team, away_team, kickoff_date, league, home_score, away_score):
        calls.append((home_team, away_team))
        return True

    monkeypatch.setattr("database.queries.upsert_odds_recent_result", _fake_upsert)
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())

    raw = adapter.fetch({"sport_key": "soccer_epl"})
    records = adapter.normalize(raw)
    records = adapter.validate(records)
    ok = adapter.persist(records)

    assert ok is True
    assert calls == [("Arsenal", "Chelsea"), ("Liverpool", "Arsenal")]


def test_coverage_check_returns_true_deliberately():
    adapter = OddsApiRecentResultsAdapter(api=_FakeOracleApi())
    assert adapter.coverage_check({"league": "orice"}) is True
    assert "coverage_check" in OddsApiRecentResultsAdapter.__dict__
