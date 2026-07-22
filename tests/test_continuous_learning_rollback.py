"""
Teste pentru integrarea Champion Guardian în learning_core/continuous_learning.py
(ADR-037, Stage R3.1 — Faza D, STRICT READ-ONLY).

Scope R3.1 (impus aici, mecanic ȘI comportamental): Faza D evaluează
campionul activ prin champion_guardian.evaluate_champion_health() și
jurnalizează rezultatul într-un automation_run — atât. NU propune nicio
decizie T3a, NU apelează rollback_service, NU atinge decision_feed. Acest
fișier crește etapă cu etapă (R3.2, R3.3...) pe măsură ce scope-ul se extinde
— la R3.1, garda de mai jos trebuie să rămână verde.

Niciun test nu atinge rețeaua sau Supabase live.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest

import learning_core.continuous_learning as cl
from learning_core import model_registry


class _FakeAlgorithm:
    def __init__(self, name="fake_algo", version="1", league_scope="Premier League"):
        self.name = name
        self.version = version
        self.league_scope = league_scope

    def describe(self):
        return {}


@pytest.fixture(autouse=True)
def clean_registry():
    model_registry._clear_registry_for_tests()
    yield
    model_registry._clear_registry_for_tests()


@pytest.fixture()
def fake_algorithm():
    algo = _FakeAlgorithm()
    model_registry.register(algo)
    return algo


class _CallRecorder:
    """Substituie automation_runs — captează apelurile fără nicio scriere reală."""

    def __init__(self):
        self.calls = []
        self._next_run_id = 1
        self._next_decision_id = 1
        self.approved_for_target = {}

    def write_run(self, producer, process_type, tier, target_key=None):
        self.calls.append(("write_run", producer, process_type, tier, target_key))
        rid = self._next_run_id
        self._next_run_id += 1
        return rid

    def start_run(self, run_id):
        self.calls.append(("start_run", run_id))
        return True

    def complete_run(self, run_id, summary=None):
        self.calls.append(("complete_run", run_id, summary))
        return True

    def fail_run(self, run_id, error_detail):
        self.calls.append(("fail_run", run_id, error_detail))
        return True

    def skip_run(self, run_id, skip_reason):
        self.calls.append(("skip_run", run_id, skip_reason))
        return True

    def propose_decision(self, run_id, tier, rollback_plan=None, evidence=None,
                          correction_method=None, ttl_hours=None):
        self.calls.append(("propose_decision", run_id, tier, rollback_plan, evidence, correction_method))
        did = self._next_decision_id
        self._next_decision_id += 1
        return did

    def surface_decision(self, decision_id):
        self.calls.append(("surface_decision", decision_id))
        return True

    def commit_decision(self, decision_id):
        self.calls.append(("commit_decision", decision_id))
        return True

    def fail_decision_commit(self, decision_id, error_detail):
        self.calls.append(("fail_decision_commit", decision_id, error_detail))
        return True

    def list_approved_decisions_for_target(self, target_key):
        return self.approved_for_target.get(target_key, [])


@dataclass
class _FakeHealthResult:
    health_state: str
    recommends_rollback: bool = False
    reason: str | None = None


@pytest.fixture()
def recorder(monkeypatch):
    rec = _CallRecorder()
    monkeypatch.setattr(cl, "ar", rec)
    monkeypatch.setattr(cl.sb, "load_config", lambda default: {"learning_core_enabled": True})
    # Izolează Faza D de Faza A/B — fără challenger activ, sub prag de antrenare
    # — ca fiecare test să vadă doar activitatea Fazei D (+ Faza C, goală).
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 0)
    monkeypatch.setattr(cl.sb, "get_latest_training_run", lambda family, league: None)
    monkeypatch.setattr(cl, "_count_finished_matches", lambda league, since=None: 0)
    return rec


# ── R3.1 — gardă mecanică de scope (sursă, nu doar comportament) ───────────

def test_phase_d_source_contains_no_forbidden_calls():
    """Garda mecanică R3.1: Faza D trebuie să fie 100% read-only — fără
    propose_decision, fără surface_decision, fără rollback_service, fără
    decision_kind. Verificare directă pe sursa funcției (nu doar
    comportamentală), ca să surprindă orice adăugare accidentală înainte
    de aprobarea explicită a R3.2."""
    src = inspect.getsource(cl._phase_d_champion_health)
    forbidden = [
        "propose_decision", "surface_decision", "rollback_service",
        "rollback_champion", "decision_kind", "rollback_candidate",
    ]
    for token in forbidden:
        assert token not in src, f"Faza D (R3.1) conține {token!r} — încalcă scope-ul strict read-only"


def test_module_does_not_yet_wire_rollback_execution():
    """Scope R3.1 la nivel de modul: rollback_service și decision_kind nu
    sunt cablate încă (vin în R3.2/R3.3, aprobate separat)."""
    src = inspect.getsource(cl)
    assert "rollback_service" not in src
    assert "decision_kind" not in src
    assert "rollback_candidate" not in src


# ── R3.1 — comportament Faza D ──────────────────────────────────────────────

def test_phase_d_logs_health_state_without_deciding(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(health_state="healthy", recommends_rollback=False, reason=None),
    )
    result = cl.run_cycle()

    assert result["health_checked"] == 1

    write_calls = [c for c in recorder.calls if c[0] == "write_run"]
    health_writes = [c for c in write_calls if c[2] == "champion_health_check"]
    assert len(health_writes) == 1
    assert health_writes[0][3] == "T2"

    complete_calls = [c for c in recorder.calls if c[0] == "complete_run"]
    health_completes = [c for c in complete_calls if c[2] and "health_state" in c[2]]
    assert len(health_completes) == 1
    assert health_completes[0][2] == {
        "health_state": "healthy", "recommends_rollback": False, "reason": None,
    }

    # Nicio decizie, indiferent de fază — Faza D e read-only, Faza C n-are ce executa.
    assert [c for c in recorder.calls if c[0] == "propose_decision"] == []


def test_phase_d_skips_when_no_active_champion(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.champion_guardian, "evaluate_champion_health", lambda family, league: None)
    result = cl.run_cycle()

    assert result["health_checked"] == 0
    skip_calls = [c for c in recorder.calls if c[0] == "skip_run"]
    assert any("campion activ" in c[2] for c in skip_calls)


def test_phase_d_recommends_rollback_but_proposes_nothing_in_r3_1(recorder, fake_algorithm, monkeypatch):
    """Cazul critic al scope-ului R3.1: chiar și la o recomandare de rollback
    (health_state='critical'), Faza D NU propune nicio decizie T3a — doar
    jurnalizează. Propunerea e Stage R3.2, neaprobată/neimplementată încă."""
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(
            health_state="critical", recommends_rollback=True,
            reason="artifact_missing: artefactul nu a putut fi încărcat",
        ),
    )
    result = cl.run_cycle()

    assert result["health_checked"] == 1
    assert [c for c in recorder.calls if c[0] == "propose_decision"] == []
    assert [c for c in recorder.calls if c[0] == "surface_decision"] == []

    complete_calls = [c for c in recorder.calls if c[0] == "complete_run"]
    health_completes = [c for c in complete_calls if c[2] and "health_state" in c[2]]
    assert health_completes[0][2]["recommends_rollback"] is True
    assert health_completes[0][2]["health_state"] == "critical"


def test_phase_d_disabled_gate_skips_entirely(fake_algorithm, monkeypatch):
    """learning_core_enabled=False -> ciclul întreg (inclusiv Faza D) e sărit,
    exact ca Fazele A/B/C existente (P1 — nimic nou pornește implicit activ)."""
    monkeypatch.setattr(cl.sb, "load_config", lambda default: dict(default))
    called = {"n": 0}
    monkeypatch.setattr(cl.champion_guardian, "evaluate_champion_health",
                         lambda family, league: called.__setitem__("n", called["n"] + 1))
    result = cl.run_cycle()
    assert result == {"enabled": False}
    assert called["n"] == 0


def test_phase_d_opted_out_algorithm_is_skipped_entirely(monkeypatch):
    """[ADR-028, precedent existent] Un algoritm opted-out din challenger
    framework nu ajunge deloc la Faza D — se oprește la garda existentă
    din _process_pair, înaintea oricărei faze."""
    class _OptedOutAlgorithm(_FakeAlgorithm):
        def describe(self):
            return {"participates_in_challenger_framework": False}

    model_registry.register(_OptedOutAlgorithm(name="league_weights_adaptive", league_scope="all"))

    rec = _CallRecorder()
    called = {"n": 0}

    def _fail_if_called(*a, **kw):
        called["n"] += 1
        raise AssertionError("evaluate_champion_health nu trebuie apelat pentru un algoritm opted-out")

    monkeypatch.setattr(cl, "ar", rec)
    monkeypatch.setattr(cl.sb, "load_config", lambda default: {"learning_core_enabled": True})
    monkeypatch.setattr(cl.sb, "count_active_challengers",
                         lambda family, league: (_ for _ in ()).throw(
                             AssertionError("count_active_challengers nu trebuie apelat pentru opted-out")))
    monkeypatch.setattr(cl.champion_guardian, "evaluate_champion_health", _fail_if_called)

    result = cl.run_cycle()

    assert result["checked"] == 1
    assert result["health_checked"] == 0
    assert called["n"] == 0
    assert rec.calls == []
