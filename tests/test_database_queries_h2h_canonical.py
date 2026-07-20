"""Teste pentru ADR-035 / D3 — database.queries.get_h2h_from_history(),
sursa canonică Database-First pentru Head-to-Head.

Verifică proprietățile cerute explicit de deciziile D3:
(1) interogarea NU filtrează după ligă — H2H e global per pereche de cluburi
    (Decizia 1), consecvent cu ELO-ul global (D2);
(2) întoarce RÂNDURI BRUTE (apelantul recalculează din actual_result/goluri,
    Decizia 2 — niciodată coloanele precalculate h2h_modifier/h2h_meetings);
(3) degradare fără excepție la client absent / eroare de rețea."""
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
    return fake


def test_returns_raw_rows(monkeypatch):
    rows = [{"home_team": "TeamA", "away_team": "TeamB", "actual_home_goals": 2,
             "actual_away_goals": 1, "actual_result": "H", "kickoff_date": "2026-05-01"}]
    _client(rows, monkeypatch)
    out = q.get_h2h_from_history("TeamA", "TeamB")
    assert out == rows  # brute, nemodificate — recalcul e treaba apelantului


def test_query_has_no_league_filter():
    """Dovadă directă a Deciziei 1: H2H e global — query-ul nu conține
    niciun .eq('league', ...)."""
    import inspect
    source = inspect.getsource(q.get_h2h_from_history)
    assert ".eq(" not in source, (
        "get_h2h_from_history() nu trebuie să filtreze după ligă — H2H e "
        "istoricul confruntărilor între două cluburi, indiferent de competiție."
    )


def test_query_covers_both_orientations():
    """Perechea e simetrică: (home vs away) SAU (away vs home)."""
    import inspect
    source = inspect.getsource(q.get_h2h_from_history)
    assert "and(home_team.eq." in source and "away_team.eq." in source


def test_does_not_read_precalculated_h2h_columns():
    """Decizia 2: nu se ating niciodată coloanele h2h_modifier/h2h_meetings.
    Se verifică CODUL, nu docstring-ul (care le menționează tocmai ca să
    explice de ce NU sunt folosite)."""
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(q.get_h2h_from_history))
    func = tree.body[0]
    if (func.body and isinstance(func.body[0], ast.Expr)
            and isinstance(func.body[0].value, ast.Constant)):
        func.body = func.body[1:]  # elimină docstring-ul
    code_only = ast.unparse(func)
    assert "h2h_modifier" not in code_only
    assert "h2h_meetings" not in code_only


def test_returns_empty_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    assert q.get_h2h_from_history("TeamA", "TeamB") == []


def test_returns_empty_when_query_raises(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("Supabase down")
    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.get_h2h_from_history("TeamA", "TeamB") == []
