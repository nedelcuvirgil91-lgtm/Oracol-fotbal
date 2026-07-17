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


class _FakeMatchResult:
    def __init__(self, data):
        self.data = data


class _FakeMatchQuery:
    """Simulează .table('match_history').select().not_.is_().eq().gt().execute()
    — suficient pentru _count_finished_matches(), nu chain-ul complet Supabase."""

    def __init__(self, rows):
        self._rows = list(rows)
        self.applied_eq: list[tuple] = []
        self.applied_gt: list[tuple] = []

    def select(self, *a, **kw):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        return self

    def eq(self, col, val):
        self.applied_eq.append((col, val))
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def gt(self, col, val):
        self.applied_gt.append((col, val))
        self._rows = [r for r in self._rows if r.get(col, "") > val]
        return self

    def execute(self):
        return _FakeMatchResult(list(self._rows))


class _FakeMatchClient:
    def __init__(self, rows):
        self._rows = rows
        self.last_query: _FakeMatchQuery | None = None

    def table(self, name):
        assert name == "match_history"
        q = _FakeMatchQuery(self._rows)
        self.last_query = q
        return q


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


def test_count_finished_matches_all_scope_ignores_league_filter(monkeypatch):
    """[Fix pre-activare learning_core_enabled] league='all' e sentinel
    ('nescopat pe o singura liga' - valoarea league_scope reala a tuturor
    algoritmilor de azi), nu o valoare din coloana match_history.league.
    Fara acest fix, .eq('league', 'all') nu s-ar potrivi niciodata cu vreun
    rand real, iar Faza B n-ar porni NICIODATA o antrenare automata."""
    rows = [
        {"id": 1, "league": "Premier League", "created_at": "2026-01-01"},
        {"id": 2, "league": "La Liga", "created_at": "2026-01-02"},
        {"id": 3, "league": "Serie A", "created_at": "2026-01-03"},
    ]
    fake_client = _FakeMatchClient(rows)
    monkeypatch.setattr(cl, "get_client", lambda: fake_client)

    result = cl._count_finished_matches("all", since=None)

    assert result == 3
    assert fake_client.last_query.applied_eq == [], \
        "league='all' nu trebuie sa aplice niciun filtru .eq('league', ...)"


def test_count_finished_matches_all_scope_respects_since(monkeypatch):
    """Ramura 'all' respecta aceeasi semantica temporala ca ramura pe liga -
    filtrul since ramane aplicat, doar filtrul de liga e omis."""
    rows = [
        {"id": 1, "league": "Premier League", "created_at": "2026-01-01"},
        {"id": 2, "league": "La Liga", "created_at": "2026-06-01"},
    ]
    fake_client = _FakeMatchClient(rows)
    monkeypatch.setattr(cl, "get_client", lambda: fake_client)

    result_no_since = cl._count_finished_matches("all", since=None)
    assert result_no_since == 2

    result_with_since = cl._count_finished_matches("all", since="2026-03-01")
    assert result_with_since == 1
    assert fake_client.last_query.applied_gt == [("created_at", "2026-03-01")]


def test_count_finished_matches_specific_league_unchanged(monkeypatch):
    """Comportament existent, neschimbat - o liga reala tot filtreaza pe
    .eq('league', ...), exact ca inainte de fix."""
    rows = [
        {"id": 1, "league": "Premier League", "created_at": "2026-01-01"},
        {"id": 2, "league": "La Liga", "created_at": "2026-01-02"},
    ]
    fake_client = _FakeMatchClient(rows)
    monkeypatch.setattr(cl, "get_client", lambda: fake_client)

    result = cl._count_finished_matches("Premier League", since=None)

    assert result == 1
    assert fake_client.last_query.applied_eq == [("league", "Premier League")]


def test_phase_b_end_to_end_with_all_scope_and_real_match_counting(recorder, monkeypatch):
    """Test de integrare: cu _count_finished_matches() REAL (nemonkeypatch-uit,
    spre deosebire de restul testelor din acest fisier), un algoritm cu
    league_scope='all' si suficiente meciuri reale trebuie sa ajunga efectiv
    la run_training() -> create_challenger(). Inainte de fix, acest test ar
    fi esuat (0 meciuri numarate mereu pentru 'all')."""
    algo = _FakeAlgorithm(name="algo_all_scope", league_scope="all")
    model_registry.register(algo)

    rows = [{"id": i, "league": "Premier League", "created_at": "2026-01-01"} for i in range(50)]
    fake_client = _FakeMatchClient(rows)
    monkeypatch.setattr(cl, "get_client", lambda: fake_client)

    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda family, league: 0)
    monkeypatch.setattr(cl.sb, "get_latest_training_run", lambda family, league: None)

    created = {}
    monkeypatch.setattr(cl.challenger_manager, "create_challenger",
                         lambda tid, family, league: created.setdefault("id", tid) or {"training_run_id": tid})
    monkeypatch.setattr(cl.challenger_manager, "transition",
                         lambda tid, to_state, rejection_reason=None: None)

    result = cl.run_cycle()

    assert result["trained"] == 1
    assert created["id"] == "tr_fake_1"


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


def test_algorithm_opted_out_of_challenger_framework_is_skipped_entirely(recorder, monkeypatch):
    """[ADR-028] Un algoritm cu participates_in_challenger_framework=False
    (ex. league_weights_adaptive) e sarit complet - checked se incrementeaza
    (a fost vazut in Registry), dar nicio Faza A/B/C nu ruleaza pentru el:
    fara automation_runs, fara count_active_challengers, fara Challenger nou."""
    class _OptedOutAlgorithm(_FakeAlgorithm):
        def describe(self):
            return {"participates_in_challenger_framework": False}

    model_registry.register(_OptedOutAlgorithm(name="league_weights_adaptive", league_scope="all"))

    def _fail_if_called(*a, **kw):
        raise AssertionError("count_active_challengers nu trebuie apelat pentru un algoritm opted-out")

    monkeypatch.setattr(cl.sb, "count_active_challengers", _fail_if_called)

    result = cl.run_cycle()

    assert result["checked"] == 1
    assert result["trained"] == 0
    assert result["evaluated"] == 0
    assert recorder.calls == [], "niciun automation_run nu trebuie creat pentru un algoritm opted-out"


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
