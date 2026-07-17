"""
Teste pentru functiile Supabase noi din ADR-033 (consensus_capture_samples,
consensus_validation_verdicts) — supabase_client.py. Fara retea, client
Supabase fabricat.
"""
import supabase_client as sb


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeUpsertTable:
    """Simuleaza .upsert(payload, on_conflict=..., ignore_duplicates=True)
    -> ON CONFLICT DO NOTHING, identic cu _FakeEvalTable din
    tests/test_challenger_evaluation.py."""
    def __init__(self, rows: dict, key_fields: tuple):
        self._rows = rows
        self._key_fields = key_fields
        self._payload = None
        self._ignore_duplicates = None

    def upsert(self, payload, on_conflict="", ignore_duplicates=False):
        self._payload = payload
        self._ignore_duplicates = ignore_duplicates
        return self

    def execute(self):
        key = tuple(self._payload[f] for f in self._key_fields)
        if key in self._rows and self._ignore_duplicates:
            return _Result([self._rows[key]])
        self._rows[key] = dict(self._payload)
        return _Result([self._rows[key]])


class _FakeClient:
    def __init__(self, table_name: str, key_fields: tuple):
        self.rows: dict = {}
        self._table_name = table_name
        self._key_fields = key_fields

    def table(self, name):
        assert name == self._table_name
        return _FakeUpsertTable(self.rows, self._key_fields)


def test_save_consensus_capture_sample_writes_row(monkeypatch):
    fake_client = _FakeClient("consensus_capture_samples", ("fixture_id",))
    monkeypatch.setattr(sb, "get_client", lambda: fake_client)

    ok = sb.save_consensus_capture_sample(
        fixture_id="fx-1", league="Premier League", home_team="A", away_team="B",
        kickoff_date="2026-01-01",
        raw_predictions=[{"family": "rule_based", "engine": "oracle_protocol",
                           "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}],
    )

    assert ok is True
    assert ("fx-1",) in fake_client.rows


def test_save_consensus_capture_sample_second_write_is_noop(monkeypatch):
    """UNIQUE(fixture_id) + ignore_duplicates=True -> a doua captura pentru
    ACELASI fixture (rerulare Streamlit) nu schimba randul existent."""
    fake_client = _FakeClient("consensus_capture_samples", ("fixture_id",))
    monkeypatch.setattr(sb, "get_client", lambda: fake_client)

    sb.save_consensus_capture_sample(
        fixture_id="fx-1", league="Premier League", home_team="A", away_team="B",
        kickoff_date="2026-01-01",
        raw_predictions=[{"family": "rule_based", "engine": "oracle_protocol",
                           "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}],
    )
    sb.save_consensus_capture_sample(
        fixture_id="fx-1", league="Premier League", home_team="A", away_team="B",
        kickoff_date="2026-01-01",
        raw_predictions=[{"family": "rule_based", "engine": "oracle_protocol",
                           "prob_home": 0.99, "prob_draw": 0.005, "prob_away": 0.005}],
    )

    assert len(fake_client.rows) == 1
    stored = fake_client.rows[("fx-1",)]
    assert stored["raw_predictions"][0]["prob_home"] == 0.5, \
        "a doua captura nu trebuie sa suprascrie randul deja existent"


def test_save_consensus_capture_sample_graceful_without_supabase():
    assert sb.save_consensus_capture_sample(
        fixture_id="fx-1", league="x", home_team="A", away_team="B",
        kickoff_date="2026-01-01", raw_predictions=[],
    ) is False


def test_save_consensus_validation_verdict_second_write_same_window_is_noop(monkeypatch):
    fake_client = _FakeClient("consensus_validation_verdicts", ("metric_name", "n_samples_evaluated"))
    monkeypatch.setattr(sb, "get_client", lambda: fake_client)

    sb.save_consensus_validation_verdict(
        metric_name="agreement_score", is_primary_metric=True, n_samples_evaluated=200,
        evaluation_window_start="2026-01-01", evaluation_window_end="2026-06-01",
        verdict="surface_worthy", statistical_method="bootstrap_independent_groups", metrics={},
    )
    sb.save_consensus_validation_verdict(
        metric_name="agreement_score", is_primary_metric=True, n_samples_evaluated=200,
        evaluation_window_start="2026-01-01", evaluation_window_end="2026-06-01",
        verdict="rejected", statistical_method="bootstrap_independent_groups", metrics={},
    )

    key = ("agreement_score", 200)
    assert len(fake_client.rows) == 1
    assert fake_client.rows[key]["verdict"] == "surface_worthy", \
        "verdictul original nu trebuie schimbat de o rerulare cu aceeasi fereastra"


def test_save_consensus_validation_verdict_new_window_is_new_row(monkeypatch):
    fake_client = _FakeClient("consensus_validation_verdicts", ("metric_name", "n_samples_evaluated"))
    monkeypatch.setattr(sb, "get_client", lambda: fake_client)

    sb.save_consensus_validation_verdict(
        metric_name="agreement_score", is_primary_metric=True, n_samples_evaluated=200,
        evaluation_window_start=None, evaluation_window_end=None,
        verdict="insufficient_data", statistical_method="bootstrap_independent_groups", metrics={},
    )
    sb.save_consensus_validation_verdict(
        metric_name="agreement_score", is_primary_metric=True, n_samples_evaluated=400,
        evaluation_window_start=None, evaluation_window_end=None,
        verdict="surface_worthy", statistical_method="bootstrap_independent_groups", metrics={},
    )

    assert len(fake_client.rows) == 2


class _FakeJoinQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **kw):
        return self

    def order(self, *a, **kw):
        return self

    def limit(self, *a, **kw):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        return self

    def in_(self, col, values):
        self._rows = [r for r in self._rows if r.get(col) in values]
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeJoinClient:
    def __init__(self, capture_rows, match_history_rows):
        self._capture_rows = capture_rows
        self._match_history_rows = match_history_rows

    def table(self, name):
        if name == "consensus_capture_samples":
            return _FakeJoinQuery(self._capture_rows)
        if name == "match_history":
            return _FakeJoinQuery(self._match_history_rows)
        raise AssertionError(f"tabela neasteptata: {name}")


def test_get_unevaluated_consensus_samples_joins_on_resolved_matches(monkeypatch):
    captures = [
        {"fixture_id": "fx-1", "raw_predictions": [], "kickoff_date": "2026-01-01"},
        {"fixture_id": "fx-2", "raw_predictions": [], "kickoff_date": "2026-01-02"},
    ]
    match_history = [
        {"fixture_id": "fx-1", "actual_result": "H"},
        # fx-2 nu are inca actual_result -> exclus
    ]
    monkeypatch.setattr(sb, "get_client", lambda: _FakeJoinClient(captures, match_history))

    result = sb.get_unevaluated_consensus_samples()

    assert len(result) == 1
    assert result[0]["fixture_id"] == "fx-1"
    assert result[0]["actual_result"] == "H"


def test_get_unevaluated_consensus_samples_empty_without_captures(monkeypatch):
    monkeypatch.setattr(sb, "get_client", lambda: _FakeJoinClient([], []))
    assert sb.get_unevaluated_consensus_samples() == []
