"""Teste pentru fixture_discovery_common.py (R-Sync-7a, ADR-039) —
validate()/persist() partajate de cei 6 adaptori de descoperire."""
from __future__ import annotations

from fixture_discovery_common import persist_fixture_records, validate_fixture_records


def test_validate_excludes_records_without_home_team():
    records = [{"away_team": "Chelsea", "kickoff_date": "2026-08-01"}]
    assert validate_fixture_records(records, "test") == []


def test_validate_excludes_records_without_away_team():
    records = [{"home_team": "Arsenal", "kickoff_date": "2026-08-01"}]
    assert validate_fixture_records(records, "test") == []


def test_validate_excludes_records_without_kickoff_date():
    records = [{"home_team": "Arsenal", "away_team": "Chelsea"}]
    assert validate_fixture_records(records, "test") == []


def test_validate_accepts_valid_record():
    records = [{"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-08-01"}]
    out = validate_fixture_records(records, "test")
    assert len(out) == 1


def test_persist_calls_upsert_scheduled_fixture_per_record(monkeypatch):
    calls = []

    def _fake_upsert(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr("database.queries.upsert_scheduled_fixture", _fake_upsert)
    ok = persist_fixture_records(
        [{"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-08-01",
          "league": "Premier League", "freelf_event_id": "998877"}],
        "freelf",
    )
    assert ok is True
    assert len(calls) == 1
    assert calls[0]["home_team"] == "Arsenal"
    assert calls[0]["provider_id"] == "freelf"
    assert calls[0]["freelf_event_id"] == "998877"
    assert calls[0]["tsdb_home_team_id"] is None  # camp neasignat, ramane None


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    def _fake_upsert(**kwargs):
        return kwargs["home_team"] == "Arsenal"

    monkeypatch.setattr("database.queries.upsert_scheduled_fixture", _fake_upsert)
    ok = persist_fixture_records(
        [
            {"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2026-08-01"},
            {"home_team": "Liverpool", "away_team": "Arsenal", "kickoff_date": "2026-08-02"},
        ],
        "freelf",
    )
    assert ok is False
