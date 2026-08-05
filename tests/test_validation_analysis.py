"""
Teste pentru Validation Analysis (ADR-052 §2.4) — validation_analysis.py:
metrici pure (_engine_metrics/_logloss/_correct), construcția raportului
(compute_period_report, JOIN cu match_history), aplatizarea pentru
persistare (_flatten_report/save_report), și orchestrarea (run_report_cycle,
automation_runs). Fără rețea — Supabase mockuit prin monkeypatch.

Invarianți verificați:
  1. Flag oprit (implicit) => run_report_cycle nu creează niciun
     automation_run, nu calculează nimic.
  2. Fiecare motor raportat pe PROPRIUL subset disponibil — n=0 => toate
     metricile None (Regula #8, nu se aproximează).
  3. compute_period_report exclude meciurile fără actual_result cunoscut.
  4. run_report_cycle: compute eșuat => fail_run; 0 meciuri => skip_run;
     succes => complete_run + save_report apelat.
  5. Metodologia (Brier/logloss/accuracy) identică cu cea deja folosită de
     shadow_testing.evaluate_experiment() — aceleași formule.
"""
from __future__ import annotations

from datetime import date

import pytest

import validation_analysis as va


# ── _engine_metrics ──────────────────────────────────────────────────────────

def test_engine_metrics_empty_rows_returns_none_metrics():
    result = va._engine_metrics([], "oracle")
    assert result == {"n": 0, "brier": None, "logloss": None, "accuracy": None}


def test_engine_metrics_oracle_perfect_prediction():
    rows = [{"oracle_prob_home": 1.0, "oracle_prob_draw": 0.0, "oracle_prob_away": 0.0, "actual_result": "H"}]
    result = va._engine_metrics(rows, "oracle")
    assert result["n"] == 1
    assert result["brier"] == pytest.approx(0.0)
    assert result["logloss"] == pytest.approx(0.0, abs=1e-9)
    assert result["accuracy"] == 1.0


def test_engine_metrics_skips_rows_where_ml_unavailable():
    rows = [
        {"ml_available": True, "ml_prob_home": 0.6, "ml_prob_draw": 0.2, "ml_prob_away": 0.2, "actual_result": "H"},
        {"ml_available": False, "ml_prob_home": None, "ml_prob_draw": None, "ml_prob_away": None, "actual_result": "H"},
    ]
    result = va._engine_metrics(rows, "ml")
    assert result["n"] == 1


def test_engine_metrics_oracle_never_gated_by_available_flag():
    """Oracle nu are coloană *_available (mereu prezent) — _engine_metrics
    nu trebuie să o ceară pentru motorul "oracle"."""
    rows = [{"oracle_prob_home": 0.5, "oracle_prob_draw": 0.3, "oracle_prob_away": 0.2, "actual_result": "D"}]
    result = va._engine_metrics(rows, "oracle")
    assert result["n"] == 1


# ── compute_period_report ────────────────────────────────────────────────────

class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **kw):
        return self

    def gte(self, col, value):
        self._rows = [r for r in self._rows if r.get(col, "") >= value]
        return self

    def lte(self, col, value):
        self._rows = [r for r in self._rows if r.get(col, "") <= value]
        return self

    def in_(self, col, values):
        self._rows = [r for r in self._rows if r.get(col) in values]
        return self

    def execute(self):
        return type("Result", (), {"data": self._rows})()


class _FakeClient:
    def __init__(self, snapshots, match_history):
        self._snapshots = snapshots
        self._match_history = match_history

    def table(self, name):
        if name == "engine_comparison_snapshots":
            return _FakeQuery(self._snapshots)
        if name == "match_history":
            return _FakeQuery(self._match_history)
        raise AssertionError(f"tabela neasteptata: {name}")


def _snapshot(fixture_id, kickoff_date="2026-08-01", ml_available=False, blend_available=False):
    return {
        "fixture_id": fixture_id, "kickoff_date": kickoff_date,
        "oracle_prob_home": 0.5, "oracle_prob_draw": 0.3, "oracle_prob_away": 0.2,
        "ml_available": ml_available,
        "ml_prob_home": 0.6 if ml_available else None,
        "ml_prob_draw": 0.2 if ml_available else None,
        "ml_prob_away": 0.2 if ml_available else None,
        "blend_available": blend_available,
        "blend_prob_home": 0.55 if blend_available else None,
        "blend_prob_draw": 0.25 if blend_available else None,
        "blend_prob_away": 0.2 if blend_available else None,
    }


def test_compute_period_report_returns_none_when_supabase_unavailable(monkeypatch):
    monkeypatch.setattr(va.sb, "get_client", lambda: None)
    assert va.compute_period_report("daily", date(2026, 8, 1), date(2026, 8, 1)) is None


def test_compute_period_report_empty_window_returns_zero_report(monkeypatch):
    monkeypatch.setattr(va.sb, "get_client", lambda: _FakeClient([], []))
    report = va.compute_period_report("daily", date(2026, 8, 1), date(2026, 8, 1))
    assert report["n_matches_total"] == 0
    assert report["oracle"]["n"] == 0


def test_compute_period_report_excludes_matches_without_known_result(monkeypatch):
    snapshots = [_snapshot("fx-1"), _snapshot("fx-2")]
    match_history = [{"fixture_id": "fx-1", "actual_result": "H"}]  # fx-2 fara rezultat inca
    monkeypatch.setattr(va.sb, "get_client", lambda: _FakeClient(snapshots, match_history))

    report = va.compute_period_report("daily", date(2026, 8, 1), date(2026, 8, 1))
    assert report["n_matches_total"] == 1
    assert report["oracle"]["n"] == 1


def test_compute_period_report_per_engine_independent_availability(monkeypatch):
    snapshots = [
        _snapshot("fx-1", ml_available=True, blend_available=True),
        _snapshot("fx-2", ml_available=False, blend_available=False),
    ]
    match_history = [
        {"fixture_id": "fx-1", "actual_result": "H"},
        {"fixture_id": "fx-2", "actual_result": "D"},
    ]
    monkeypatch.setattr(va.sb, "get_client", lambda: _FakeClient(snapshots, match_history))

    report = va.compute_period_report("daily", date(2026, 8, 1), date(2026, 8, 1))
    assert report["n_matches_total"] == 2
    assert report["oracle"]["n"] == 2   # oracle mereu prezent
    assert report["ml"]["n"] == 1       # doar fx-1
    assert report["blend"]["n"] == 1    # doar fx-1


def test_compute_period_report_returns_none_on_query_exception(monkeypatch):
    class _BoomClient:
        def table(self, name):
            raise RuntimeError("eroare simulata")

    monkeypatch.setattr(va.sb, "get_client", lambda: _BoomClient())
    assert va.compute_period_report("daily", date(2026, 8, 1), date(2026, 8, 1)) is None


# ── _flatten_report / save_report ────────────────────────────────────────────

def test_flatten_report_produces_expected_columns():
    report = va._empty_report("weekly", date(2026, 8, 1), date(2026, 8, 7))
    row = va._flatten_report(report)
    assert row["cadence"] == "weekly"
    assert row["oracle_n"] == 0
    assert row["ml_brier"] is None
    assert row["blend_accuracy"] is None


def test_save_report_calls_supabase_writer(monkeypatch):
    captured = {}
    monkeypatch.setattr(va.sb, "save_validation_analysis_report", lambda row: captured.update(row) or True)
    report = va._empty_report("daily", date(2026, 8, 1), date(2026, 8, 1))
    assert va.save_report(report) is True
    assert captured["cadence"] == "daily"


def test_save_report_swallows_exception(monkeypatch):
    def _boom(row):
        raise RuntimeError("eroare simulata")
    monkeypatch.setattr(va.sb, "save_validation_analysis_report", _boom)
    report = va._empty_report("daily", date(2026, 8, 1), date(2026, 8, 1))
    assert va.save_report(report) is False


# ── run_report_cycle — orchestrare ───────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_ar(monkeypatch):
    calls = []

    class _Recorder:
        def write_run(self, producer, process_type, tier, target_key=None):
            calls.append(("write_run", producer, process_type, tier))
            return len(calls)

        def start_run(self, run_id):
            calls.append(("start_run", run_id))
            return True

        def complete_run(self, run_id, summary=None):
            calls.append(("complete_run", run_id, summary))
            return True

        def skip_run(self, run_id, skip_reason):
            calls.append(("skip_run", run_id, skip_reason))
            return True

        def fail_run(self, run_id, error_detail):
            calls.append(("fail_run", run_id, error_detail))
            return True

    monkeypatch.setattr(va, "ar", _Recorder())
    yield calls


def test_run_report_cycle_disabled_by_default(monkeypatch, clean_ar):
    monkeypatch.setattr(va.sb, "load_config", lambda default: dict(default))
    result = va.run_report_cycle("daily")
    assert result == {"enabled": False}
    assert clean_ar == []


def _enable(monkeypatch):
    monkeypatch.setattr(va.sb, "load_config", lambda default: {"validation_analysis_enabled": True})


def test_run_report_cycle_invalid_cadence(monkeypatch, clean_ar):
    _enable(monkeypatch)
    result = va.run_report_cycle("monthly")
    assert result["status"] == "invalid_cadence"
    assert clean_ar == []  # nicio rulare creata pt o cadenta invalida


def test_run_report_cycle_compute_failed(monkeypatch, clean_ar):
    _enable(monkeypatch)
    monkeypatch.setattr(va, "compute_period_report", lambda cadence, start, end: None)
    result = va.run_report_cycle("daily")
    assert result["status"] == "compute_failed"
    assert clean_ar[-1][0] == "fail_run"


def test_run_report_cycle_no_data_skips(monkeypatch, clean_ar):
    _enable(monkeypatch)
    empty = va._empty_report("daily", date(2026, 8, 1), date(2026, 8, 1))
    monkeypatch.setattr(va, "compute_period_report", lambda cadence, start, end: empty)
    result = va.run_report_cycle("daily")
    assert result["status"] == "no_data"
    assert clean_ar[-1][0] == "skip_run"


def test_run_report_cycle_success_saves_and_completes(monkeypatch, clean_ar):
    _enable(monkeypatch)
    report = {
        "cadence": "daily", "period_start": "2026-08-01", "period_end": "2026-08-01",
        "n_matches_total": 3,
        "oracle": {"n": 3, "brier": 0.2, "logloss": 0.5, "accuracy": 0.66},
        "ml": {"n": 1, "brier": 0.1, "logloss": 0.3, "accuracy": 1.0},
        "blend": {"n": 0, "brier": None, "logloss": None, "accuracy": None},
    }
    monkeypatch.setattr(va, "compute_period_report", lambda cadence, start, end: report)
    saved_rows = []
    monkeypatch.setattr(va, "save_report", lambda r: saved_rows.append(r) or True)

    result = va.run_report_cycle("daily")

    assert result["status"] == "computed"
    assert result["saved"] is True
    assert saved_rows == [report]
    assert clean_ar[-1][0] == "complete_run"


def test_run_report_cycle_window_excludes_current_day():
    """Fereastra e mereu STRICT inainte de ziua curenta (as_of) - nu include
    ziua in curs, care poate avea inca meciuri fara rezultat final."""
    window = va._window_for_cadence("daily", date(2026, 8, 5))
    assert window == (date(2026, 8, 4), date(2026, 8, 4))

    window_weekly = va._window_for_cadence("weekly", date(2026, 8, 5))
    assert window_weekly == (date(2026, 7, 29), date(2026, 8, 4))


# ── is_enabled ────────────────────────────────────────────────────────────────

def test_validation_analysis_disabled_by_default(monkeypatch):
    monkeypatch.setattr(va.sb, "load_config", lambda default: dict(default))
    assert va.is_enabled() is False
