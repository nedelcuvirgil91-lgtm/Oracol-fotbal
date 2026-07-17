"""
Teste pentru learning_core.promotion_service — Pasul 5, ADR-019. Fără
rețea — toate dependențele (challenger_manager, supabase_client,
model_artifact_storage) sunt monkeypatch-uite.

Cerințele centrale de validat (contractele înghețate, Pasul 4.5):
  1. Promotion execută, nu decide — zero import shadow_testing, zero
     recalculare de statistici.
  2. Fail-fast: la prima precondiție eșuată, ZERO apel RPC (zero scriere).
  3. Idempotență: 'already_active' e un rezultat de succes, nu o eroare.
  4. Orice excepție (inclusiv din RPC) se mapează la
     PromotionResult(status="rejected", reason=...), niciodată propagată.
"""
import numpy as np
import pytest

from learning_core import promotion_service as ps


class _FakeModel:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    def predict_proba(self, X):
        if self.should_fail:
            raise RuntimeError("inferenta a esuat")
        return np.array([[0.5, 0.3, 0.2]])


def _valid_challenger(state="SUCCEEDED", family="xgboost_v1", scope="all"):
    return {"training_run_id": "run-1", "algorithm_family": family, "league_scope": scope, "state": state}


def _candidate_verdict():
    return {"training_run_id": "run-1", "verdict": "candidate_for_promotion"}


@pytest.fixture
def happy_path(monkeypatch):
    monkeypatch.setattr("learning_core.challenger_manager.get_challenger", lambda tid: _valid_challenger())
    monkeypatch.setattr("supabase_client.get_latest_challenger_evaluation", lambda tid: _candidate_verdict())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr("supabase_client.rpc_promote_challenger", lambda tid, by: "promoted")


def test_promoted_success_path(happy_path):
    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="chief-architect")
    assert result.status == "promoted"
    assert result.training_run_id == "run-1"
    assert result.reason is None


def test_already_active_is_success_not_error(happy_path, monkeypatch):
    monkeypatch.setattr("supabase_client.rpc_promote_challenger", lambda tid, by: "already_active")
    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="chief-architect")
    assert result.status == "already_active"
    assert result.reason is None


def test_rejected_when_challenger_not_found(monkeypatch):
    monkeypatch.setattr("learning_core.challenger_manager.get_challenger", lambda tid: None)

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe fara Challenger")

    monkeypatch.setattr("supabase_client.rpc_promote_challenger", _fail_if_called)

    result = ps.promote_challenger("run-ghost", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "niciun Challenger" in result.reason


def test_rejected_when_scope_mismatch(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_challenger",
        lambda tid: _valid_challenger(family="xgboost_v1", scope="premier_league"),
    )

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe cu scope gresit")

    monkeypatch.setattr("supabase_client.rpc_promote_challenger", _fail_if_called)

    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "aparține de" in result.reason


def test_rejected_when_not_succeeded(monkeypatch):
    monkeypatch.setattr(
        "learning_core.challenger_manager.get_challenger",
        lambda tid: _valid_challenger(state="EVALUATING"),
    )

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe fara SUCCEEDED")

    monkeypatch.setattr("supabase_client.rpc_promote_challenger", _fail_if_called)

    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "SUCCEEDED" in result.reason


def test_rejected_when_no_verdict_recorded(monkeypatch):
    monkeypatch.setattr("learning_core.challenger_manager.get_challenger", lambda tid: _valid_challenger())
    monkeypatch.setattr("supabase_client.get_latest_challenger_evaluation", lambda tid: None)

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe fara verdict")

    monkeypatch.setattr("supabase_client.rpc_promote_challenger", _fail_if_called)

    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "candidate_for_promotion" in result.reason


def test_rejected_when_verdict_is_not_candidate(monkeypatch):
    monkeypatch.setattr("learning_core.challenger_manager.get_challenger", lambda tid: _valid_challenger())
    monkeypatch.setattr(
        "supabase_client.get_latest_challenger_evaluation",
        lambda tid: {"training_run_id": "run-1", "verdict": "monitoring"},
    )

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe cu verdict 'monitoring'")

    monkeypatch.setattr("supabase_client.rpc_promote_challenger", _fail_if_called)

    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "monitoring" in result.reason


def test_rejected_when_artifact_missing(monkeypatch):
    monkeypatch.setattr("learning_core.challenger_manager.get_challenger", lambda tid: _valid_challenger())
    monkeypatch.setattr("supabase_client.get_latest_challenger_evaluation", lambda tid: _candidate_verdict())
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: None)

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe fara artefact")

    monkeypatch.setattr("supabase_client.rpc_promote_challenger", _fail_if_called)

    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "artefact" in result.reason


def test_rejected_when_artifact_inference_fails(monkeypatch):
    monkeypatch.setattr("learning_core.challenger_manager.get_challenger", lambda tid: _valid_challenger())
    monkeypatch.setattr("supabase_client.get_latest_challenger_evaluation", lambda tid: _candidate_verdict())
    monkeypatch.setattr(
        "learning_core.model_artifact_storage.load_model_artifact",
        lambda tid: _FakeModel(should_fail=True),
    )

    def _fail_if_called(*a, **kw):
        raise AssertionError("nu trebuie sa mearga mai departe cu artefact defect")

    monkeypatch.setattr("supabase_client.rpc_promote_challenger", _fail_if_called)

    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "predicții valide" in result.reason


def test_rpc_exception_mapped_to_rejected(happy_path, monkeypatch):
    def _boom(tid, by):
        raise RuntimeError("promote_challenger: Challenger run-1 nu este in starea SUCCEEDED")

    monkeypatch.setattr("supabase_client.rpc_promote_challenger", _boom)

    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "SUCCEEDED" in result.reason


def test_unexpected_top_level_exception_never_propagates(monkeypatch):
    def _boom(tid):
        raise RuntimeError("eroare complet neasteptata")

    monkeypatch.setattr("learning_core.challenger_manager.get_challenger", _boom)

    result = ps.promote_challenger("run-1", "xgboost_v1", "all", promoted_by="x")
    assert result.status == "rejected"
    assert "eroare complet neasteptata" in result.reason


# ── Invariant: Promotion execută, nu decide ─────────────────────────────────

def test_module_does_not_import_shadow_testing():
    import ast
    import pathlib

    tree = ast.parse(
        pathlib.Path(ps.__file__).read_text(encoding="utf-8"), filename=ps.__file__,
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[-1] == "shadow_testing" for a in node.names), \
                "promotion_service.py nu are voie sa importe shadow_testing — Promotion executa, nu decide"
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[-1] != "shadow_testing", \
                "promotion_service.py nu are voie sa importe shadow_testing — Promotion executa, nu decide"


# ── Izolare de modul ─────────────────────────────────────────────────────────

def test_module_has_only_known_importers():
    """La închiderea Pasului 5 (ADR-019), acest modul avea ZERO importatori
    de producție ("apelat exclusiv manual (CLI/UI viitoare, nescrise
    încă)"). ADR-030 (Continuous Learning) adaugă
    learning_core/continuous_learning.py ca primul apelant real legitim —
    Faza C (execuția promovărilor deja aprobate de om). Garda rămâne utilă
    sub formă de whitelist explicit."""
    import ast
    import pathlib

    SKIP = {"promotion_service.py", "test_promotion_service.py", "continuous_learning.py"}

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if ".git" in path.parts:
            continue
        if path.name in SKIP:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[-1] == "promotion_service" for alias in node.names):
                    offenders.append(str(path.relative_to(root)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[-1] == "promotion_service" or any(
                    alias.name == "promotion_service" for alias in node.names
                ):
                    offenders.append(str(path.relative_to(root)))

    assert offenders == [], f"promotion_service e importat in afara whitelist-ului cunoscut: {offenders}"
