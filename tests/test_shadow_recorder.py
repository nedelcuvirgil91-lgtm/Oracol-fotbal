"""Teste pentru shadow_recorder.py (ADR-034, PR5) — fără rețea, Supabase
mock-uit prin un client fake (niciun apel real)."""
from __future__ import annotations

import uuid

from provider_selector import (
    ALGORITHM_VERSION, ProviderRecommendation, ProviderScore, RecommendationReason,
    ScoreComponents,
)
from provider_capabilities import DataType
import shadow_recorder


class _FakeInsertResult:
    def execute(self):
        return None


class _FakeTable:
    def __init__(self, sink: list[dict]):
        self._sink = sink
        self._rows = []

    def insert(self, row: dict):
        self._sink.append(row)
        return _FakeInsertResult()

    def select(self, *_a, **_kw):
        return self

    def eq(self, *_a, **_kw):
        return self

    def gte(self, *_a, **_kw):
        return self

    def order(self, *_a, **_kw):
        return self

    def execute(self):
        class _Res:
            def __init__(self, data):
                self.data = data
        return _Res(self._rows)


class _FakeClient:
    def __init__(self, sink: list[dict], rows: list[dict] | None = None):
        self._sink = sink
        self._rows = rows or []

    def table(self, name: str):
        t = _FakeTable(self._sink)
        t._rows = self._rows
        return t


def _score(total: float) -> ProviderScore:
    components = ScoreComponents(availability=1.0, coverage=1.0, reliability=1.0,
                                  quota=1.0, latency=1.0, priority=1.0)
    return ProviderScore(provider_id="beta", components=components, total=total)


def _recommendation(decision_changed=True) -> ProviderRecommendation:
    current = _score(0.5)
    recommended = _score(0.9) if decision_changed else current
    reason = RecommendationReason(component_deltas={"coverage": 0.4}) if decision_changed else None
    return ProviderRecommendation(
        league="Romania SuperLiga", data_type=DataType.FIXTURES, current_provider="alpha",
        current_score=current, recommended_provider="beta" if decision_changed else "alpha",
        recommended_score=recommended, reason=reason, decision_changed=decision_changed,
    )


def test_new_shadow_run_id_returns_uuid():
    run_id = shadow_recorder.new_shadow_run_id()
    assert isinstance(run_id, uuid.UUID)


def test_new_shadow_run_id_is_unique_per_call():
    a = shadow_recorder.new_shadow_run_id()
    b = shadow_recorder.new_shadow_run_id()
    assert a != b


def test_record_shadow_recommendation_writes_expected_row(monkeypatch):
    sink: list[dict] = []
    import supabase_client as sb
    monkeypatch.setattr(sb, "get_client", lambda: _FakeClient(sink))

    run_id = uuid.uuid4()
    ok = shadow_recorder.record_shadow_recommendation(_recommendation(), run_id)
    assert ok is True
    assert len(sink) == 1
    row = sink[0]
    assert row["shadow_run_id"] == str(run_id)
    assert row["algorithm_version"] == ALGORITHM_VERSION
    assert row["league"] == "Romania SuperLiga"
    assert row["data_type"] == "fixtures"
    assert row["current_provider"] == "alpha"
    assert row["recommended_provider"] == "beta"
    assert row["decision_changed"] is True
    assert row["component_deltas"] == {"coverage": 0.4}


def test_record_shadow_recommendation_null_reason_when_no_decision_change(monkeypatch):
    sink: list[dict] = []
    import supabase_client as sb
    monkeypatch.setattr(sb, "get_client", lambda: _FakeClient(sink))

    ok = shadow_recorder.record_shadow_recommendation(_recommendation(decision_changed=False), uuid.uuid4())
    assert ok is True
    assert sink[0]["component_deltas"] is None


def test_record_shadow_recommendation_false_when_supabase_unavailable(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "get_client", lambda: None)
    ok = shadow_recorder.record_shadow_recommendation(_recommendation(), uuid.uuid4())
    assert ok is False


def test_record_shadow_recommendation_degrades_gracefully_on_exception(monkeypatch):
    import supabase_client as sb

    def _raise():
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr(sb, "get_client", _raise)
    ok = shadow_recorder.record_shadow_recommendation(_recommendation(), uuid.uuid4())
    assert ok is False


def test_get_shadow_observations_converts_rows_to_domain_objects(monkeypatch):
    rows = [
        {"decision_changed": True, "recommended_provider": "beta", "current_score": 0.5, "recommended_score": 0.9},
        {"decision_changed": False, "recommended_provider": "alpha", "current_score": 0.8, "recommended_score": 0.8},
    ]
    import supabase_client as sb
    monkeypatch.setattr(sb, "get_client", lambda: _FakeClient([], rows=rows))

    observations = shadow_recorder.get_shadow_observations()
    assert len(observations) == 2
    assert observations[0].decision_changed is True
    assert observations[0].recommended_provider == "beta"
    assert observations[0].current_total == 0.5
    assert observations[0].recommended_total == 0.9


def test_get_shadow_observations_empty_when_supabase_unavailable(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "get_client", lambda: None)
    assert shadow_recorder.get_shadow_observations() == []


def test_get_shadow_observations_degrades_gracefully_on_exception(monkeypatch):
    import supabase_client as sb

    def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(sb, "get_client", _raise)
    assert shadow_recorder.get_shadow_observations() == []


def test_get_shadow_rows_returns_raw_dicts_unconverted(monkeypatch):
    rows = [{"league": "Romania SuperLiga", "data_type": "fixtures", "observed_at": "2026-07-19T10:00:00+00:00",
             "current_provider": "espn", "recommended_provider": "sportapi", "decision_changed": True,
             "component_deltas": {"coverage": 0.4}}]
    import supabase_client as sb
    monkeypatch.setattr(sb, "get_client", lambda: _FakeClient([], rows=rows))

    result = shadow_recorder.get_shadow_rows()
    assert result == rows  # neconvertit - exact rândul brut


def test_get_shadow_rows_empty_when_supabase_unavailable(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "get_client", lambda: None)
    assert shadow_recorder.get_shadow_rows() == []


def test_get_shadow_rows_degrades_gracefully_on_exception(monkeypatch):
    import supabase_client as sb

    def _raise():
        raise RuntimeError("boom")

    monkeypatch.setattr(sb, "get_client", _raise)
    assert shadow_recorder.get_shadow_rows() == []
