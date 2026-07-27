"""Teste pentru database.queries.upsert_equivalence_evaluation() (ADR-040, G2)
— owner unic de scriere pentru equivalence_evaluations, wrapper subțire
peste .table().upsert(), fără logică de clasificare."""
from __future__ import annotations

import database.queries as q


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeUpsertQuery:
    def __init__(self, calls):
        self._calls = calls

    def upsert(self, payload, on_conflict=None, ignore_duplicates=False):
        self._calls.append(("upsert", payload, on_conflict, ignore_duplicates))
        return self

    def execute(self):
        return _FakeResult([])


class _FakeClient:
    def __init__(self):
        self.calls: list = []

    def table(self, name):
        self.calls.append(("table", name))
        if name != "equivalence_evaluations":
            raise AssertionError(f"tabelă neașteptată: {name}")
        return _FakeUpsertQuery(self.calls)


def _minimal_kwargs(**overrides) -> dict:
    base = dict(
        gate_key="R-Sync-7b", entity="scheduled_fixtures",
        window_from="2026-08-01", window_to="2026-08-08",
        live_count=30, scheduled_count=30, matched_count=30,
        missing_scheduled_count=0, missing_live_count=0,
        field_difference_count=0, provider_id_difference_count=0,
        equivalence_state="green",
    )
    base.update(overrides)
    return base


def test_upsert_writes_via_on_conflict_ignore_duplicates(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: client)

    ok = q.upsert_equivalence_evaluation(**_minimal_kwargs())

    assert ok is True
    upsert_call = [c for c in client.calls if c[0] == "upsert"]
    assert len(upsert_call) == 1
    _, payload, on_conflict, ignore_duplicates = upsert_call[0]
    assert on_conflict == "gate_key,entity,window_to,matched_count"
    assert ignore_duplicates is True
    assert payload["gate_key"] == "R-Sync-7b"
    assert payload["entity"] == "scheduled_fixtures"
    assert payload["equivalence_state"] == "green"


def test_upsert_defaults_jsonb_fields_to_empty_not_none(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: client)

    q.upsert_equivalence_evaluation(**_minimal_kwargs())

    payload = [c for c in client.calls if c[0] == "upsert"][0][1]
    assert payload["provider_breakdown"] == {}
    assert payload["root_cause_summary"] == {}
    assert payload["sample_missing_scheduled"] == []
    assert payload["sample_missing_live"] == []
    assert payload["sample_field_differences"] == []
    assert payload["sample_provider_id_diffs"] == []
    assert payload["run_id"] is None


def test_upsert_passes_through_provided_jsonb_and_run_id(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(q, "get_client", lambda: client)

    q.upsert_equivalence_evaluation(**_minimal_kwargs(
        provider_breakdown={"freelf": {"matched": 30}},
        root_cause_summary={"UNKNOWN": 1},
        run_id=7,
    ))

    payload = [c for c in client.calls if c[0] == "upsert"][0][1]
    assert payload["provider_breakdown"] == {"freelf": {"matched": 30}}
    assert payload["root_cause_summary"] == {"UNKNOWN": 1}
    assert payload["run_id"] == 7


def test_upsert_returns_false_when_client_unavailable(monkeypatch):
    monkeypatch.setattr(q, "get_client", lambda: None)
    ok = q.upsert_equivalence_evaluation(**_minimal_kwargs())
    assert ok is False


def test_upsert_returns_false_on_exception(monkeypatch):
    class _BoomClient:
        def table(self, name):
            raise RuntimeError("boom")

    monkeypatch.setattr(q, "get_client", lambda: _BoomClient())
    ok = q.upsert_equivalence_evaluation(**_minimal_kwargs())
    assert ok is False
