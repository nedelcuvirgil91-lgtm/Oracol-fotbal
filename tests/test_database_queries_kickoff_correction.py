"""Teste pentru database.queries.correct_flashscore_kickoff_if_mismatched()
(ADR-070) — fără rețea, Supabase mock-uit prin monkeypatch.

NU e o cale nouă de scriere: funcția citește rândul existent, decide DACĂ
corectează, apoi deleagă scrierea la `upsert_match()` (RPC-ul canonic deja
existent, migrarea 048) — testele de aici verifică decizia (când se apelează
`upsert_match`, cu ce payload), nu re-testează RPC-ul însuși (deja acoperit
de `tests/test_rpc_write_ok_reschedule.py`)."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeSelectQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **kw):
        return self

    def eq(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, match_history_rows=None):
        self._tables = {"match_history": match_history_rows or []}

    def table(self, name):
        return _FakeSelectQuery(self._tables.get(name, []))


def test_no_client_returns_false_without_upsert_call(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    called = []
    monkeypatch.setattr(q, "upsert_match", lambda payload: called.append(payload) or True)
    assert q.correct_flashscore_kickoff_if_mismatched(
        "flashscore_x", "A", "B", "Liga X", "2026-08-30",
    ) is False
    assert called == []


def test_missing_fixture_id_or_kickoff_returns_false_early(monkeypatch):
    called = []
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient())
    monkeypatch.setattr(q, "upsert_match", lambda payload: called.append(payload) or True)
    assert q.correct_flashscore_kickoff_if_mismatched("", "A", "B", "Liga X", "2026-08-30") is False
    assert q.correct_flashscore_kickoff_if_mismatched("flashscore_x", "A", "B", "Liga X", "") is False
    assert called == []


def test_fixture_not_found_returns_false_without_upsert_call(monkeypatch):
    called = []
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient(match_history_rows=[]))
    monkeypatch.setattr(q, "upsert_match", lambda payload: called.append(payload) or True)
    assert q.correct_flashscore_kickoff_if_mismatched(
        "flashscore_necunoscut", "A", "B", "Liga X", "2026-08-30",
    ) is False
    assert called == []


def test_already_played_match_never_gets_corrected(monkeypatch):
    """Garda centrală, ADR-070: un meci cu actual_result deja scris NU se
    atinge NICIODATĂ, indiferent cât de diferită e data scrapuită — ar
    rescrie identitatea unui rezultat istoric real."""
    called = []
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient(
        match_history_rows=[{"kickoff_date": "2026-08-20T17:00:00", "actual_result": "H"}],
    ))
    monkeypatch.setattr(q, "upsert_match", lambda payload: called.append(payload) or True)
    assert q.correct_flashscore_kickoff_if_mismatched(
        "flashscore_jucat", "A", "B", "Liga X", "2026-08-30",
    ) is False
    assert called == []


def test_matching_date_is_not_a_correction(monkeypatch):
    called = []
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient(
        match_history_rows=[{"kickoff_date": "2026-08-30T13:00:00", "actual_result": None}],
    ))
    monkeypatch.setattr(q, "upsert_match", lambda payload: called.append(payload) or True)
    assert q.correct_flashscore_kickoff_if_mismatched(
        "flashscore_ok", "A", "B", "Liga X", "2026-08-30T16:00:00",
    ) is False
    assert called == []


def test_mismatched_date_triggers_upsert_with_minimal_payload(monkeypatch):
    """Cazul real (ADR-070): rând scris cu dată placeholder (29 aug), data
    reală (30 aug) extrasă acum de pre_match_odds.py — payload minim,
    COALESCE pe restul coloanelor (nimic altceva trimis)."""
    called = []
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient(
        match_history_rows=[{"kickoff_date": "2026-08-29T17:00:00", "actual_result": None}],
    ))
    monkeypatch.setattr(q, "upsert_match", lambda payload: called.append(payload) or True)

    ok = q.correct_flashscore_kickoff_if_mismatched(
        "flashscore_jig21AFE", "Farul Constanța", "FC Botosani", "Romania SuperLiga",
        "2026-08-30T13:00:00",
    )

    assert ok is True
    assert called == [{
        "fixture_id": "flashscore_jig21AFE", "home_team": "Farul Constanța",
        "away_team": "FC Botosani", "league": "Romania SuperLiga",
        "kickoff_date": "2026-08-30T13:00:00",
    }]


def test_upsert_failure_is_propagated_as_false(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient(
        match_history_rows=[{"kickoff_date": "2026-08-29T17:00:00", "actual_result": None}],
    ))
    monkeypatch.setattr(q, "upsert_match", lambda payload: False)
    assert q.correct_flashscore_kickoff_if_mismatched(
        "flashscore_x", "A", "B", "Liga X", "2026-08-30T13:00:00",
    ) is False


def test_only_date_component_compared_not_time_of_day(monkeypatch):
    """Ore diferite in aceeasi zi NU declanseaza o corectie — RPC-ul insusi
    trateaza identic prin left(kickoff_date, 10)."""
    called = []
    monkeypatch.setattr(q, "get_client", lambda: _FakeClient(
        match_history_rows=[{"kickoff_date": "2026-08-30T17:00:00", "actual_result": None}],
    ))
    monkeypatch.setattr(q, "upsert_match", lambda payload: called.append(payload) or True)
    assert q.correct_flashscore_kickoff_if_mismatched(
        "flashscore_x", "A", "B", "Liga X", "2026-08-30T13:00:00",
    ) is False
    assert called == []


def test_client_exception_returns_false(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("boom")

    monkeypatch.setattr(q, "get_client", lambda: _Boom())
    assert q.correct_flashscore_kickoff_if_mismatched(
        "flashscore_x", "A", "B", "Liga X", "2026-08-30T13:00:00",
    ) is False
