"""Teste pentru equivalence_governance.py (ADR-040, G2) — generic,
entity-agnostic. Folosește direct ScheduledFixturesShadowReport ca obiect
de test (duck typing deliberat — orice raport cu aceleași câmpuri e valid,
nu doar acela)."""
from __future__ import annotations

from dataclasses import dataclass, field

import equivalence_governance as mod


@dataclass
class _FakeReport:
    live_count: int
    scheduled_count: int
    matched: int
    missing_scheduled_count: int = 0
    missing_live_count: int = 0
    field_difference_count: int = 0
    provider_id_difference_count: int = 0
    accepted_exception_count: int = 0
    missing_scheduled: list = field(default_factory=list)
    missing_live: list = field(default_factory=list)
    field_differences: list = field(default_factory=list)
    provider_id_differences: list = field(default_factory=list)
    provider_breakdown: dict = field(default_factory=dict)
    root_cause_summary: dict = field(default_factory=dict)


def _report(**overrides) -> _FakeReport:
    base = dict(live_count=30, scheduled_count=30, matched=30)
    base.update(overrides)
    return _FakeReport(**base)


def test_classify_insufficient_data_below_min_live():
    score, state = mod.classify_evaluation(_report(live_count=29, scheduled_count=29, matched=29))
    assert score is None
    assert state == "insufficient_data"


def test_classify_broken_when_scheduled_empty_but_live_nonempty():
    score, state = mod.classify_evaluation(_report(scheduled_count=0, matched=0))
    assert score is None
    assert state == "broken"


def test_classify_green_when_perfectly_equivalent():
    score, state = mod.classify_evaluation(_report())
    assert score == 1.0
    assert state == "green"


def test_classify_yellow_when_only_accepted_exceptions():
    score, state = mod.classify_evaluation(_report(field_difference_count=1, accepted_exception_count=1))
    assert score == 1.0
    assert state == "yellow"


def test_classify_red_when_unaccepted_field_difference():
    score, state = mod.classify_evaluation(_report(field_difference_count=1, accepted_exception_count=0))
    assert score is not None and score < 1.0
    assert state == "red"


def test_classify_red_dominates_min_not_average():
    """Un singur defect catastrofal (id_purity=0) nu se ascunde -- MIN, nu medie."""
    score, state = mod.classify_evaluation(_report(provider_id_difference_count=30))
    assert score == 0.0
    assert state == "red"


def test_custom_min_live_threshold_respected():
    score, state = mod.classify_evaluation(_report(live_count=10, scheduled_count=10, matched=10), min_live_for_evaluation=5)
    assert state == "green"


def test_persist_always_writes_even_for_insufficient_data(monkeypatch):
    calls = []

    def _fake_upsert(**kwargs):
        calls.append(kwargs)
        return True

    import database.queries as queries
    monkeypatch.setattr(queries, "upsert_equivalence_evaluation", _fake_upsert)

    ok = mod.persist_equivalence_evaluation(
        gate_key="R-Sync-7b", entity="scheduled_fixtures",
        report=_report(live_count=5, scheduled_count=5, matched=5),
        window_from="2026-08-01", window_to="2026-08-08",
    )
    assert ok is True
    assert len(calls) == 1
    assert calls[0]["equivalence_state"] == "insufficient_data"
    assert calls[0]["equivalence_score"] is None


def test_persist_passes_all_report_fields_through(monkeypatch):
    calls = []

    def _fake_upsert(**kwargs):
        calls.append(kwargs)
        return True

    import database.queries as queries
    monkeypatch.setattr(queries, "upsert_equivalence_evaluation", _fake_upsert)

    report = _report(provider_breakdown={"freelf": {"matched": 30}}, root_cause_summary={"UNKNOWN": 2})
    mod.persist_equivalence_evaluation(
        gate_key="R-Sync-7b", entity="scheduled_fixtures", report=report,
        window_from="2026-08-01", window_to="2026-08-08", run_id=42,
    )
    call = calls[0]
    assert call["gate_key"] == "R-Sync-7b"
    assert call["entity"] == "scheduled_fixtures"
    assert call["run_id"] == 42
    assert call["provider_breakdown"] == {"freelf": {"matched": 30}}
    assert call["root_cause_summary"] == {"UNKNOWN": 2}
    assert call["equivalence_state"] == "green"


def test_persist_state_override_forces_broken_without_classification(monkeypatch):
    calls = []

    def _fake_upsert(**kwargs):
        calls.append(kwargs)
        return True

    import database.queries as queries
    monkeypatch.setattr(queries, "upsert_equivalence_evaluation", _fake_upsert)

    mod.persist_equivalence_evaluation(
        gate_key="R-Sync-7b", entity="scheduled_fixtures",
        report=_report(),  # ar clasifica GREEN dacă nu era override-ul
        window_from="2026-08-01", window_to="2026-08-08",
        state_override="broken",
    )
    assert calls[0]["equivalence_state"] == "broken"
    assert calls[0]["equivalence_score"] is None
