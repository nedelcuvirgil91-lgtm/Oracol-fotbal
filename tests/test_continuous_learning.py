"""
Teste pentru learning_core/continuous_learning.py (ADR-030) — funcția
decuplată de run_daily.py, orchestrator peste mecanica deja existentă
(Model Registry, Challenger FSM, Statistics Engine, Promotion Service).

Fiecare funcție externă (automation_runs, challenger_manager,
challenger_evaluation, run_training, promote_challenger, supabase_client)
e monkeypatch-uită direct — testele verifică exclusiv logica de
orchestrare (ce se apelează, în ce ordine, cu ce date), nu re-testează
mecanica deja acoperită de suitele proprii ale acelor module.

Niciun test nu atinge rețeaua sau Supabase live.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

import learning_core.continuous_learning as cl
from learning_core import model_registry
from learning_core.model_registry import TrainingRunResult


class _FakeAlgorithm:
    def __init__(self, name="fake_algo", version="1", league_scope="Premier League"):
        self.name = name
        self.version = version
        self.league_scope = league_scope

    def fit(self, training_data):
        return TrainingRunResult(training_run_id="tr_fake_1", status="trained", samples_used=250)

    def predict(self, features):
        return (0.4, 0.3, 0.3, {})

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


@pytest.fixture()
def recorder(monkeypatch):
    rec = _CallRecorder()
    monkeypatch.setattr(cl, "ar", rec)
    monkeypatch.setattr(cl.sb, "load_config", lambda default: {"learning_core_enabled": True})
    return rec


def test_disabled_by_default_skips_entire_cycle(monkeypatch, fake_algorithm):
    monkeypatch.setattr(cl.sb, "load_config", lambda default: dict(default))
    result = cl.run_cycle()
    assert result == {"enabled": False}


def test_guard_blocks_when_more_than_one_active_challenger(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 2)
    result = cl.run_cycle()
    assert result["guard_failures"] == 1
    assert result["trained"] == 0
    assert result["evaluated"] == 0
    fail_calls = [c for c in recorder.calls if c[0] == "fail_run"]
    assert len(fail_calls) == 1
    assert "anomalie" in fail_calls[0][2]


def test_guard_blocks_on_unknown_count(recorder, fake_algorithm, monkeypatch):
    """count_active_challengers()==-1 (Supabase indisponibil) nu trebuie
    niciodată tratat ca 'sigur, continuă' — regula 'nu se aproximează'."""
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: -1)
    result = cl.run_cycle()
    assert result["guard_failures"] == 1


def test_phase_b_skips_training_below_threshold(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 0)
    monkeypatch.setattr(cl.sb, "get_latest_training_run", lambda family, league: None)
    monkeypatch.setattr(cl, "_count_finished_matches", lambda league, since=None: 5)  # sub prag
    result = cl.run_cycle()
    assert result["trained"] == 0
    skip_calls = [c for c in recorder.calls if c[0] == "skip_run"]
    assert any("prag de volum" in c[2] for c in skip_calls)


def test_phase_b_trains_and_creates_challenger_above_threshold(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 0)
    monkeypatch.setattr(cl.sb, "get_latest_training_run", lambda family, league: None)
    monkeypatch.setattr(cl, "_count_finished_matches", lambda league, since=None: 500)

    created = {}
    transitions = []

    monkeypatch.setattr(cl.challenger_manager, "create_challenger",
                         lambda tid, family, league: created.setdefault("id", tid) or {"training_run_id": tid})
    monkeypatch.setattr(cl.challenger_manager, "transition",
                         lambda tid, to_state, rejection_reason=None: transitions.append(to_state))

    result = cl.run_cycle()
    assert result["trained"] == 1
    assert created["id"] == "tr_fake_1"
    assert transitions == ["WAITING", "EVALUATING"]


def test_phase_a_candidate_for_promotion_creates_t3a_decision(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 1)
    monkeypatch.setattr(
        cl.challenger_evaluation, "evaluate_active_challenger",
        lambda family, league, min_matches=200: {
            "status": "candidate_for_promotion", "n_matches_evaluated": 210,
            "delta_brier": -0.03, "brier_significant": True,
        },
    )
    monkeypatch.setattr(cl.challenger_manager, "get_active_challenger",
                         lambda family, league: {"training_run_id": "tr_active_1"})
    transitions = []
    monkeypatch.setattr(cl.challenger_manager, "transition",
                         lambda tid, to_state, rejection_reason=None: transitions.append((tid, to_state)))

    result = cl.run_cycle()
    assert result["evaluated"] == 1
    assert result["proposed"] == 1
    assert transitions == [("tr_active_1", "SUCCEEDED")]

    propose_calls = [c for c in recorder.calls if c[0] == "propose_decision"]
    assert len(propose_calls) == 1
    _, _, tier, rollback_plan, evidence, correction_method = propose_calls[0]
    assert tier == "T3a"
    assert rollback_plan is not None, "T3a fara rollback_plan ar incalca precondiția structurala"
    assert evidence["training_run_id"] == "tr_active_1"
    assert correction_method == "none — pre-ADR-034"


def test_phase_a_rejected_verdict_transitions_challenger(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 1)
    monkeypatch.setattr(
        cl.challenger_evaluation, "evaluate_active_challenger",
        lambda family, league, min_matches=200: {"status": "rejected", "n_matches_evaluated": 210},
    )
    monkeypatch.setattr(cl.challenger_manager, "get_active_challenger",
                         lambda family, league: {"training_run_id": "tr_active_2"})
    transitions = []
    monkeypatch.setattr(cl.challenger_manager, "transition",
                         lambda tid, to_state, rejection_reason=None: transitions.append((tid, to_state, rejection_reason)))

    cl.run_cycle()
    assert transitions == [("tr_active_2", "REJECTED", "verdict_negative")]
    propose_calls = [c for c in recorder.calls if c[0] == "propose_decision"]
    assert propose_calls == [], "un verdict respins nu propune nicio decizie T3a"


def test_phase_a_monitoring_verdict_takes_no_action(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 1)
    monkeypatch.setattr(
        cl.challenger_evaluation, "evaluate_active_challenger",
        lambda family, league, min_matches=200: {"status": "monitoring", "n_matches_evaluated": 80},
    )
    monkeypatch.setattr(cl.challenger_manager, "get_active_challenger",
                         lambda family, league: {"training_run_id": "tr_active_3"})
    transitions = []
    monkeypatch.setattr(cl.challenger_manager, "transition",
                         lambda *a, **k: transitions.append(a))

    cl.run_cycle()
    assert transitions == [], "monitoring nu tranzitioneaza FSM-ul"


def test_phase_c_commits_approved_decision_via_promotion_service(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 0)
    monkeypatch.setattr(cl.sb, "get_latest_training_run", lambda family, league: {"created_at": "x"})
    monkeypatch.setattr(cl, "_count_finished_matches", lambda league, since=None: 0)  # sub prag -> skip B

    target_key = "fake_algo|Premier League"
    recorder.approved_for_target[target_key] = [
        {"id": 99, "evidence": {"training_run_id": "tr_active_1"}}
    ]

    @dataclass
    class _FakePromotionResult:
        status: str
        training_run_id: str
        reason: str | None = None

    monkeypatch.setattr(cl, "promote_challenger",
                         lambda training_run_id, algorithm_family, league_scope, promoted_by:
                             _FakePromotionResult(status="promoted", training_run_id=training_run_id))

    result = cl.run_cycle()
    assert result["committed"] == 1
    commit_calls = [c for c in recorder.calls if c[0] == "commit_decision"]
    assert commit_calls == [(  "commit_decision", 99)]


def test_phase_c_marks_commit_failed_when_promotion_rejected(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 0)
    monkeypatch.setattr(cl.sb, "get_latest_training_run", lambda family, league: {"created_at": "x"})
    monkeypatch.setattr(cl, "_count_finished_matches", lambda league, since=None: 0)

    target_key = "fake_algo|Premier League"
    recorder.approved_for_target[target_key] = [
        {"id": 100, "evidence": {"training_run_id": "tr_bad"}}
    ]

    @dataclass
    class _FakePromotionResult:
        status: str
        training_run_id: str
        reason: str | None = None

    monkeypatch.setattr(cl, "promote_challenger",
                         lambda training_run_id, algorithm_family, league_scope, promoted_by:
                             _FakePromotionResult(status="rejected", training_run_id=training_run_id,
                                                   reason="Challenger nu e SUCCEEDED"))

    result = cl.run_cycle()
    assert result["committed"] == 0
    fail_calls = [c for c in recorder.calls if c[0] == "fail_decision_commit"]
    assert len(fail_calls) == 1 and fail_calls[0][1] == 100


def test_generic_over_multiple_registry_entries(recorder, monkeypatch):
    """Fara nicio ramura speciala per algoritm — un al doilea algoritm
    inregistrat e procesat identic, fara nicio schimbare de cod."""
    model_registry.register(_FakeAlgorithm(name="algo_a", league_scope="Premier League"))
    model_registry.register(_FakeAlgorithm(name="algo_b", league_scope="La Liga"))
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 0)
    monkeypatch.setattr(cl.sb, "get_latest_training_run", lambda family, league: None)
    monkeypatch.setattr(cl, "_count_finished_matches", lambda league, since=None: 0)

    result = cl.run_cycle()
    assert result["checked"] == 2
