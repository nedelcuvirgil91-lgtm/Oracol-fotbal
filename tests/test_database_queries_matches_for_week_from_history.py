"""Teste pentru ADR-053 — database.queries.get_matches_for_week_from_history(),
funcția nouă de discovery Database-First pentru get_matches_for_week()
(oracle_api.py). Verifică: (1) forma dicționarului returnat e compatibilă
cu cea produsă de cascada live (_fetch_matches_fd()), (2) setul de ligi
"covered" conține doar ligile cu cel puțin un rând în fereastră, (3)
filtrarea exactă pe kickoff_date[:10] respinge rândurile în afara
ferestrei (inclusiv cazul timestamp complet), (4) status derivat din
actual_result, (5) degradare fără excepție la client absent/eroare."""
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
        "fixture_id": "fs_1", "home_team": "Dinamo", "away_team": "Rapid",
        "league": "Romania SuperLiga", "kickoff_date": "2026-08-08",
        "season": "2026/2027", "actual_result": None,
    }], monkeypatch)

    matches, covered = q.get_matches_for_week_from_history(
        ["Romania SuperLiga"], "2026-08-05", "2026-08-12",
    )

    assert covered == {"Romania SuperLiga"}
    assert len(matches) == 1
    m = matches[0]
    assert m["fixture_id"] == "fs_1"
    assert m["home_team"] == "Dinamo"
    assert m["away_team"] == "Rapid"
    assert m["home_team_id"] == "" and m["away_team_id"] == ""
    assert m["kickoff_utc"] == "2026-08-08"
    assert m["kickoff_date"] == "2026-08-08"
    assert m["league"] == "Romania SuperLiga"
    assert m["season"] == "2026/2027"
    assert m["venue_city"] == ""
    assert m["status"] == "scheduled"
    assert m["coverage_level"] == ""
    assert m["home_odds"] is None and m["draw_odds"] is None and m["away_odds"] is None
    assert m["odds_source"] is None
    assert m["source"] == "match_history"


def test_status_finished_when_actual_result_present(monkeypatch):
    _client([{
        "fixture_id": "fs_2", "home_team": "Sepsi", "away_team": "CFR Cluj",
        "league": "Romania SuperLiga", "kickoff_date": "2026-08-06",
        "season": "2026/2027", "actual_result": "H",
    }], monkeypatch)

    matches, _covered = q.get_matches_for_week_from_history(
        ["Romania SuperLiga"], "2026-08-05", "2026-08-12",
    )
    assert matches[0]["status"] == "finished"


def test_full_timestamp_kickoff_date_is_sliced_and_window_checked(monkeypatch):
    _client([{
        "fixture_id": "fs_3", "home_team": "Voluntari", "away_team": "FCSB",
        "league": "Romania SuperLiga", "kickoff_date": "2026-08-09T18:30:00",
        "season": "2026/2027", "actual_result": None,
    }], monkeypatch)

    matches, covered = q.get_matches_for_week_from_history(
        ["Romania SuperLiga"], "2026-08-05", "2026-08-12",
    )
    assert covered == {"Romania SuperLiga"}
    assert matches[0]["kickoff_date"] == "2026-08-09"
    assert matches[0]["kickoff_utc"] == "2026-08-09T18:30:00"


def test_row_outside_exact_window_is_excluded_despite_wide_sql_filter(monkeypatch):
    """SQL-level lte(d_to + 'T23:59:59') e deliberat larg — verificarea
    exactă pe kickoff_raw[:10] trebuie să respingă orice rând în afara
    ferestrei cerute (regresie posibilă dacă cineva elimină filtrul Python)."""
    _client([{
        "fixture_id": "fs_4", "home_team": "A", "away_team": "B",
        "league": "Romania SuperLiga", "kickoff_date": "2026-08-13T10:00:00",
        "season": "2026/2027", "actual_result": None,
    }], monkeypatch)

    matches, covered = q.get_matches_for_week_from_history(
        ["Romania SuperLiga"], "2026-08-05", "2026-08-12",
    )
    assert matches == []
    assert covered == set()


def test_rows_missing_team_or_league_are_skipped(monkeypatch):
    _client([
        {"fixture_id": "fs_5", "home_team": "", "away_team": "B",
         "league": "Romania SuperLiga", "kickoff_date": "2026-08-06", "actual_result": None},
        {"fixture_id": "fs_6", "home_team": "A", "away_team": "B",
         "league": "", "kickoff_date": "2026-08-06", "actual_result": None},
    ], monkeypatch)

    matches, covered = q.get_matches_for_week_from_history(
        ["Romania SuperLiga"], "2026-08-05", "2026-08-12",
    )
    assert matches == []
    assert covered == set()


def test_covered_set_only_includes_leagues_with_rows(monkeypatch):
    _client([{
        "fixture_id": "fs_7", "home_team": "Dinamo", "away_team": "Rapid",
        "league": "Romania SuperLiga", "kickoff_date": "2026-08-06",
        "season": "2026/2027", "actual_result": None,
    }], monkeypatch)

    matches, covered = q.get_matches_for_week_from_history(
        ["Romania SuperLiga", "Premier League"], "2026-08-05", "2026-08-12",
    )
    assert covered == {"Romania SuperLiga"}
    assert "Premier League" not in covered


def test_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    matches, covered = q.get_matches_for_week_from_history(
        ["Romania SuperLiga"], "2026-08-05", "2026-08-12",
    )
    assert matches == [] and covered == set()


def test_degrades_gracefully_on_exception(monkeypatch):
    class _RaisingClient:
        def table(self, name):
            raise RuntimeError("boom")

    monkeypatch.setattr(q, "get_client", lambda: _RaisingClient())
    matches, covered = q.get_matches_for_week_from_history(
        ["Romania SuperLiga"], "2026-08-05", "2026-08-12",
    )
    assert matches == [] and covered == set()
