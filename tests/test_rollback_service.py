"""
Teste pentru learning_core.rollback_service (Stage R1.5) — ADR-037. Fără
rețea: toate dependențele (supabase_client, model_artifact_storage) sunt
monkeypatch-uite. Oglindește test_promotion_service.py.

Cerințele centrale de validat (simetric cu Promotion):
  1. Rollback execută, nu decide — zero evaluare de sănătate/statistici.
  2. Fail-fast: la prima precondiție eșuată, ZERO apel RPC (zero scriere), și
     validarea artefactului e sărită dacă nu există predecesor.
  3. CAS: predecesorul validat e trimis ca expected_predecessor la RPC.
  4. Idempotență: 'already_active' e succes, nu eroare.
  5. Orice excepție (inclusiv din RPC) → RollbackResult(status="rejected"),
     niciodată propagată.
"""
import numpy as np
import pytest

from learning_core import rollback_service as rs


class _FakeModel:
    def __init__(self, should_fail: bool = False):
        self.should_fail = should_fail

    def predict_proba(self, X):
        if self.should_fail:
            raise RuntimeError("inferenta a esuat")
        return np.array([[0.5, 0.3, 0.2]])


def _fail_if_called(*a, **kw):
    raise AssertionError("nu trebuie sa se ajunga aici — fail-fast incalcat")


@pytest.fixture
def happy_path(monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_predecessor", lambda fam, scope: "pred-1")
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: _FakeModel())
    monkeypatch.setattr("supabase_client.rpc_rollback_champion", lambda fam, scope, exp, reason, by: "rolled_back")


# ── Căi de succes ───────────────────────────────────────────────────────────

def test_rolled_back_success_path(happy_path):
    result = rs.rollback_champion("xgboost_v1", "all", reason="operator", rolled_back_by="chief")
    assert result.status == "rolled_back"
    assert result.predecessor_training_run_id == "pred-1"
    assert result.reason is None


def test_already_active_is_success_not_error(happy_path, monkeypatch):
    monkeypatch.setattr("supabase_client.rpc_rollback_champion",
                        lambda fam, scope, exp, reason, by: "already_active")
    result = rs.rollback_champion("xgboost_v1", "all", reason="operator", rolled_back_by="chief")
    assert result.status == "already_active"
    assert result.reason is None
    assert result.predecessor_training_run_id == "pred-1"


def test_cas_seed_is_the_validated_predecessor(happy_path, monkeypatch):
    """Predecesorul validat în Python e trimis ca expected_predecessor la RPC
    (garanția CAS: artefactul validat = cel activat)."""
    captured = {}

    def _capture(fam, scope, expected_predecessor, reason, by):
        captured["expected_predecessor"] = expected_predecessor
        return "rolled_back"

    monkeypatch.setattr("supabase_client.rpc_rollback_champion", _capture)
    rs.rollback_champion("xgboost_v1", "all", reason="regression", rolled_back_by="guardian")
    assert captured["expected_predecessor"] == "pred-1"


@pytest.mark.parametrize("reason", sorted(rs.VALID_ROLLBACK_REASONS))
def test_all_six_reasons_accepted(happy_path, reason):
    """Toate cele 6 motive trec de validare și ajung la RPC."""
    result = rs.rollback_champion("xgboost_v1", "all", reason=reason, rolled_back_by="x")
    assert result.status == "rolled_back"


# ── Fail-fast: precondiții eșuate, ZERO apel RPC ────────────────────────────

def test_rejected_invalid_reason_before_any_io(monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_predecessor", _fail_if_called)
    monkeypatch.setattr("supabase_client.rpc_rollback_champion", _fail_if_called)
    result = rs.rollback_champion("xgboost_v1", "all", reason="not-a-reason", rolled_back_by="x")
    assert result.status == "rejected"
    assert "motiv invalid" in result.reason


def test_rejected_no_predecessor_skips_artifact_and_rpc(monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_predecessor", lambda fam, scope: None)
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", _fail_if_called)
    monkeypatch.setattr("supabase_client.rpc_rollback_champion", _fail_if_called)
    result = rs.rollback_champion("xgboost_v1", "all", reason="operator", rolled_back_by="x")
    assert result.status == "rejected"
    assert "niciun predecesor" in result.reason
    # F1: mesajul menționează și posibilitatea Supabase indisponibil
    assert "Supabase indisponibil" in result.reason


def test_rejected_when_artifact_missing(monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_predecessor", lambda fam, scope: "pred-1")
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: None)
    monkeypatch.setattr("supabase_client.rpc_rollback_champion", _fail_if_called)
    result = rs.rollback_champion("xgboost_v1", "all", reason="operator", rolled_back_by="x")
    assert result.status == "rejected"
    assert "nu a putut fi încărcat" in result.reason
    assert result.predecessor_training_run_id == "pred-1"


def test_rejected_when_artifact_inference_fails(monkeypatch):
    monkeypatch.setattr("supabase_client.get_champion_predecessor", lambda fam, scope: "pred-1")
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact",
                        lambda tid: _FakeModel(should_fail=True))
    monkeypatch.setattr("supabase_client.rpc_rollback_champion", _fail_if_called)
    result = rs.rollback_champion("xgboost_v1", "all", reason="operator", rolled_back_by="x")
    assert result.status == "rejected"
    assert "nu produce predicții valide" in result.reason


# ── Excepții RPC și neașteptate → rejected, niciodată propagate ─────────────

def test_rpc_predecessor_mismatch_mapped_to_rejected(happy_path, monkeypatch):
    def _boom(fam, scope, exp, reason, by):
        raise RuntimeError("rollback_champion: predecessor_mismatch — asteptat X, gasit Y")

    monkeypatch.setattr("supabase_client.rpc_rollback_champion", _boom)
    result = rs.rollback_champion("xgboost_v1", "all", reason="operator", rolled_back_by="x")
    assert result.status == "rejected"
    assert "predecessor_mismatch" in result.reason
    assert result.predecessor_training_run_id == "pred-1"


def test_unexpected_rpc_status_rejected(happy_path, monkeypatch):
    monkeypatch.setattr("supabase_client.rpc_rollback_champion",
                        lambda fam, scope, exp, reason, by: "ceva_neasteptat")
    result = rs.rollback_champion("xgboost_v1", "all", reason="operator", rolled_back_by="x")
    assert result.status == "rejected"
    assert "răspuns neașteptat" in result.reason


def test_unexpected_top_level_exception_never_propagates(monkeypatch):
    def _boom(fam, scope):
        raise RuntimeError("eroare complet neasteptata")

    monkeypatch.setattr("supabase_client.get_champion_predecessor", _boom)
    result = rs.rollback_champion("xgboost_v1", "all", reason="operator", rolled_back_by="x")
    assert result.status == "rejected"
    assert "eroare complet neasteptata" in result.reason


# ── is_rollback_promoted (Stage R3.2A — singurul loc care interpretează
# formatul promoted_by; consumat de continuous_learning ca gardă anti-ping-pong) ──

def test_is_rollback_promoted_true_on_rollback_format():
    champion = {"training_run_id": "tr_1", "promoted_by": "rollback:regression:ADR-037-continuous-learning"}
    assert rs.is_rollback_promoted(champion) is True


def test_is_rollback_promoted_false_on_normal_promotion():
    champion = {"training_run_id": "tr_1", "promoted_by": "ADR-030-continuous-learning"}
    assert rs.is_rollback_promoted(champion) is False


def test_is_rollback_promoted_false_on_none_champion():
    assert rs.is_rollback_promoted(None) is False


def test_is_rollback_promoted_false_on_missing_promoted_by():
    assert rs.is_rollback_promoted({"training_run_id": "tr_1"}) is False


def test_is_rollback_promoted_false_on_non_string_promoted_by():
    """Regula 'nu se aproximează' — un tip neașteptat (ex. None explicit
    stocat, sau o valoare non-text corupta) nu trebuie să crape, nici să fie
    interpretat implicit ca rollback."""
    assert rs.is_rollback_promoted({"promoted_by": None}) is False
    assert rs.is_rollback_promoted({"promoted_by": 12345}) is False
