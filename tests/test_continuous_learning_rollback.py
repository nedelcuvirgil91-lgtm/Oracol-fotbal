"""
Teste pentru integrarea Champion Guardian în learning_core/continuous_learning.py
(ADR-037, Stage R3 — Faza D).

R3.1 (read-only): Faza D evaluează campionul activ prin
champion_guardian.evaluate_champion_health() și jurnalizează rezultatul.

R3.2A (propunere, aprobată): dacă Guardian recomandă rollback, Faza D
propune o decizie T3a în decision feed — NICIODATĂ automat, doar propunere.
Trei gărzi obligatorii, verificate mai jos:
  - gardă anti-ping-pong (Stratul 3, ADR-037 §14) — lanț automat plafonat
    la un singur pas, prin rollback_service.is_rollback_promoted() (NU
    parsing local de promoted_by);
  - gardă R3-Risk-1 — nu se stivuiește o propunere peste o decizie deschisă
    deja existentă pe același target (propose_decision suprascrie evidence);
  - maparea health_state -> rollback reason (Opțiunea A) fără atingerea
    contractului Champion Guardian (R2).

R3.2B (execuția efectivă a rollback-ului aprobat, în Faza C) NU e implementată
încă — garda mecanică de mai jos (test_module_does_not_yet_execute_rollback)
impune asta explicit, ca punct de graniță auditabil.

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
    brier_live: float | None = None
    window_end: str | None = None
    n_matches_evaluated: int = 0


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
    # Implicit: niciun campion "rollback-promoted" (izolează testele de
    # gardă anti-ping-pong de restul, dacă nu suprascrise explicit).
    monkeypatch.setattr(cl.sb, "get_active_champion",
                         lambda family, league: {"training_run_id": "tr_champion", "promoted_by": "ADR-030-continuous-learning"})
    return rec


class _FakeDecisionFeedResult:
    def __init__(self, data):
        self.data = data


class _FakeDecisionFeedQuery:
    """Simulează .table(...).select().eq()/.in_()/.limit().execute() — suficient
    pentru _has_open_decision_for_target(), nu chain-ul complet Supabase."""

    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **kw):
        return self

    def eq(self, col, val):
        self._rows = [r for r in self._rows if r.get(col) == val]
        return self

    def in_(self, col, values):
        vals = set(values)
        self._rows = [r for r in self._rows if r.get(col) in vals]
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _FakeDecisionFeedResult(list(self._rows))


class _FakeDecisionFeedClient:
    """Simulează get_client() pentru _has_open_decision_for_target: două
    tabele — automation_runs (id, target_key) și decision_feed (id, run_id, status)."""

    def __init__(self, runs, decisions):
        self._runs = runs
        self._decisions = decisions

    def table(self, name):
        if name == "automation_runs":
            return _FakeDecisionFeedQuery(self._runs)
        if name == "decision_feed":
            return _FakeDecisionFeedQuery(self._decisions)
        raise AssertionError(f"tabelă neașteptată: {name}")


def _health_completes(recorder_calls):
    complete_calls = [c for c in recorder_calls if c[0] == "complete_run"]
    return [c for c in complete_calls if c[2] and "health_state" in c[2]]


# ── R3.2A/R3.2B — gardă mecanică de graniță (sursă, nu doar comportament) ──

def test_module_does_not_yet_execute_rollback():
    """Graniță R3.2A/R3.2B: propunerea (R3.2A, aprobată) nu trebuie
    NICIODATĂ să execute rollback-ul. Verificare mecanică pe sursa întregului
    modul — rollback_champion() nu trebuie apelat de nicăieri până la
    aprobarea explicită a R3.2B."""
    src = inspect.getsource(cl)
    assert "rollback_service.rollback_champion(" not in src
    assert ".rollback_champion(" not in src


def test_phase_c_source_unchanged_no_decision_kind_branch():
    """R3.2A nu modifică Faza C — nicio ramificare pe decision_kind acolo
    încă (vine în R3.3, aprobată separat)."""
    src = inspect.getsource(cl._phase_c_execute_approved)
    assert "decision_kind" not in src
    assert "rollback" not in src.lower()


def test_is_rollback_promoted_not_reimplemented_locally():
    """Cerința de decuplare (aprobată explicit): continuous_learning.py nu
    are voie să interpreteze formatul promoted_by direct — nici
    startswith('rollback:'), nici split(':'), nici regex. Toată logica
    rămâne în rollback_service.is_rollback_promoted()."""
    src = inspect.getsource(cl)
    assert 'startswith("rollback:")' not in src
    assert "startswith('rollback:')" not in src
    assert 're.match' not in src and 're.search' not in src


# ── R3.1 — comportament Faza D (read-only, healthy/insufficient/None) ──────

def test_phase_d_logs_health_state_without_deciding(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(health_state="healthy", recommends_rollback=False, reason=None),
    )
    result = cl.run_cycle()

    assert result["health_checked"] == 1
    assert result["rollback_proposed"] == 0

    write_calls = [c for c in recorder.calls if c[0] == "write_run"]
    health_writes = [c for c in write_calls if c[2] == "champion_health_check"]
    assert len(health_writes) == 1
    assert health_writes[0][3] == "T2"

    health_completes = _health_completes(recorder.calls)
    assert len(health_completes) == 1
    assert health_completes[0][2] == {
        "health_state": "healthy", "recommends_rollback": False, "reason": None,
    }
    assert [c for c in recorder.calls if c[0] == "propose_decision"] == []


def test_phase_d_skips_when_no_active_champion(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(cl.champion_guardian, "evaluate_champion_health", lambda family, league: None)
    result = cl.run_cycle()

    assert result["health_checked"] == 0
    skip_calls = [c for c in recorder.calls if c[0] == "skip_run"]
    assert any("campion activ" in c[2] for c in skip_calls)


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


# ── R3.2A — propunere T3a de rollback ───────────────────────────────────────

def test_phase_d_proposes_t3a_rollback_when_recommended(recorder, fake_algorithm, monkeypatch):
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(
            health_state="degrading", recommends_rollback=True,
            reason="regression: ferestre degradate consecutive (baseline/trend)",
            brier_live=0.27, window_end="2026-07-01", n_matches_evaluated=42,
        ),
    )
    result = cl.run_cycle()

    assert result["health_checked"] == 1
    assert result["rollback_proposed"] == 1

    propose_calls = [c for c in recorder.calls if c[0] == "propose_decision"]
    assert len(propose_calls) == 1
    _, _, tier, rollback_plan, evidence, correction_method = propose_calls[0]
    assert tier == "T3a"
    assert rollback_plan is not None
    assert evidence["decision_kind"] == "rollback"
    assert evidence["reason"] == "regression"
    assert evidence["health_state"] == "degrading"
    assert evidence["n_matches_evaluated"] == 42
    assert correction_method == "none — pre-ADR-034"

    assert [c for c in recorder.calls if c[0] == "surface_decision"] == [("surface_decision", 1)]

    write_calls = [c for c in recorder.calls if c[0] == "write_run"]
    assert any(c[2] == "rollback_candidate" and c[3] == "T3a" for c in write_calls)


@pytest.mark.parametrize("prefix,expected", [
    ("artifact_missing: artefactul nu a putut fi incarcat", "artifact_missing"),
    ("model_error: predict_proba invalid", "model_error"),
])
def test_phase_d_reason_mapping_structural(recorder, fake_algorithm, monkeypatch, prefix, expected):
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(health_state="critical", recommends_rollback=True, reason=prefix),
    )
    cl.run_cycle()
    propose_calls = [c for c in recorder.calls if c[0] == "propose_decision"]
    assert propose_calls[0][4]["reason"] == expected


def test_phase_d_reason_mapping_fallback_to_regression_when_indeterminate(recorder, fake_algorithm, monkeypatch):
    """Critical, dar fără cod structural recunoscut in reason -> fallback
    sigur pe 'regression' (motiv valid, niciodată un motiv inventat/necunoscut)."""
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(health_state="critical", recommends_rollback=True, reason=None),
    )
    cl.run_cycle()
    propose_calls = [c for c in recorder.calls if c[0] == "propose_decision"]
    assert propose_calls[0][4]["reason"] == "regression"


# ── R3.2A — gardă anti-ping-pong (Stratul 3) ────────────────────────────────

def test_phase_d_anti_ping_pong_suppresses_proposal(recorder, fake_algorithm, monkeypatch):
    """Campionul activ a fost el însuși reactivat printr-un rollback anterior
    (promoted_by = 'rollback:...') — o nouă degradare NU trebuie să propună
    automat un al doilea rollback (ar reveni la predecesorul deja abandonat
    ca degradat). Interpretarea trece exclusiv prin
    rollback_service.is_rollback_promoted()."""
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(
            health_state="degrading", recommends_rollback=True, reason="regression: ...",
        ),
    )
    monkeypatch.setattr(
        cl.sb, "get_active_champion",
        lambda family, league: {"training_run_id": "tr_reactivated", "promoted_by": "rollback:regression:op1"},
    )

    result = cl.run_cycle()

    assert result["health_checked"] == 1
    assert result["rollback_proposed"] == 0
    assert [c for c in recorder.calls if c[0] == "propose_decision"] == []

    health_completes = _health_completes(recorder.calls)
    assert health_completes[0][2]["chain_rollback_suppressed"] is True


# ── R3.2A — gardă R3-Risk-1 (testul cel mai important din R3.2A) ───────────

def test_phase_d_skips_rollback_proposal_when_open_decision_exists_for_target(recorder, fake_algorithm, monkeypatch):
    """R3-Risk-1: dacă există deja o decizie DESCHISĂ pentru target (aici:
    o decizie 'pending' — indiferent de fel, ex. o promovare candidat),
    Guardian recomandând rollback NU trebuie:
      - să creeze o a doua decizie (propose_decision NU se apelează deloc —
        deci evidence-ul decizei existente nu poate fi suprascris, fiindcă
        singurul mecanism de suprascriere e propose_decision însuși);
      - să emită un run 'rollback_candidate'.
    Guardian TOT rulează (evaluarea rămâne făcută, health_checked=1), iar
    run-ul Fazei D se închide cu skip_run, motivat explicit."""
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(
            health_state="critical", recommends_rollback=True,
            reason="artifact_missing: artefactul nu a putut fi incarcat",
        ),
    )
    # Campion NEreactivat prin rollback — izolează testul strict de gardă
    # anti-ping-pong (care ar suprima independent, din alt motiv).
    monkeypatch.setattr(cl.sb, "get_active_champion",
                         lambda family, league: {"training_run_id": "tr_x", "promoted_by": "ADR-030-continuous-learning"})

    fake_client = _FakeDecisionFeedClient(
        runs=[{"id": 501, "target_key": "fake_algo|Premier League"}],
        decisions=[{"id": 9001, "run_id": 501, "status": "pending"}],  # decizie deschisă preexistentă
    )
    monkeypatch.setattr(cl, "get_client", lambda: fake_client)

    result = cl.run_cycle()

    # Guardian a rulat — evaluarea rămâne făcută.
    assert result["health_checked"] == 1
    # NU se creează nicio decizie nouă -> evidence-ul celei existente nu poate
    # fi suprascris (singurul mecanism de suprascriere e propose_decision).
    assert [c for c in recorder.calls if c[0] == "propose_decision"] == []
    assert [c for c in recorder.calls if c[0] == "surface_decision"] == []
    # NU se emite un run de tip rollback_candidate.
    write_calls = [c for c in recorder.calls if c[0] == "write_run"]
    assert [c for c in write_calls if c[2] == "rollback_candidate"] == []
    # Run-ul Fazei D se închide cu skip, motivat (alături de skip-ul separat,
    # nelegat, al Fazei B sub prag de volum — zgomot așteptat, ignorat aici).
    skip_calls = [c for c in recorder.calls if c[0] == "skip_run"]
    health_skips = [c for c in skip_calls if "decizie deschisa" in c[2]]
    assert len(health_skips) == 1
    assert result["rollback_proposed"] == 0


def test_phase_d_proposes_when_no_open_decision_exists_for_target(recorder, fake_algorithm, monkeypatch):
    """Control pozitiv pentru testul de mai sus: fără nicio decizie deschisă
    pe target, propunerea de rollback se face normal."""
    monkeypatch.setattr(
        cl.champion_guardian, "evaluate_champion_health",
        lambda family, league: _FakeHealthResult(health_state="degrading", recommends_rollback=True, reason="x"),
    )
    fake_client = _FakeDecisionFeedClient(runs=[], decisions=[])
    monkeypatch.setattr(cl, "get_client", lambda: fake_client)

    result = cl.run_cycle()

    assert result["rollback_proposed"] == 1
    assert len([c for c in recorder.calls if c[0] == "propose_decision"]) == 1
