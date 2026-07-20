"""Teste pentru ADR-023 (Variant C) / ADR-035 D2 — database.queries.get_latest_team_elo(),
funcția nouă de tip bulk-fetch + cache ce citește match_history.home_elo_after/
away_elo_after (Canonical Live ELO Snapshot).

Verifică, la nivel de unitate, exact ce demonstrează analiza arhitecturală
D2: (1) perspectiva home/away corectă, (2) interogarea NU filtrează după
ligă — ELO e global per club, (3) rândurile cu elo_after încă NULL
(backfill întârziat, ADR-023 Consecința #4) sunt sărite, nu aproximate,
(4) cache in-memory per proces, (5) degradare fără excepție la client
absent/eroare de rețea."""
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

    def or_(self, *a, **kw):
        self._calls.append(("or_", a, kw)); return self

    def eq(self, *a, **kw):
        self._calls.append(("eq", a, kw)); return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        self._calls.append(("is_", a, kw)); return self

    def order(self, *a, **kw):
        self._calls.append(("order", a, kw)); return self

    def limit(self, *a, **kw):
        self._calls.append(("limit", a, kw)); return self

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
    q._team_elo_cache.clear()
    return fake


def test_reads_most_recent_finished_match_home_perspective(monkeypatch):
    rows = [{"home_team": "Dinamo", "away_team": "Petrolul",
             "home_elo_after": 1611, "away_elo_after": 1459,
             "kickoff_date": "2026-07-18"}]
    _client(rows, monkeypatch)
    assert q.get_latest_team_elo("Dinamo") == 1611


def test_reads_most_recent_finished_match_away_perspective(monkeypatch):
    rows = [{"home_team": "Petrolul", "away_team": "Dinamo",
             "home_elo_after": 1459, "away_elo_after": 1611,
             "kickoff_date": "2026-07-18"}]
    _client(rows, monkeypatch)
    assert q.get_latest_team_elo("Dinamo") == 1611


def test_query_has_no_league_filter():
    """Dovadă directă a pct. 3 din analiza D2: ELO e global per club —
    query-ul nu conține niciun .eq('league', ...)."""
    import inspect
    source = inspect.getsource(q.get_latest_team_elo)
    assert ".eq(" not in source, (
        "get_latest_team_elo() nu trebuie să filtreze după ligă — ELO e "
        "urmărit global per club (ELOTracker, sync/backfill_features.py)."
    )


def test_skips_rows_with_null_elo_after_in_lookback_window(monkeypatch):
    rows = [
        {"home_team": "Dinamo", "away_team": "X", "home_elo_after": None,
         "away_elo_after": None, "kickoff_date": "2026-07-18"},
        {"home_team": "Dinamo", "away_team": "Y", "home_elo_after": 1600,
         "away_elo_after": None, "kickoff_date": "2026-07-10"},
    ]
    _client(rows, monkeypatch)
    assert q.get_latest_team_elo("Dinamo") == 1600


def test_returns_none_when_all_rows_in_window_have_null_elo(monkeypatch):
    rows = [{"home_team": "Dinamo", "away_team": "X", "home_elo_after": None,
             "away_elo_after": None, "kickoff_date": "2026-07-18"}]
    _client(rows, monkeypatch)
    assert q.get_latest_team_elo("Dinamo") is None


def test_returns_none_when_no_rows(monkeypatch):
    _client([], monkeypatch)
    assert q.get_latest_team_elo("Echipă Necunoscută") is None


def test_returns_none_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    q._team_elo_cache.clear()
    assert q.get_latest_team_elo("Oricine") is None


def test_returns_none_when_query_raises_instead_of_crashing(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("Supabase down")
    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    q._team_elo_cache.clear()
    assert q.get_latest_team_elo("Oricine") is None


def test_caches_result_avoiding_second_query(monkeypatch):
    rows = [{"home_team": "Dinamo", "away_team": "X", "home_elo_after": 1611,
             "away_elo_after": None, "kickoff_date": "2026-07-18"}]
    fake = _client(rows, monkeypatch)

    first = q.get_latest_team_elo("Dinamo")
    fake._rows = []  # dacă ar interoga din nou, ar primi listă goală
    second = q.get_latest_team_elo("Dinamo")

    assert first == second == 1611


def test_caches_none_result_too(monkeypatch):
    """Echipele fără istoric (ex. naționale) nu trebuie interogate repetat
    la fiecare meci predicted în același batch."""
    fake = _client([], monkeypatch)
    q.get_latest_team_elo("Franța")
    calls_after_first = len(fake.calls)
    q.get_latest_team_elo("Franța")
    assert len(fake.calls) == calls_after_first
