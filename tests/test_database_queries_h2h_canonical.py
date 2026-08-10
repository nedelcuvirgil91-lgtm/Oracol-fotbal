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


# ════════════════════════════════════════════════════════════════════════
# ADR-045 — H2H Owner (Flashscore, 14 ligi FLASHSCORE_TRACKED_COMPETITIONS)
# ════════════════════════════════════════════════════════════════════════
# get_h2h_from_history() e sursa canonică folosită deja de _build_h2h() —
# repointarea "de facto" la Flashscore pentru H2H (ADR-045, rândul 7 din
# matricea Owner/Fallback) nu cere COD nou: match_history include deja,
# fără nicio schimbare, rezultatele scrise de Flashscore pentru cele 14
# competiții tracked (Faza 2/3, Foundation Data Layer, `persist_match_
# foundation_data()`). Testele de mai jos dovedesc mecanic proprietatea
# care face asta adevărat — get_h2h_from_history() e complet agnostic
# de sursă/provider, nu filtrează niciodată după `source`/`fixture_id`.

def test_query_has_no_source_or_fixture_id_filter():
    """Dovadă directă: interogarea nu conține niciun `.eq('source', ...)`
    sau `.eq('fixture_id', ...)` — rândurile scrise de Flashscore
    (fixture_id = 'flashscore_<mid>') sunt incluse identic cu orice alt
    provider, fără nicio cale de cod separată."""
    import inspect
    source = inspect.getsource(q.get_h2h_from_history)
    assert "source" not in source.split('"""')[-1]  # cod, nu docstring
    assert "fixture_id" not in source.split('"""')[-1]


def test_flashscore_sourced_rows_returned_identically_to_any_other_provider(monkeypatch):
    """Regresie directă pentru ADR-045: un rând `match_history` scris de
    Flashscore (fixture_id prefixat 'flashscore_', convenție confirmată în
    `normalize_match_statistics()`) apare în rezultat exact ca un rând de
    la orice alt provider — niciun filtru/excludere per sursă."""
    rows = [
        {"home_team": "TeamA", "away_team": "TeamB", "actual_home_goals": 2,
         "actual_away_goals": 1, "actual_result": "H", "kickoff_date": "2026-05-01",
         "league": "Romania SuperLiga", "fixture_id": "flashscore_EeqI7WJc"},
        {"home_team": "TeamB", "away_team": "TeamA", "actual_home_goals": 0,
         "actual_away_goals": 0, "actual_result": "D", "kickoff_date": "2025-11-01",
         "league": "Romania SuperLiga", "fixture_id": "footballdata_9981"},
    ]
    _client(rows, monkeypatch)
    out = q.get_h2h_from_history("TeamA", "TeamB")
    assert out == rows
    assert any(r["fixture_id"].startswith("flashscore_") for r in out)
