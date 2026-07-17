"""
Teste pentru BackfillOddsService — generic, fara nicio referinta la o liga
anume in logica testata (Premier League apare doar ca DATE de test, nu ca
ramura de cod). Fara retea, fara Supabase live.
"""
from datetime import datetime, timedelta, timezone

import services.odds_backfill_service as svc


def _iso_date(days_ago: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self._filters = {}

    def select(self, cols):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def gte(self, col, val):
        self._filters[("gte", col)] = val
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

    def execute(self):
        class Res:
            pass
        r = Res()
        start, end = getattr(self, "_range", (0, len(self._rows)))
        r.data = self._rows[start:end + 1]
        return r


class _FakeClient:
    def __init__(self, match_history_rows, rpc_sink, rpc_should_write=True):
        self._rows = match_history_rows
        self._rpc_sink = rpc_sink
        self._rpc_should_write = rpc_should_write

    def table(self, name):
        assert name == "match_history"
        return _FakeTable(self._rows)

    def rpc(self, name, params):
        assert name == "upsert_odds_snapshot"
        self._rpc_sink.append(params)
        should_write = self._rpc_should_write

        class Res:
            pass

        class Query:
            def execute(self):
                r = Res()
                r.data = should_write
                return r

        return Query()


class _FakeSb:
    def __init__(self, client):
        self._client = client

    def get_client(self):
        return self._client


def _match_history_row(id_, fixture_id, home, away, days_ago, hg, ag):
    return {
        "id": id_, "fixture_id": fixture_id, "home_team": home, "away_team": away,
        "kickoff_date": _iso_date(days_ago), "actual_home_goals": hg, "actual_away_goals": ag,
    }


def _source_row(home_raw, away_raw, days_ago, hg, ag, bookmaker="Bet365"):
    return {
        "match_date": _iso_date(days_ago), "home_team_raw": home_raw, "away_team_raw": away_raw,
        "home_goals": hg, "away_goals": ag, "bookmaker": bookmaker,
        "price_home": 1.9, "price_draw": 3.4, "price_away": 4.2,
        "source_hash": "deadbeef", "source_url": "https://example.test/matches.csv",
    }


def _service(match_history_rows, source_rows, rpc_sink):
    client = _FakeClient(match_history_rows, rpc_sink)
    sb = _FakeSb(client)

    def importer(division, season, min_date):
        return source_rows

    return svc.BackfillOddsService(
        provider="test-provider", division="X0", season=None,
        importer=importer, league="Test League", supabase_client=sb,
    )


def test_exact_match_writes_with_provenance():
    mh = [_match_history_row(1, "fd_1", "Team A", "Team B", 10, 2, 1)]
    src = [_source_row("Team A", "Team B", 10, 2, 1)]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 1
    assert result.written_ok == 1
    assert result.rejected_no_match == 0
    assert len(sink) == 1
    call = sink[0]
    assert call["p_fixture_id"] == "fd_1"
    assert call["p_provider"] == "test-provider"
    assert call["p_import_type"] == "historical_backfill"
    assert call["p_import_version"] == "OddsBackfill_v1"
    assert call["p_source_hash"] == "deadbeef"


def test_no_match_rejected_fail_closed():
    mh = [_match_history_row(1, "fd_1", "Team A", "Team B", 10, 2, 1)]
    src = [_source_row("Team C", "Team D", 10, 0, 0)]  # echipe complet diferite
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 0
    assert result.rejected_no_match == 1
    assert result.written_ok == 0
    assert sink == []
    assert "no_match" in result.rejection_details[0]


def test_ambiguous_match_rejected_not_guessed():
    """Doi candidati in match_history pentru aceeasi cheie -> sarit, nu ghicit."""
    mh = [
        _match_history_row(1, "fd_1", "Team A", "Team B", 10, 2, 1),
        _match_history_row(2, "fd_2", "Team A", "Team B", 10, 2, 1),
    ]
    src = [_source_row("Team A", "Team B", 10, 2, 1)]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 0
    assert result.rejected_ambiguous_match == 1
    assert sink == []


def test_score_mismatch_rejected():
    """Nume+data se potrivesc dar scorul difera -> nepotrivire, nu se forteaza."""
    mh = [_match_history_row(1, "fd_1", "Team A", "Team B", 10, 2, 1)]
    src = [_source_row("Team A", "Team B", 10, 3, 3)]  # scor diferit
    sink = []
    result = _service(mh, src, sink).run()

    assert result.matched == 0
    assert result.rejected_score_mismatch == 1
    assert sink == []


def test_dry_run_never_calls_rpc():
    mh = [_match_history_row(1, "fd_1", "Team A", "Team B", 10, 2, 1)]
    src = [_source_row("Team A", "Team B", 10, 2, 1)]
    sink = []
    result = _service(mh, src, sink).run(dry_run=True)

    assert result.matched == 1
    assert result.written_ok == 1  # numarat, dar fara scriere reala
    assert sink == [], "dry_run nu are voie sa apeleze RPC-ul de scriere"


def test_match_rate_percentage_computed_correctly():
    mh = [_match_history_row(1, "fd_1", "Team A", "Team B", 10, 2, 1)]
    src = [
        _source_row("Team A", "Team B", 10, 2, 1),   # potrivire
        _source_row("Team X", "Team Y", 10, 0, 0),   # fara potrivire
    ]
    sink = []
    result = _service(mh, src, sink).run(dry_run=True)

    assert result.source_rows_found == 2
    assert result.matched == 1
    assert result.match_rate_pct == 50.0


def test_multiple_bookmakers_same_match_both_written():
    mh = [_match_history_row(1, "fd_1", "Team A", "Team B", 10, 2, 1)]
    src = [
        _source_row("Team A", "Team B", 10, 2, 1, bookmaker="Bet365"),
        _source_row("Team A", "Team B", 10, 2, 1, bookmaker="Market_Max"),
    ]
    sink = []
    result = _service(mh, src, sink).run()

    assert result.source_matches_found == 1   # un singur meci unic
    assert result.source_rows_found == 2      # dar 2 randuri (meci,bookmaker)
    assert result.matched == 2
    assert result.written_ok == 2
    assert {c["p_bookmaker"] for c in sink} == {"Bet365", "Market_Max"}
