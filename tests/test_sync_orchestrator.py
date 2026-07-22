"""Teste pentru sync_orchestrator.py (R4.1, ADR-038 Step 5/7).

Niciun task real de sincronizare nu e inregistrat aici (R4.2, deferat) -
toate task-urile din aceste teste sunt fake-uri minimale, doar ca sa
verifice mecanismul de decizie in sine."""
from __future__ import annotations

from sync_orchestrator import Priority, SyncOrchestrator, SyncTask


class _FakeRequestManager:
    def __init__(self, allowed_providers=None):
        self._allowed = allowed_providers  # None = toate permise

    def should_request(self, provider):
        if self._allowed is None:
            return True
        return provider in self._allowed


def _orch(allowed_providers=None):
    return SyncOrchestrator(request_manager=_FakeRequestManager(allowed_providers))


def test_register_and_list_tasks():
    orch = _orch()
    orch.register_task(SyncTask(name="t1", provider="apifootball", priority=Priority.P1, run=lambda: None))
    assert [t.name for t in orch.tasks()] == ["t1"]


def test_unregister_task():
    orch = _orch()
    orch.register_task(SyncTask(name="t1", provider="apifootball", priority=Priority.P1, run=lambda: None))
    orch.unregister_task("t1")
    assert orch.tasks() == []


def test_should_run_unknown_task_is_not_eligible():
    orch = _orch()
    eligible, reason = orch.should_run("ghost")
    assert eligible is False
    assert "necunoscut" in reason


def test_should_run_eligible_task_with_no_gates():
    orch = _orch()
    orch.register_task(SyncTask(name="t1", provider="apifootball", priority=Priority.P1, run=lambda: None))
    eligible, reason = orch.should_run("t1")
    assert eligible is True


def test_should_run_blocked_by_budget():
    orch = _orch(allowed_providers=set())  # niciun provider permis
    orch.register_task(SyncTask(name="t1", provider="apifootball", priority=Priority.P1, run=lambda: None))
    eligible, reason = orch.should_run("t1")
    assert eligible is False
    assert "buget" in reason


def test_should_run_blocked_by_missing_dependency():
    orch = _orch()
    orch.register_task(SyncTask(
        name="t2", provider="apifootball", priority=Priority.P1, run=lambda: None,
        depends_on=("t1",),
    ))
    eligible, reason = orch.should_run("t2", succeeded_this_run=set())
    assert eligible is False
    assert "dependinte" in reason


def test_should_run_allowed_once_dependency_satisfied():
    orch = _orch()
    orch.register_task(SyncTask(
        name="t2", provider="apifootball", priority=Priority.P1, run=lambda: None,
        depends_on=("t1",),
    ))
    eligible, reason = orch.should_run("t2", succeeded_this_run={"t1"})
    assert eligible is True


def test_coverage_required_blocks_when_no_cache_entry(monkeypatch):
    import coverage_cache

    monkeypatch.setattr(coverage_cache, "get_cached_coverage", lambda *a, **kw: None)
    orch = _orch()
    orch.register_task(SyncTask(
        name="t1", provider="apifootball", priority=Priority.P1, run=lambda: None,
        coverage_required=True, league_id_canonical="Romania SuperLiga",
        api_football_league_id=283, season=2026,
    ))
    eligible, reason = orch.should_run("t1")
    assert eligible is False
    assert "coverage" in reason


def test_coverage_required_blocks_when_plan_restricted(monkeypatch):
    import coverage_cache

    monkeypatch.setattr(
        coverage_cache, "get_cached_coverage",
        lambda *a, **kw: {"fixtures_supported": "plan_restricted"},
    )
    orch = _orch()
    orch.register_task(SyncTask(
        name="t1", provider="apifootball", priority=Priority.P1, run=lambda: None,
        coverage_required=True, league_id_canonical="Romania SuperLiga",
        api_football_league_id=283, season=2026,
    ))
    eligible, _ = orch.should_run("t1")
    assert eligible is False


def test_coverage_required_allows_when_supported(monkeypatch):
    import coverage_cache

    monkeypatch.setattr(
        coverage_cache, "get_cached_coverage",
        lambda *a, **kw: {"fixtures_supported": "True"},
    )
    orch = _orch()
    orch.register_task(SyncTask(
        name="t1", provider="apifootball", priority=Priority.P1, run=lambda: None,
        coverage_required=True, league_id_canonical="Premier League",
        api_football_league_id=39, season=2025,
    ))
    eligible, _ = orch.should_run("t1")
    assert eligible is True


def test_coverage_required_missing_league_fields_blocks_defensively():
    orch = _orch()
    orch.register_task(SyncTask(
        name="t1", provider="apifootball", priority=Priority.P1, run=lambda: None,
        coverage_required=True,  # fara league_id_canonical/api_football_league_id/season
    ))
    eligible, _ = orch.should_run("t1")
    assert eligible is False


def test_run_pending_executes_in_priority_order():
    order = []
    orch = _orch()
    orch.register_task(SyncTask(name="low", provider="apifootball", priority=Priority.P5, run=lambda: order.append("low")))
    orch.register_task(SyncTask(name="high", provider="apifootball", priority=Priority.P1, run=lambda: order.append("high")))
    results = orch.run_pending()
    assert order == ["high", "low"]
    assert all(r.ran for r in results)


def test_run_pending_reports_skip_reason_without_running():
    orch = _orch(allowed_providers=set())
    ran_flag = []
    orch.register_task(SyncTask(name="t1", provider="apifootball", priority=Priority.P1, run=lambda: ran_flag.append(1)))
    results = orch.run_pending()
    assert ran_flag == []
    assert results[0].ran is False
    assert "buget" in results[0].reason


def test_run_pending_one_task_failure_does_not_stop_others():
    order = []

    def _boom():
        raise RuntimeError("simulated failure")

    orch = _orch()
    orch.register_task(SyncTask(name="a_fails", provider="apifootball", priority=Priority.P1, run=_boom))
    orch.register_task(SyncTask(name="b_ok", provider="apifootball", priority=Priority.P2, run=lambda: order.append("b_ok")))
    results = orch.run_pending()
    assert order == ["b_ok"]
    by_name = {r.task_name: r for r in results}
    assert by_name["a_fails"].ran is False
    assert by_name["a_fails"].error is not None
    assert by_name["b_ok"].ran is True


def test_run_pending_dependency_chain_respected_end_to_end():
    order = []
    orch = _orch()
    orch.register_task(SyncTask(name="first", provider="apifootball", priority=Priority.P2, run=lambda: order.append("first")))
    orch.register_task(SyncTask(
        name="second", provider="apifootball", priority=Priority.P1, run=lambda: order.append("second"),
        depends_on=("first",),
    ))
    results = orch.run_pending()
    # "second" are prioritate mai inalta (P1 < P2), dar depinde de "first" -
    # trebuie sa se ordoneze/astepte corect, nu doar dupa prioritate bruta.
    assert order == ["first", "second"]
    assert all(r.ran for r in results)
