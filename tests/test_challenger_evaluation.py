"""
Teste pentru learning_core.challenger_evaluation (Shadow Evaluation) —
Pasul 4, ADR-018. Fără rețea.

Cerința centrală, impusă explicit de Chief Architect Review: verdictul
trebuie să fie IMUABIL — odată calculat pentru un training_run_id și o
fereastră de evaluare (n_matches_evaluated) dată, o rerulare a job-ului NU
trebuie să-l schimbe. Testat end-to-end (`test_immutability_second_write_
with_same_window_is_a_noop`) printr-un Supabase fabricat care reproduce
fidel UNIQUE (training_run_id, n_matches_evaluated) + ON CONFLICT DO
NOTHING (ignore_duplicates=True) — nu doar presupus.
"""
import pytest

from learning_core import challenger_evaluation as ce


def _full_candidate_result(n: int = 250) -> dict:
    return {
        "status": "candidate_for_promotion", "n_matches_evaluated": n,
        "evaluation_window_start": "2026-01-01", "evaluation_window_end": "2026-06-01",
        "brier_baseline": 0.62, "brier_experiment": 0.55, "delta_brier": -0.07, "brier_significant": True,
        "logloss_baseline": 1.05, "logloss_experiment": 0.98, "delta_logloss": -0.07, "logloss_significant": True,
        "accuracy_baseline": 0.45, "accuracy_experiment": 0.50, "delta_accuracy": 0.05, "accuracy_significant": True,
        "statistical_method": "paired_bootstrap",
    }


# ── evaluate_active_challenger: orchestrare ─────────────────────────────────

def test_no_active_challenger_returns_none(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: None,
    )

    def _fail_if_called(*a, **kw):
        raise AssertionError("shadow_testing.evaluate_experiment nu trebuie apelat fara Challenger activ")

    monkeypatch.setattr("shadow_testing.evaluate_experiment", _fail_if_called)

    result = ce.evaluate_active_challenger("xgboost_v1", "all")
    assert result is None


def test_evaluate_experiment_failure_returns_none(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-1"},
    )
    monkeypatch.setattr("shadow_testing.evaluate_experiment", lambda **kw: None)

    def _fail_if_called(*a, **kw):
        raise AssertionError("supabase_client.record_challenger_evaluation nu trebuie apelat fara rezultat")

    monkeypatch.setattr("supabase_client.record_challenger_evaluation", _fail_if_called)

    result = ce.evaluate_active_challenger("xgboost_v1", "all")
    assert result is None


def test_persists_candidate_for_promotion_verdict(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-1"},
    )
    monkeypatch.setattr("shadow_testing.evaluate_experiment", lambda **kw: _full_candidate_result())

    captured = {}
    monkeypatch.setattr(
        "supabase_client.record_challenger_evaluation",
        lambda **kw: captured.update(kw) or True,
    )

    result = ce.evaluate_active_challenger("xgboost_v1", "all")

    assert result["status"] == "candidate_for_promotion"
    assert captured["training_run_id"] == "run-1"
    assert captured["algorithm_family"] == "xgboost_v1"
    assert captured["league_scope"] == "all"
    assert captured["n_matches_evaluated"] == 250
    assert captured["verdict"] == "candidate_for_promotion"
    assert captured["delta_brier"] == -0.07
    assert captured["brier_significant"] is True


def test_persists_insufficient_data_verdict_with_minimal_fields(monkeypatch):
    """evaluate_experiment intoarce un dict minimal pt insufficient_data —
    verifica ca lipsa celorlalte chei nu cauzeaza eroare (folosite cu
    .get(..., None))."""
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-1"},
    )
    monkeypatch.setattr(
        "shadow_testing.evaluate_experiment",
        lambda **kw: {"status": "insufficient_data", "n_matches_evaluated": 12},
    )

    captured = {}
    monkeypatch.setattr(
        "supabase_client.record_challenger_evaluation",
        lambda **kw: captured.update(kw) or True,
    )

    result = ce.evaluate_active_challenger("xgboost_v1", "all", statistical_method="paired_bootstrap")

    assert result["status"] == "insufficient_data"
    assert captured["verdict"] == "insufficient_data"
    assert captured["n_matches_evaluated"] == 12
    assert captured["statistical_method"] == "paired_bootstrap"
    assert captured["brier_baseline"] is None
    assert captured["evaluation_window_start"] is None


def test_unknown_verdict_not_persisted(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-1"},
    )
    monkeypatch.setattr(
        "shadow_testing.evaluate_experiment",
        lambda **kw: {"status": "some_future_status_not_yet_known", "n_matches_evaluated": 300},
    )

    def _fail_if_called(**kw):
        raise AssertionError("un verdict necunoscut nu trebuie persistat")

    monkeypatch.setattr("supabase_client.record_challenger_evaluation", _fail_if_called)

    result = ce.evaluate_active_challenger("xgboost_v1", "all")
    assert result["status"] == "some_future_status_not_yet_known"


def test_exceptions_are_swallowed_not_propagated(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare simulata")

    monkeypatch.setattr("learning_core.challenger_manager.get_active_challenger", _boom)

    result = ce.evaluate_active_challenger("xgboost_v1", "all")
    assert result is None


# ── Imuabilitate end-to-end, prin supabase_client real (Supabase fabricat) ──

class _FakeEvalTable:
    def __init__(self, rows: dict):
        self._rows = rows  # cheie: (training_run_id, n_matches_evaluated)
        self._payload = None
        self._on_conflict = None
        self._ignore_duplicates = None

    def upsert(self, payload, on_conflict="", ignore_duplicates=False):
        self._payload = payload
        self._on_conflict = on_conflict
        self._ignore_duplicates = ignore_duplicates
        return self

    def execute(self):
        key = (self._payload["training_run_id"], self._payload["n_matches_evaluated"])
        if key in self._rows:
            if self._ignore_duplicates:
                # ON CONFLICT DO NOTHING — randul existent NU se schimba
                return _Result([self._rows[key]])
            self._rows[key] = dict(self._payload)
            return _Result([self._rows[key]])
        self._rows[key] = dict(self._payload)
        return _Result([self._rows[key]])


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeClient:
    def __init__(self):
        self.rows: dict = {}

    def table(self, name):
        assert name == "challenger_evaluations"
        return _FakeEvalTable(self.rows)


def test_immutability_second_write_with_same_window_is_a_noop(monkeypatch):
    """Testul central cerut de Chief Architect Review: o a doua rulare a
    job-ului de evaluare, cu ACEEASI fereastra (acelasi n_matches_evaluated),
    NU trebuie sa schimbe verdictul deja persistat — chiar daca (simuland
    un bug/o schimbare accidentala) rezultatul recalculat ar fi diferit."""
    fake_client = _FakeClient()
    monkeypatch.setattr("supabase_client.get_client", lambda: fake_client)

    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-1"},
    )

    first_result = _full_candidate_result(n=250)
    monkeypatch.setattr("shadow_testing.evaluate_experiment", lambda **kw: first_result)

    ce.evaluate_active_challenger("xgboost_v1", "all")

    key = ("run-1", 250)
    assert fake_client.rows[key]["verdict"] == "candidate_for_promotion"
    assert fake_client.rows[key]["delta_brier"] == -0.07

    # Simuleaza o rerulare a job-ului, cu ACEEASI fereastra (n=250), dar cu
    # un rezultat DIFERIT (ex. un bug in statistica ar fi produs alt verdict) --
    # imuabilitatea trebuie sa impiedice scrierea lui.
    second_result = dict(first_result)
    second_result["status"] = "rejected"
    second_result["delta_brier"] = 0.12
    monkeypatch.setattr("shadow_testing.evaluate_experiment", lambda **kw: second_result)

    ce.evaluate_active_challenger("xgboost_v1", "all")

    assert fake_client.rows[key]["verdict"] == "candidate_for_promotion", \
        "verdictul original nu trebuie schimbat de o rerulare cu aceeasi fereastra"
    assert fake_client.rows[key]["delta_brier"] == -0.07
    assert len(fake_client.rows) == 1, "nu trebuie sa apara un rand nou pt aceeasi fereastra"


def test_new_evaluation_window_produces_new_row(monkeypatch):
    """O fereastra NOUA (mai multe meciuri acumulate) produce un rand NOU,
    distinct -- un fapt nou, nu o corectie a celui vechi."""
    fake_client = _FakeClient()
    monkeypatch.setattr("supabase_client.get_client", lambda: fake_client)

    monkeypatch.setattr(
        "learning_core.challenger_manager.get_active_challenger",
        lambda family, scope: {"training_run_id": "run-1"},
    )

    monkeypatch.setattr("shadow_testing.evaluate_experiment", lambda **kw: _full_candidate_result(n=250))
    ce.evaluate_active_challenger("xgboost_v1", "all")

    monkeypatch.setattr("shadow_testing.evaluate_experiment", lambda **kw: _full_candidate_result(n=400))
    ce.evaluate_active_challenger("xgboost_v1", "all")

    assert len(fake_client.rows) == 2
    assert ("run-1", 250) in fake_client.rows
    assert ("run-1", 400) in fake_client.rows


# ── Izolare de modul ─────────────────────────────────────────────────────────

def test_module_has_zero_importers_outside_own_test():
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if ".git" in path.parts:
            continue
        if path.name in ("challenger_evaluation.py", "test_challenger_evaluation.py"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[-1] == "challenger_evaluation" for alias in node.names):
                    offenders.append(str(path.relative_to(root)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[-1] == "challenger_evaluation" or any(
                    alias.name == "challenger_evaluation" for alias in node.names
                ):
                    offenders.append(str(path.relative_to(root)))

    assert offenders == [], f"challenger_evaluation e importat in afara scopului Pasului 4: {offenders}"
