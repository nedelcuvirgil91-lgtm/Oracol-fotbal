"""Teste pentru database.queries — citirile I/O noi din Faza 2 (ADR-044 §5,
Team DNA): get_team_recent_advanced_stats, get_team_recent_statistics_
extended, get_team_recent_player_ratings, get_team_standings_row.

Verifică: rezoluția home/away corectă pentru tabelele EAV fără coloană de
echipă nativă (match_statistics_extended, player_match_stats), degradare
fără excepție la client absent/eroare de rețea, listă goală când echipa
n-are meciuri recente. Fără rețea."""
from __future__ import annotations

from datetime import datetime, timedelta

import database.queries as q


class _FakeResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _FakeQuery:
    def __init__(self, rows, calls, table_name):
        self._rows = rows
        self._calls = calls
        self._table_name = table_name
        self._count_requested = False

    def select(self, *a, **kw):
        self._calls.append((self._table_name, "select", a, kw))
        if kw.get("count") == "exact":
            self._count_requested = True
        return self

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

    def is_(self, *a, **kw):
        self._calls.append((self._table_name, "is_", a, kw)); return self

    def order(self, *a, **kw):
        self._calls.append((self._table_name, "order", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append((self._table_name, "limit", a, kw)); return self

    def execute(self):
        count = len(self._rows) if self._count_requested else None
        return _FakeResult(self._rows, count=count)


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


def test_get_team_recent_advanced_stats_applies_since_date_when_given(monkeypatch):
    fake = _FakeClient({"match_history": []})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_team_recent_advanced_stats("Dinamo", "Romania SuperLiga", since_date="2026-07-01")
    gte_calls = [c for c in fake.calls if c[1] == "gte"]
    assert gte_calls == [("match_history", "gte", ("kickoff_date", "2026-07-01"), {})]


def test_get_team_recent_advanced_stats_no_since_date_skips_gte(monkeypatch):
    fake = _FakeClient({"match_history": []})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_team_recent_advanced_stats("Dinamo", "Romania SuperLiga")
    assert not [c for c in fake.calls if c[1] == "gte"]


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


def test_get_team_recent_statistics_extended_forwards_since_date_to_side_map(monkeypatch):
    fake = _FakeClient({"match_history": []})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    q.get_team_recent_statistics_extended("Dinamo", "Romania SuperLiga", since_date="2026-07-01")
    gte_calls = [c for c in fake.calls if c[1] == "gte"]
    assert gte_calls == [("match_history", "gte", ("kickoff_date", "2026-07-01"), {})]


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


# ════════════════════════════════════════════════════════════════════════
# is_flashscore_match_already_collected (Delta Sync)
# ════════════════════════════════════════════════════════════════════════

def test_is_flashscore_match_already_collected_true_when_row_exists(monkeypatch):
    fake = _FakeClient({"match_history": [{"id": 42}]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.is_flashscore_match_already_collected("abc123") is True
    call = next(c for c in fake.calls if c[0] == "match_history" and c[1] == "eq")
    assert call[2] == ("fixture_id", "flashscore_abc123")


def test_is_flashscore_match_already_collected_false_when_no_row(monkeypatch):
    fake = _FakeClient({"match_history": []})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.is_flashscore_match_already_collected("never-seen") is False


def test_is_flashscore_match_already_collected_false_when_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.is_flashscore_match_already_collected("abc123") is False


def test_is_flashscore_match_already_collected_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.is_flashscore_match_already_collected("abc123") is False


def test_is_flashscore_match_already_collected_true_when_result_already_set(monkeypatch):
    """[FIX 2026-08-05] Meci complet (are actual_result) - True indiferent de kickoff."""
    row = {"id": 1, "kickoff_date": "2020-01-01T15:00:00", "actual_result": "H"}
    fake = _FakeClient({"match_history": [row]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.is_flashscore_match_already_collected("abc123") is True


def test_is_flashscore_match_already_collected_true_when_kickoff_still_future(monkeypatch):
    """[FIX 2026-08-05] Meci-schelet (fara rezultat) dar inca neinceput - True,
    normal sa nu aiba inca rezultat, nu are rost sa reincercam fetch."""
    future = (datetime.now() + timedelta(days=3)).isoformat()
    row = {"id": 1, "kickoff_date": future, "actual_result": None}
    fake = _FakeClient({"match_history": [row]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.is_flashscore_match_already_collected("abc123") is True


def test_is_flashscore_match_already_collected_false_when_kickoff_past_no_result(monkeypatch):
    """[FIX 2026-08-05] Chiar problema gasita: meci-schelet ramas fara rezultat
    MULT dupa ce ar fi trebuit sa se joace - False, reincercam fetch/persist,
    ca sa nu ramana blocat la nesfarsit prin Delta Sync."""
    past = (datetime.now() - timedelta(days=2)).isoformat()
    row = {"id": 1, "kickoff_date": past, "actual_result": None}
    fake = _FakeClient({"match_history": [row]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.is_flashscore_match_already_collected("abc123") is False


def test_is_flashscore_match_already_collected_false_when_kickoff_few_hours_ago(monkeypatch):
    """[REGRESIE — ar fi prins bug-ul de semn gasit la re-verificare: prima
    varianta a fix-ului aduna marja la kickoff (kickoff + 6h > now), care
    trata orice moment pana la 6h DUPA kickoff drept "sarim" - un meci
    inceput acum 3 ore (aproape sigur terminat) tot ar fi fost sarit
    definitiv. Kickoff cu doar cateva ore in urma (nu zile, ca la testul
    de mai sus) - trebuie sa reincercam (False), nu doar kickoff din trecut
    indepartat."""
    past = (datetime.now() - timedelta(hours=3)).isoformat()
    row = {"id": 1, "kickoff_date": past, "actual_result": None}
    fake = _FakeClient({"match_history": [row]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.is_flashscore_match_already_collected("abc123") is False


def test_is_flashscore_match_already_collected_true_when_kickoff_unparsable(monkeypatch):
    """Data neparsabila - nu se ghiceste, comportament neschimbat (True, siguranta)."""
    row = {"id": 1, "kickoff_date": "not-a-date", "actual_result": None}
    fake = _FakeClient({"match_history": [row]})
    monkeypatch.setattr(q, "get_client", lambda: fake)
    assert q.is_flashscore_match_already_collected("abc123") is True


# ════════════════════════════════════════════════════════════════════════
# get_finishing_data_readiness
# ════════════════════════════════════════════════════════════════════════

def test_get_finishing_data_readiness_returns_counts_bound_to_season(monkeypatch):
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    fake = _FakeClient({"match_history": rows})
    monkeypatch.setattr(q, "get_client", lambda: fake)

    out = q.get_finishing_data_readiness("2026-07-01")

    assert out == {"finished_total": 3, "shots_on_target": 3, "xg": 3}
    # [DECIS — proprietarul produsului, sesiune 2026-08-15] pragul de 400 e
    # STRICT pe sezonul curent — toate cele 3 interogări trebuie mărginite.
    gte_calls = [c for c in fake.calls if c[1] == "gte"]
    assert len(gte_calls) == 3
    assert all(c == ("match_history", "gte", ("kickoff_date", "2026-07-01"), {}) for c in gte_calls)


def test_get_finishing_data_readiness_no_client(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_finishing_data_readiness("2026-07-01") == {"finished_total": 0, "shots_on_target": 0, "xg": 0}


def test_get_finishing_data_readiness_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    assert q.get_finishing_data_readiness("2026-07-01") == {"finished_total": 0, "shots_on_target": 0, "xg": 0}
