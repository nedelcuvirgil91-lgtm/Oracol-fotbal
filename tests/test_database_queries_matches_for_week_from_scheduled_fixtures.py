"""Teste pentru database.queries.get_matches_for_week_from_scheduled_fixtures()
— fallback de ULTIMĂ INSTANȚĂ pentru oracle_api.get_matches_for_week(),
adăugat 2026-08-10 după un incident live confirmat (ESPN a întors zero
rezultate pe toate cele 98 de interogări ale cascadei live, deși
scheduled_fixtures avea deja 76 de meciuri pentru aceeași fereastră — 62
pierdute complet).

Verifică: (1) forma dicționarului returnat e compatibilă cu cea produsă
de get_matches_for_week_from_history()/cascada live, (2) fixture_id
sintetic stabil din id-ul rândului, (3) setul "covered" conține doar
ligile cu rânduri, (4) degradare fără excepție la client absent/eroare."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    def select(self, *a, **kw):
        self._calls.append(("select", a, kw)); return self

    def in_(self, *a, **kw):
        self._calls.append(("in_", a, kw)); return self

    def gte(self, *a, **kw):
        self._calls.append(("gte", a, kw)); return self

    def lte(self, *a, **kw):
        self._calls.append(("lte", a, kw)); return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows
        self.calls: list = []

    def table(self, name):
        return _FakeQuery(self._rows, self.calls)


def _client(rows, monkeypatch) -> _FakeClient:
    fake = _FakeClient(rows)
    monkeypatch.setattr(q, "get_client", lambda: fake)
    return fake


def test_returns_matches_with_expected_dict_shape(monkeypatch):
    _client([{
        "id": 42, "home_team_canonical": "Houston Dynamo",
        "away_team_canonical": "Seattle Sounders", "league": "MLS",
        "kickoff_date": "2026-08-15", "kickoff_utc": "2026-08-15T23:30:00+00:00",
        "venue_city": "Houston", "status": "scheduled",
    }], monkeypatch)

    matches, covered = q.get_matches_for_week_from_scheduled_fixtures(
        ["MLS"], "2026-08-10", "2026-08-17",
    )

    assert covered == {"MLS"}
    assert len(matches) == 1
    m = matches[0]
    assert m["fixture_id"] == "scheduled_42"
    assert m["home_team"] == "Houston Dynamo"
    assert m["away_team"] == "Seattle Sounders"
    assert m["home_team_id"] == "" and m["away_team_id"] == ""
    assert m["kickoff_utc"] == "2026-08-15T23:30:00+00:00"
    assert m["kickoff_date"] == "2026-08-15"
    assert m["league"] == "MLS"
    assert m["season"] is None
    assert m["venue_city"] == "Houston"
    assert m["status"] == "scheduled"
    assert m["coverage_level"] == ""
    assert m["home_odds"] is None and m["draw_odds"] is None and m["away_odds"] is None
    assert m["odds_source"] is None
    assert m["source"] == "scheduled_fixtures"


def test_fixture_id_synthesized_stable_from_row_id(monkeypatch):
    _client([{
        "id": 7, "home_team_canonical": "A", "away_team_canonical": "B",
        "league": "MLS", "kickoff_date": "2026-08-15",
    }], monkeypatch)
    matches, _covered = q.get_matches_for_week_from_scheduled_fixtures(
        ["MLS"], "2026-08-10", "2026-08-17",
    )
    assert matches[0]["fixture_id"] == "scheduled_7"


def test_kickoff_utc_falls_back_to_kickoff_date_when_missing(monkeypatch):
    _client([{
        "id": 1, "home_team_canonical": "A", "away_team_canonical": "B",
        "league": "MLS", "kickoff_date": "2026-08-15", "kickoff_utc": None,
    }], monkeypatch)
    matches, _covered = q.get_matches_for_week_from_scheduled_fixtures(
        ["MLS"], "2026-08-10", "2026-08-17",
    )
    assert matches[0]["kickoff_utc"] == "2026-08-15"


def test_rows_missing_team_or_league_are_skipped(monkeypatch):
    _client([
        {"id": 1, "home_team_canonical": "", "away_team_canonical": "B",
         "league": "MLS", "kickoff_date": "2026-08-15"},
        {"id": 2, "home_team_canonical": "A", "away_team_canonical": "B",
         "league": "", "kickoff_date": "2026-08-15"},
    ], monkeypatch)

    matches, covered = q.get_matches_for_week_from_scheduled_fixtures(
        ["MLS"], "2026-08-10", "2026-08-17",
    )
    assert matches == []
    assert covered == set()


def test_covered_set_only_includes_leagues_with_rows(monkeypatch):
    _client([{
        "id": 1, "home_team_canonical": "A", "away_team_canonical": "B",
        "league": "MLS", "kickoff_date": "2026-08-15",
    }], monkeypatch)

    matches, covered = q.get_matches_for_week_from_scheduled_fixtures(
        ["MLS", "Premier League"], "2026-08-10", "2026-08-17",
    )
    assert covered == {"MLS"}
    assert "Premier League" not in covered


def test_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    matches, covered = q.get_matches_for_week_from_scheduled_fixtures(
        ["MLS"], "2026-08-10", "2026-08-17",
    )
    assert matches == [] and covered == set()


def test_degrades_gracefully_on_exception(monkeypatch):
    class _RaisingClient:
        def table(self, name):
            raise RuntimeError("boom")

    monkeypatch.setattr(q, "get_client", lambda: _RaisingClient())
    matches, covered = q.get_matches_for_week_from_scheduled_fixtures(
        ["MLS"], "2026-08-10", "2026-08-17",
    )
    assert matches == [] and covered == set()
