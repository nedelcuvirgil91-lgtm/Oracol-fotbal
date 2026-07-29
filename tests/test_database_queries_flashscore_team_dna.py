"""Teste pentru database.queries — citirile I/O noi din Faza 2 (ADR-044 §5,
Team DNA): get_team_recent_advanced_stats, get_team_recent_statistics_
extended, get_team_recent_player_ratings, get_team_standings_row.

Verifică: rezoluția home/away corectă pentru tabelele EAV fără coloană de
echipă nativă (match_statistics_extended, player_match_stats), degradare
fără excepție la client absent/eroare de rețea, listă goală când echipa
n-are meciuri recente. Fără rețea."""
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

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        self._calls.append((self._table_name, "is_", a, kw)); return self

    def order(self, *a, **kw):
        self._calls.append((self._table_name, "order", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append((self._table_name, "limit", a, kw)); return self

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
# get_team_recent_advanced_stats
# ════════════════════════════════════════════════════════════════════════

def test_get_team_recent_advanced_stats_returns_raw_rows(monkeypatch):
    rows = [{"id": 1, "home_team": "Dinamo", "away_team": "Rapid", "home_xg_actual": 1.5}]
    fake = _FakeClient({"match_history": rows})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_recent_advanced_stats("Dinamo", "Romania SuperLiga") == rows


def test_get_team_recent_advanced_stats_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_team_recent_advanced_stats("Dinamo", "Romania SuperLiga") == []


def test_get_team_recent_advanced_stats_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_team_recent_advanced_stats("Dinamo", "Romania SuperLiga") == []


# ════════════════════════════════════════════════════════════════════════
# get_team_recent_statistics_extended
# ════════════════════════════════════════════════════════════════════════

def test_get_team_recent_statistics_extended_resolves_correct_side(monkeypatch):
    match_rows = [
        {"id": 1, "home_team": "Dinamo", "away_team": "Rapid"},
        {"id": 2, "home_team": "Craiova", "away_team": "Dinamo"},
    ]
    stat_rows = [
        {"match_id": 1, "stat_key": "passes", "home_value_numeric": 450.0, "away_value_numeric": 380.0},
        {"match_id": 2, "stat_key": "passes", "home_value_numeric": 400.0, "away_value_numeric": 420.0},
    ]
    fake = _FakeClient({"match_history": match_rows, "match_statistics_extended": stat_rows})
    monkeypatch.setattr(q, "get_client", lambda: fake)

    out = q.get_team_recent_statistics_extended("Dinamo", "Romania SuperLiga")

    values = {r["match_id"]: r["value"] for r in out}
    assert values[1] == 450.0   # Dinamo a fost gazdă în meciul 1
    assert values[2] == 420.0   # Dinamo a fost oaspete în meciul 2


def test_get_team_recent_statistics_extended_no_matches_returns_empty(monkeypatch):
    fake = _FakeClient({"match_history": []})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_recent_statistics_extended("Dinamo", "Romania SuperLiga") == []


def test_get_team_recent_statistics_extended_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_team_recent_statistics_extended("Dinamo", "Romania SuperLiga") == []


# ════════════════════════════════════════════════════════════════════════
# get_team_recent_player_ratings
# ════════════════════════════════════════════════════════════════════════

def test_get_team_recent_player_ratings_filters_by_resolved_side(monkeypatch):
    match_rows = [{"id": 1, "home_team": "Dinamo", "away_team": "Rapid"}]
    player_rows = [
        {"match_id": 1, "team": "home", "player_name": "Pop A.", "rating": 7.5, "minutes_played": 90},
        {"match_id": 1, "team": "away", "player_name": "X. Y.", "rating": 6.0, "minutes_played": 90},
    ]
    fake = _FakeClient({"match_history": match_rows, "player_match_stats": player_rows})
    monkeypatch.setattr(q, "get_client", lambda: fake)

    out = q.get_team_recent_player_ratings("Dinamo", "Romania SuperLiga")

    assert len(out) == 1
    assert out[0]["player_name"] == "Pop A."


def test_get_team_recent_player_ratings_excludes_rows_without_rating(monkeypatch):
    match_rows = [{"id": 1, "home_team": "Dinamo", "away_team": "Rapid"}]
    player_rows = [{"match_id": 1, "team": "home", "player_name": "Pop A.", "rating": None}]
    fake = _FakeClient({"match_history": match_rows, "player_match_stats": player_rows})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_recent_player_ratings("Dinamo", "Romania SuperLiga") == []


def test_get_team_recent_player_ratings_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_team_recent_player_ratings("Dinamo", "Romania SuperLiga") == []


# ════════════════════════════════════════════════════════════════════════
# get_team_standings_row
# ════════════════════════════════════════════════════════════════════════

def test_get_team_standings_row_filters_by_team(monkeypatch):
    rows = [{"team": "Dinamo", "rank": 3}, {"team": "Rapid", "rank": 1}]
    fake = _FakeClient({"flashscore_standings_snapshot": rows})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    out = q.get_team_standings_row("Dinamo", "Romania SuperLiga")
    assert out == {"team": "Dinamo", "rank": 3}


def test_get_team_standings_row_returns_none_when_team_not_found(monkeypatch):
    rows = [{"team": "Rapid", "rank": 1}]
    fake = _FakeClient({"flashscore_standings_snapshot": rows})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.get_team_standings_row("Dinamo", "Romania SuperLiga") is None


def test_get_team_standings_row_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_team_standings_row("Dinamo", "Romania SuperLiga") is None
