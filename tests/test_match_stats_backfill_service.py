"""
Teste pentru MatchStatsBackfillService — generic, fara nicio referinta la o
liga anume in logica testata. Fara retea, fara Supabase live.

Acopera specific ce nu era acoperit de test_odds_backfill_service.py:
gating-ul per-coloana NULL (Regula #13 — Protecția Writer-ilor) — o valoare
deja populata nu trebuie niciodata suprascrisa, iar o coloana lipsa in sursa
nu trebuie niciodata scrisa ca aproximare.
"""
from datetime import datetime, timedelta, timezone

import services.match_stats_backfill_service as svc


def _iso_date(days_ago: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


class _FakeTable:
    def __init__(self, rows, update_sink):
        self._rows = rows
        self._update_sink = update_sink
        self._pending_update = None

    def select(self, cols):
        return self

    def eq(self, col, val):
        if self._pending_update is not None:
            match = next((r for r in self._rows if r["id"] == val), None)
            if match is not None:
                match.update(self._pending_update)
            self._update_sink.append((val, dict(self._pending_update)))
            self._pending_update = None
        return self

    def gte(self, col, val):
        return self

    class _Not:
        def __init__(self, outer):
            self.outer = outer
        def is_(self, col, val):
            return self.outer

    @property
    def not_(self):
        return self._Not(self)

    def range(self, start, end):
        self._range = (start, end)
        return self

    def update(self, values):
        self._pending_update = values
        return self

    def execute(self):
        class Res:
            pass
        r = Res()
        if hasattr(self, "_range"):
            start, end = self._range
            r.data = self._rows[start:end + 1]
        else:
            r.data = [1]  # update "succes"
        return r


class _FakeClient:
    def __init__(self, match_history_rows, update_sink):
        self._rows = match_history_rows
        self._update_sink = update_sink

    def table(self, name):
        assert name == "match_history"
        return _FakeTable(self._rows, self._update_sink)


class _FakeSb:
    def __init__(self, client):
        self._client = client

    def get_client(self):
        return self._client


def _mh_row(id_, home, away, days_ago, hg, ag, **existing_stats):
    row = {
        "id": id_, "fixture_id": f"fd_{id_}", "home_team": home, "away_team": away,
        "kickoff_date": _iso_date(days_ago), "actual_home_goals": hg, "actual_away_goals": ag,
    }
    row.update(existing_stats)
    return row


def _source_row(home_raw, away_raw, days_ago, hg, ag, **stats):
    row = {
        "match_date": _iso_date(days_ago), "home_team_raw": home_raw, "away_team_raw": away_raw,
        "home_goals": hg, "away_goals": ag,
    }
    row.update(stats)
    return row


COLUMNS = ["home_shots", "away_shots", "home_shots_on_target", "away_shots_on_target"]


def _service(match_history_rows, source_rows, update_sink, columns=COLUMNS):
    client = _FakeClient(match_history_rows, update_sink)
    sb = _FakeSb(client)

    def importer(division, season, min_date):
        return source_rows

    return svc.MatchStatsBackfillService(
        provider="test-provider", division="X0", season=None,
        importer=importer, league="Test League", columns=columns, supabase_client=sb,
    )


def test_writes_only_null_columns_never_overwrites():
    """Cerinta centrala (Regula #13): home_shots deja populat NU trebuie
    atins, dar away_shots (NULL) trebuie completat."""
    mh = [_mh_row(1, "Team A", "Team B", 10, 2, 1, home_shots=99)]
    src = [_source_row("Team A", "Team B", 10, 2, 1,
                        home_shots=12, away_shots=8, home_shots_on_target=5, away_shots_on_target=3)]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 1
    assert result.written_ok == 1
    assert sink[0][1] == {
        "away_shots": 8, "home_shots_on_target": 5, "away_shots_on_target": 3,
    }, "home_shots era deja populat (99) si NU trebuia inclus in UPDATE"
    assert mh[0]["home_shots"] == 99, "valoarea reala preexistenta a fost suprascrisa — regresie destructiva"


def test_source_missing_column_never_written_as_approximation():
    """Daca sursa nu are o valoare pentru o coloana, acea coloana nu apare
    deloc in payload-ul de UPDATE — nu se scrie 0 sau None."""
    mh = [_mh_row(1, "Team A", "Team B", 10, 2, 1)]
    src = [_source_row("Team A", "Team B", 10, 2, 1, home_shots=12, away_shots=8)]  # fara target
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 1
    assert sink[0][1] == {"home_shots": 12, "away_shots": 8}
    assert "home_shots_on_target" not in sink[0][1]
    assert "away_shots_on_target" not in sink[0][1]


def test_already_complete_row_generates_no_update_call():
    mh = [_mh_row(1, "Team A", "Team B", 10, 2, 1,
                  home_shots=1, away_shots=2, home_shots_on_target=3, away_shots_on_target=4)]
    src = [_source_row("Team A", "Team B", 10, 2, 1,
                        home_shots=99, away_shots=99, home_shots_on_target=99, away_shots_on_target=99)]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 1
    assert result.already_complete == 1
    assert result.written_ok == 0
    assert sink == []


def test_no_match_rejected_fail_closed():
    mh = [_mh_row(1, "Team A", "Team B", 10, 2, 1)]
    src = [_source_row("Team C", "Team D", 10, 0, 0, home_shots=1)]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 0
    assert result.rejected_no_match == 1
    assert sink == []


def test_ambiguous_match_rejected_not_guessed():
    mh = [
        _mh_row(1, "Team A", "Team B", 10, 2, 1),
        _mh_row(2, "Team A", "Team B", 10, 2, 1),
    ]
    src = [_source_row("Team A", "Team B", 10, 2, 1, home_shots=1)]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 0
    assert result.rejected_ambiguous_match == 1
    assert sink == []


def test_score_mismatch_rejected():
    mh = [_mh_row(1, "Team A", "Team B", 10, 2, 1)]
    src = [_source_row("Team A", "Team B", 10, 3, 3, home_shots=1)]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 0
    assert result.rejected_score_mismatch == 1
    assert sink == []


def test_dry_run_never_calls_update():
    mh = [_mh_row(1, "Team A", "Team B", 10, 2, 1)]
    src = [_source_row("Team A", "Team B", 10, 2, 1, home_shots=1, away_shots=2)]
    sink = []
    result = _service(mh, src, sink).run(dry_run=True)

    assert result.matched == 1
    assert result.written_ok == 1
    assert sink == [], "dry_run nu are voie sa scrie"


def test_columns_populated_counter_per_column():
    mh = [
        _mh_row(1, "Team A", "Team B", 10, 2, 1),
        _mh_row(2, "Team C", "Team D", 11, 0, 0, home_shots=5),
    ]
    src = [
        _source_row("Team A", "Team B", 10, 2, 1, home_shots=1, away_shots=2),
        _source_row("Team C", "Team D", 11, 0, 0, home_shots=99, away_shots=3),
    ]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.columns_populated["home_shots"] == 1  # doar meciul 1 (meciul 2 avea deja valoare)
    assert result.columns_populated["away_shots"] == 2  # ambele meciuri
