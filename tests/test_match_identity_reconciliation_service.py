"""
Teste pentru MatchIdentityReconciliationService (ADR-025, ID-025-01/02).
Fara retea, fara Supabase live — `process_group()` e pura (fara I/O), testata
direct cu dict-uri; `run()` foloseste un client fals in memorie.
"""
import pytest

import services.match_identity_reconciliation_service as svc
from services.match_identity_reconciliation_service import (
    MatchIdentityReconciliationService, process_group, resolve_source,
)


def _row(id, fixture_id, home="Team A", away="Team B", date="2026-01-01",
         result="H", hg=1, ag=0, **extra):
    base = {
        "id": id, "fixture_id": fixture_id, "home_team": home, "away_team": away,
        "kickoff_date": date, "actual_result": result,
        "actual_home_goals": hg, "actual_away_goals": ag,
    }
    base.update(extra)
    return base


# ── resolve_source ──────────────────────────────────────────────────────────

def test_resolve_source_known_prefixes():
    assert resolve_source("fd_12345") == "football_data"
    assert resolve_source("espn_999") == "espn"
    assert resolve_source("odds_abcdef") == "odds_api"
    assert resolve_source("kaggle_deadbeef") == "kaggle_historical"


def test_resolve_source_unknown_prefix_is_none():
    assert resolve_source("opta_123") is None
    assert resolve_source(None) is None
    assert resolve_source("") is None


# ── process_group: HARD CONFLICT ────────────────────────────────────────────

def test_hard_conflict_on_differing_result_excludes_group_no_side_effects():
    rows = [_row(1, "fd_1", result="H"), _row(2, "kaggle_1", result="A")]
    decision = process_group(rows)
    assert decision.excluded_reason == "hard_conflict"
    assert decision.canonical_id is None
    assert decision.merge_updates == {}
    assert decision.noncanonical == []


def test_hard_conflict_on_differing_goals_excludes_group():
    rows = [_row(1, "fd_1", hg=2), _row(2, "kaggle_1", hg=3)]
    decision = process_group(rows)
    assert decision.excluded_reason == "hard_conflict"


def test_null_hard_conflict_column_does_not_trigger_conflict():
    # World Cup 2026-style: ambele randuri au actual_result NULL (dormant).
    rows = [_row(1, "espn_1", result=None, hg=None, ag=None),
            _row(2, "odds_1", result=None, hg=None, ag=None)]
    decision = process_group(rows)
    assert decision.excluded_reason is None


# ── process_group: unknown source ───────────────────────────────────────────

def test_unknown_source_excludes_whole_group():
    rows = [_row(1, "fd_1"), _row(2, "opta_1")]
    decision = process_group(rows)
    assert decision.excluded_reason == "unknown_source"


# ── process_group: canonical selection ──────────────────────────────────────

def test_canonical_is_row_with_lowest_source_rank():
    rows = [_row(1, "kaggle_1"), _row(2, "fd_1")]
    decision = process_group(rows)
    assert decision.canonical_id == 2
    assert decision.canonical_source == "football_data"
    assert [n["id"] for n in decision.noncanonical] == [1]


def test_tiebreak_uses_lowest_id_at_equal_rank():
    # Rang egal (teoretic) — decis prin id minim, NU rangul de sursa.
    rows = [_row(20, "fd_b"), _row(10, "fd_a")]
    decision = process_group(rows)
    assert decision.canonical_id == 10


# ── process_group: merge non-destructiv (Pasii 1-4, ID-025-01) ─────────────

def test_case1_canonical_value_never_overwritten():
    rows = [
        _row(1, "fd_1", home_shots=10),
        _row(2, "kaggle_1", home_shots=99),
    ]
    decision = process_group(rows)
    assert "home_shots" not in decision.merge_updates


def test_case2_single_candidate_fills_null_canonical():
    rows = [
        _row(1, "fd_1", home_shots=None),
        _row(2, "kaggle_1", home_shots=7),
    ]
    decision = process_group(rows)
    assert decision.merge_updates["home_shots"] == 7


def test_case3_soft_conflict_resolved_by_lowest_rank_among_candidates():
    rows = [
        _row(1, "espn_1", home_shots=None),   # canonical (rank 2)
        _row(2, "odds_1", home_shots=11),     # rank 3
        _row(3, "kaggle_1", home_shots=9),    # rank 4
    ]
    decision = process_group(rows)
    assert decision.merge_updates["home_shots"] == 11  # odds_api (rank 3) beats kaggle (rank 4)


def test_case4_no_row_has_value_stays_absent_from_updates():
    rows = [
        _row(1, "fd_1", home_shots=None),
        _row(2, "kaggle_1", home_shots=None),
    ]
    decision = process_group(rows)
    assert "home_shots" not in decision.merge_updates


def test_superseded_reason_format():
    rows = [_row(1, "kaggle_04f4107f71d47331"), _row(2, "fd_497780")]
    decision = process_group(rows)
    reason = decision.noncanonical[0]["reason"]
    assert "canonical=fd_497780 (rank=1)" in reason
    assert "superseded=kaggle_04f4107f71d47331 (rank=4)" in reason


def test_idempotent_on_two_row_group_deterministic_regardless_of_input_order():
    a = [_row(1, "fd_1", home_shots=None), _row(2, "kaggle_1", home_shots=5)]
    b = list(reversed(a))
    assert process_group(a).canonical_id == process_group(b).canonical_id
    assert process_group(a).merge_updates == process_group(b).merge_updates


# ── run(): EXECUTE mode guard ───────────────────────────────────────────────

def test_execute_mode_not_authorized_raises_before_any_io():
    service = MatchIdentityReconciliationService(supabase_client=object())
    with pytest.raises(NotImplementedError):
        service.run(dry_run=False)


# ── run(): DRY-RUN orchestration with fake client ───────────────────────────

class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self._filters = []

    def select(self, cols):
        return self

    def is_(self, col, val):
        self._filters.append(("is_null", col))
        return self

    def in_(self, col, values):
        self._filters.append(("in", col, set(values)))
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        rows = self._rows
        for f in self._filters:
            if f[0] == "is_null":
                rows = [r for r in rows if r.get(f[1]) is None]
            elif f[0] == "in":
                rows = [r for r in rows if r.get(f[1]) in f[2]]
        if hasattr(self, "_range"):
            start, end = self._range
            rows = rows[start:end + 1]

        class Res:
            pass
        res = Res()
        res.data = rows
        return res


class _FakeClient:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "match_history"
        return _FakeTable(self._rows)


class _FakeSb:
    def __init__(self, rows):
        self._client = _FakeClient(rows)

    def get_client(self):
        return self._client


def test_run_dry_run_discovers_and_reports_duplicate_groups():
    rows = [
        _row(1, "fd_1", home="Alpha", away="Beta", date="2026-02-01", home_shots=None),
        _row(2, "kaggle_1", home="Alpha", away="Beta", date="2026-02-01", home_shots=8),
        _row(3, "fd_2", home="Gamma", away="Delta", date="2026-02-02"),  # unic, fara duplicat
    ]
    service = MatchIdentityReconciliationService(supabase_client=_FakeSb(rows))
    report = service.run(dry_run=True)

    assert report.total_groups == 1
    assert report.reconciled_groups == 1
    assert report.excluded_hard_conflict_count == 0
    assert report.excluded_unknown_source_count == 0
    assert report.columns_populated.get("home_shots") == 1
    assert report.canonical_rows_with_any_fill == 1
    assert report.total_rows_affected == 2  # 1 grup marcat + 1 canonic completat


def test_run_dry_run_never_calls_update_or_rpc():
    rows = [
        _row(1, "fd_1", home="Alpha", away="Beta", date="2026-02-01"),
        _row(2, "kaggle_1", home="Alpha", away="Beta", date="2026-02-01"),
    ]

    class _NoWriteTable(_FakeTable):
        def update(self, *a, **kw):
            raise AssertionError("DRY-RUN nu trebuie sa apeleze niciodata update()")

        def upsert(self, *a, **kw):
            raise AssertionError("DRY-RUN nu trebuie sa apeleze niciodata upsert()")

    class _NoWriteClient(_FakeClient):
        def table(self, name):
            return _NoWriteTable(self._rows)

        def rpc(self, *a, **kw):
            raise AssertionError("DRY-RUN nu trebuie sa apeleze niciodata rpc()")

    class _NoWriteSb:
        def get_client(self):
            return _NoWriteClient(rows)

    service = MatchIdentityReconciliationService(supabase_client=_NoWriteSb())
    report = service.run(dry_run=True)
    assert report.total_groups == 1
