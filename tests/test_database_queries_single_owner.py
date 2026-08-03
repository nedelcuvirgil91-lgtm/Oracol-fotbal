"""Teste pentru functiile Single Owner adaugate in database.queries.py
(Pasul 1 Master Repair Plan, ADR-045): get_match_ids_with_complete_
flashscore_stats, get_flashscore_covered_standings_leagues,
has_flashscore_h2h_context, plus regresia pentru
get_finished_matches_missing_stats(include_id=...). Fara retea."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows, calls, table_name):
        self._rows = rows
        self._calls = calls
        self._table_name = table_name

    def select(self, *a, **kw):
        self._calls.append((self._table_name, "select", a, kw)); return self

    def eq(self, *a, **kw):
        self._calls.append((self._table_name, "eq", a, kw)); return self

    def or_(self, *a, **kw):
        self._calls.append((self._table_name, "or_", a, kw)); return self

    def in_(self, *a, **kw):
        self._calls.append((self._table_name, "in_", a, kw)); return self

    def gte(self, *a, **kw):
        self._calls.append((self._table_name, "gte", a, kw)); return self

    @property
    def not_(self):
        return self

    def limit(self, *a, **kw):
        self._calls.append((self._table_name, "limit", a, kw)); return self

    def order(self, *a, **kw):
        self._calls.append((self._table_name, "order", a, kw)); return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, rows_by_table: dict[str, list[dict]]):
        self._rows_by_table = rows_by_table
        self.calls: list = []

    def table(self, name):
        return _FakeQuery(self._rows_by_table.get(name, []), self.calls, name)


class _BoomClient:
    def table(self, name):
        raise RuntimeError("simulated network failure")


# ════════════════════════════════════════════════════════════════════════
# get_match_ids_with_complete_flashscore_stats
# ════════════════════════════════════════════════════════════════════════

def test_get_match_ids_with_complete_flashscore_stats_returns_matching_ids(monkeypatch):
    fake = _FakeClient({"flashscore_data_completeness": [{"match_id": 1}, {"match_id": 3}]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_match_ids_with_complete_flashscore_stats([1, 2, 3])
    assert result == {1, 3}


def test_get_match_ids_with_complete_flashscore_stats_empty_input_no_query(monkeypatch):
    fake = _FakeClient({})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_match_ids_with_complete_flashscore_stats([]) == set()
    assert fake.calls == []


def test_get_match_ids_with_complete_flashscore_stats_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_match_ids_with_complete_flashscore_stats([1, 2]) == set()


def test_get_match_ids_with_complete_flashscore_stats_network_error_returns_empty(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_match_ids_with_complete_flashscore_stats([1]) == set()


# ════════════════════════════════════════════════════════════════════════
# get_flashscore_covered_standings_leagues
# ════════════════════════════════════════════════════════════════════════

def test_get_flashscore_covered_standings_leagues_returns_distinct_names(monkeypatch):
    fake = _FakeClient({"flashscore_standings_snapshot": [
        {"competition": "Premier League"}, {"competition": "Premier League"},
        {"competition": "Romania SuperLiga"},
    ]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    result = q.get_flashscore_covered_standings_leagues()
    assert result == {"Premier League", "Romania SuperLiga"}


def test_get_flashscore_covered_standings_leagues_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_flashscore_covered_standings_leagues() == set()


def test_get_flashscore_covered_standings_leagues_network_error_returns_empty(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_flashscore_covered_standings_leagues() == set()


# ════════════════════════════════════════════════════════════════════════
# has_flashscore_h2h_context
# ════════════════════════════════════════════════════════════════════════

def test_has_flashscore_h2h_context_true_when_context_exists(monkeypatch):
    fake = _FakeClient({
        "match_history": [{"id": 42}],
        "flashscore_match_context": [{"id": 7}],
    })
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.has_flashscore_h2h_context("Team A", "Team B") is True


def test_has_flashscore_h2h_context_false_when_no_matching_pair(monkeypatch):
    fake = _FakeClient({"match_history": [], "flashscore_match_context": []})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.has_flashscore_h2h_context("Team A", "Team B") is False


def test_has_flashscore_h2h_context_false_when_pair_exists_but_no_context(monkeypatch):
    fake = _FakeClient({
        "match_history": [{"id": 42}],
        "flashscore_match_context": [],
    })
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.has_flashscore_h2h_context("Team A", "Team B") is False


def test_has_flashscore_h2h_context_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.has_flashscore_h2h_context("Team A", "Team B") is False


def test_has_flashscore_h2h_context_network_error_returns_false(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.has_flashscore_h2h_context("Team A", "Team B") is False


# ════════════════════════════════════════════════════════════════════════
# get_finished_matches_missing_stats(include_id=...) — regresie
# ════════════════════════════════════════════════════════════════════════

def test_get_finished_matches_missing_stats_default_excludes_id(monkeypatch):
    fake = _FakeClient({"match_history": [{"home_team": "A", "away_team": "B"}]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(days_back=2)
    select_calls = [c for c in fake.calls if c[1] == "select"]
    assert select_calls[0][2] == ("home_team,away_team,kickoff_date,league",)


def test_get_finished_matches_missing_stats_include_id_adds_id_column(monkeypatch):
    fake = _FakeClient({"match_history": [{"id": 1, "home_team": "A", "away_team": "B"}]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_finished_matches_missing_stats(days_back=2, include_id=True)
    select_calls = [c for c in fake.calls if c[1] == "select"]
    assert select_calls[0][2] == ("id,home_team,away_team,kickoff_date,league",)
