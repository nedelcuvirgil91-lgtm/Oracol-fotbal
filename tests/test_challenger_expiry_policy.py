"""Politica de expirare pentru Challenger-ul blocat în `monitoring` (ADR-057).

CONTEXT, măsurat live (2026-09-06): `monitoring` nu e stare terminală și nu
expiră de la sine. Prin invariantul „cel mult un Challenger activ" (ADR-016 §4),
un Challenger rămas acolo blochează Faza B — antrenarea nouă — la nesfârșit.
Cazul real: zero antrenări între 24 august și 6 septembrie, cu 470 de meciuri
terminate noi acumulate (prag de antrenare: 30). Campionul care servea era
antrenat pe 4 august.

Vocabularul exista deja (`expired` e valid în
`challenger_manager.VALID_REJECTION_REASONS` ȘI în constrângerea `CHECK` din
Postgres); lipsea declanșatorul. ADR-057 a fost scris pe 17 august, a rămas
PROPUS, și nu era referit de niciun alt document sau cod — motiv pentru care
starea a fost descoperită abia după 14 zile.

CE APĂRĂ ACESTE TESTE, în ordinea importanței:
  1. Politica nu expiră NIMIC automat — produce o propunere, omul decide
     (Opțiunea B din ADR-057 §4, aleasă tocmai fiindcă politica e generică și
     va propune expirarea și pentru un Challenger care merită păstrat).
  2. Flagul e implicit OPRIT (North Star #3).
  3. Ținta e ÎNGHEȚATĂ la propunere — între propunere și aprobare pot trece 7
     zile, iar slotul poate fi ocupat între timp de alt Challenger.
  4. Criteriile de promovare rămân absolut neatinse.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import learning_core.continuous_learning as cl
from learning_core import model_registry
from learning_core.model_registry import TrainingRunResult
from tests.test_continuous_learning import _CallRecorder  # noqa: F401  (client fals deja probat)

import pytest

TARGET = "fake_algo|Premier League"


class _Algoritm:
    name = "fake_algo"
    version = "1"
    league_scope = "Premier League"

    def fit(self, training_data):
        return TrainingRunResult(training_run_id="tr_x", status="trained", samples_used=250)

    def predict(self, features):
        return (0.4, 0.3, 0.3, {})

    def describe(self):
        return {}

    def get_trained_model(self):
        return "model"

    def get_calibration_temperature(self):
        return 1.0


@pytest.fixture(autouse=True)
def registru_curat():
    model_registry._clear_registry_for_tests()
    model_registry.register(_Algoritm())
    yield
    model_registry._clear_registry_for_tests()


@pytest.fixture()
def rec(monkeypatch):
    recorder = _CallRecorder()
    monkeypatch.setattr(cl, "ar", recorder)
    return recorder


def _config(monkeypatch, **chei):
    valori = {"learning_core_enabled": True, **chei}
    monkeypatch.setattr(cl.sb, "load_config", lambda default: dict(valori))


def _challenger_in_monitoring(monkeypatch, n: int, training_run_id: str = "tr_blocat"):
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda f, l: 1)
    monkeypatch.setattr(
        cl.challenger_evaluation, "evaluate_active_challenger",
        lambda family, league, min_matches=200: {
            "status": "monitoring", "n_matches_evaluated": n,
            "delta_brier": -0.011, "brier_significant": False,
        },
    )
    monkeypatch.setattr(cl.challenger_manager, "get_active_challenger",
                        lambda f, l: {"training_run_id": training_run_id})
    tranzitii: list = []
    monkeypatch.setattr(cl.challenger_manager, "transition",
                        lambda tid, to_state, rejection_reason=None:
                            tranzitii.append((tid, to_state, rejection_reason)))
    return tranzitii


def _propuneri(rec) -> list:
    return [c for c in rec.calls if c[0] == "propose_decision"]


# ════════════════════════════════════════════════════════════════════════
# Flagul — implicit oprit
# ════════════════════════════════════════════════════════════════════════

def test_flagul_e_oprit_cand_cheia_lipseste_din_config(monkeypatch):
    """North Star #3: niciun flag nou nu pornește implicit activ. Un merge pe
    `main` nu trebuie să activeze politica."""
    monkeypatch.setattr(cl.sb, "load_config", lambda default: dict(default))
    assert cl.is_challenger_expiry_proposals_enabled() is False


def test_flagul_e_pornit_doar_cand_e_setat_explicit(monkeypatch):
    monkeypatch.setattr(cl.sb, "load_config",
                        lambda default: {"challenger_expiry_proposals_enabled": True})
    assert cl.is_challenger_expiry_proposals_enabled() is True


def test_flagul_de_expirare_e_independent_de_learning_core(monkeypatch):
    """Flag DEDICAT: `learning_core_enabled` pornit nu implică politica pornită."""
    monkeypatch.setattr(cl.sb, "load_config", lambda default: {"learning_core_enabled": True})
    assert cl.is_challenger_expiry_proposals_enabled() is False


# ════════════════════════════════════════════════════════════════════════
# Faza A — când se propune și când NU
# ════════════════════════════════════════════════════════════════════════

def test_sub_prag_nu_se_propune_nimic(rec, monkeypatch):
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    tranzitii = _challenger_in_monitoring(monkeypatch, n=cl.MIN_MATCHES_FOR_EXPIRY - 1)

    rezultat = cl.run_cycle()

    assert rezultat["expiry_proposed"] == 0
    assert _propuneri(rec) == []
    assert tranzitii == []


def test_prag_atins_dar_flag_oprit_nu_propune_dar_CONSEMNEAZA(rec, monkeypatch):
    """Starea pe care ADR-057 §8 o descria drept „blocaj fără nicio alertă"
    devine un fapt vizibil în `automation_runs`, nu tăcere."""
    _config(monkeypatch)  # flagul lipsește => oprit
    tranzitii = _challenger_in_monitoring(monkeypatch, n=cl.MIN_MATCHES_FOR_EXPIRY + 50)

    rezultat = cl.run_cycle()

    assert rezultat["expiry_proposed"] == 0
    assert _propuneri(rec) == []
    assert tranzitii == []

    rezumate = [c[2] for c in rec.calls if c[0] == "complete_run" and c[2]]
    marcate = [s for s in rezumate if s.get("expiry_threshold_reached")]
    assert marcate, "pragul atins cu flagul oprit trebuie consemnat, nu trecut sub tăcere"
    assert marcate[0]["expiry_proposals_enabled"] is False


def test_prag_atins_cu_flag_pornit_propune_decizie_T3a(rec, monkeypatch):
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    tranzitii = _challenger_in_monitoring(monkeypatch, n=506, training_run_id="tr_blocat")

    rezultat = cl.run_cycle()

    assert rezultat["expiry_proposed"] == 1
    propuneri = _propuneri(rec)
    assert len(propuneri) == 1
    _, _, tier, rollback_plan, evidence, correction_method = propuneri[0]
    assert tier == "T3a"
    assert rollback_plan, "T3a fără rollback_plan încalcă precondiția structurală"
    assert evidence["decision_kind"] == "expiry"
    assert evidence["training_run_id"] == "tr_blocat", "ținta trebuie înghețată în evidence"
    assert evidence["n_matches_evaluated"] == 506
    assert evidence["min_matches_for_expiry"] == cl.MIN_MATCHES_FOR_EXPIRY
    assert correction_method == "none — pre-ADR-034"

    assert tranzitii == [], (
        "GARDA CENTRALĂ: propunerea NU are voie să tranziționeze FSM-ul. "
        "Expirarea se execută abia după aprobare umană, în Faza C."
    )
    assert ("surface_decision", 1) in rec.calls, "decizia trebuie să apară în feed"


def test_propunerea_de_expirare_apare_pe_un_process_type_propriu(rec, monkeypatch):
    """Ca să se poată distinge în `automation_runs` de o propunere de promovare
    sau de rollback, fără să te uiți în evidence."""
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    _challenger_in_monitoring(monkeypatch, n=400)

    cl.run_cycle()

    tipuri = [c[2] for c in rec.calls if c[0] == "write_run"]
    assert "challenger_expiry_candidate" in tipuri


def test_promovarea_are_prioritate_asupra_expirarii(rec, monkeypatch):
    """Un Challenger care a devenit candidat nu se expiră, oricât de mare ar fi
    n. Criteriile de promovare rămân neatinse (ADR-057 §1)."""
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda f, l: 1)
    monkeypatch.setattr(
        cl.challenger_evaluation, "evaluate_active_challenger",
        lambda family, league, min_matches=200: {
            "status": "candidate_for_promotion", "n_matches_evaluated": 900,
        },
    )
    monkeypatch.setattr(cl.challenger_manager, "get_active_challenger",
                        lambda f, l: {"training_run_id": "tr_bun"})
    monkeypatch.setattr(cl.challenger_manager, "transition",
                        lambda tid, to_state, rejection_reason=None: None)

    rezultat = cl.run_cycle()

    assert rezultat["proposed"] == 1
    assert rezultat["expiry_proposed"] == 0
    evidence = _propuneri(rec)[0][4]
    assert evidence.get("decision_kind") != "expiry"


def test_verdictul_respins_nu_produce_propunere_de_expirare(rec, monkeypatch):
    """`rejected` închide Challenger-ul singur — nu mai are ce expira."""
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda f, l: 1)
    monkeypatch.setattr(
        cl.challenger_evaluation, "evaluate_active_challenger",
        lambda family, league, min_matches=200: {
            "status": "rejected", "n_matches_evaluated": 900,
        },
    )
    monkeypatch.setattr(cl.challenger_manager, "get_active_challenger",
                        lambda f, l: {"training_run_id": "tr_slab"})
    monkeypatch.setattr(cl.challenger_manager, "transition",
                        lambda tid, to_state, rejection_reason=None: None)

    rezultat = cl.run_cycle()

    assert rezultat["expiry_proposed"] == 0
    assert _propuneri(rec) == []


def test_insufficient_data_nu_produce_propunere(rec, monkeypatch):
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda f, l: 1)
    monkeypatch.setattr(
        cl.challenger_evaluation, "evaluate_active_challenger",
        lambda family, league, min_matches=200: {
            "status": "insufficient_data", "n_matches_evaluated": 900,
        },
    )
    monkeypatch.setattr(cl.challenger_manager, "get_active_challenger",
                        lambda f, l: {"training_run_id": "tr_x"})

    assert cl.run_cycle()["expiry_proposed"] == 0
    assert _propuneri(rec) == []


# ════════════════════════════════════════════════════════════════════════
# Faza C — execuția, pe ținta ÎNGHEȚATĂ
# ════════════════════════════════════════════════════════════════════════

def _pregateste_faza_c(rec, monkeypatch, decizie: dict, challenger: dict | None):
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda f, l: 0)
    monkeypatch.setattr(cl.sb, "get_latest_challenger", lambda f, l: {"created_at": "x"})
    monkeypatch.setattr(cl, "_count_finished_matches", lambda league, since=None: 0)
    monkeypatch.setattr(cl.challenger_manager, "get_challenger", lambda tid: challenger)
    tranzitii: list = []
    monkeypatch.setattr(cl.challenger_manager, "transition",
                        lambda tid, to_state, rejection_reason=None:
                            tranzitii.append((tid, to_state, rejection_reason)))
    rec.approved_for_target[TARGET] = [decizie]
    return tranzitii


def test_expirarea_aprobata_marcheaza_challengerul_REJECTED_expired(rec, monkeypatch):
    tranzitii = _pregateste_faza_c(
        rec, monkeypatch,
        decizie={"id": 7, "evidence": {"decision_kind": "expiry", "training_run_id": "tr_blocat"}},
        challenger={"training_run_id": "tr_blocat", "state": "EVALUATING"},
    )

    rezultat = cl.run_cycle()

    assert tranzitii == [("tr_blocat", "REJECTED", "expired")]
    assert rezultat["expiry_committed"] == 1
    assert ("commit_decision", 7) in rec.calls


def test_se_expira_TINTA_INGHETATA_nu_challengerul_activ_acum(rec, monkeypatch):
    """GARDA CENTRALĂ a Execution Contract-ului. Între propunere și aprobare pot
    trece 7 zile; dacă slotul e ocupat între timp de alt Challenger, o execuție
    care ar recalcula ținta l-ar expira pe cel greșit."""
    tranzitii = _pregateste_faza_c(
        rec, monkeypatch,
        decizie={"id": 8, "evidence": {"decision_kind": "expiry", "training_run_id": "tr_VECHI"}},
        challenger={"training_run_id": "tr_VECHI", "state": "EVALUATING"},
    )
    monkeypatch.setattr(cl.challenger_manager, "get_active_challenger",
                        lambda f, l: {"training_run_id": "tr_NOU_nevinovat"})

    cl.run_cycle()

    assert tranzitii == [("tr_VECHI", "REJECTED", "expired")]
    assert all(t[0] != "tr_NOU_nevinovat" for t in tranzitii)


def test_tinta_deja_terminala_se_inchide_ca_no_op_idempotent(rec, monkeypatch):
    """Intenția e deja îndeplinită — slotul e liber. Nu se raportează eșec
    pentru ceva ce nu mai are ce să eșueze, și nu se re-tranziționează."""
    tranzitii = _pregateste_faza_c(
        rec, monkeypatch,
        decizie={"id": 9, "evidence": {"decision_kind": "expiry", "training_run_id": "tr_promovat"}},
        challenger={"training_run_id": "tr_promovat", "state": "PROMOTED"},
    )

    rezultat = cl.run_cycle()

    assert tranzitii == [], "un Challenger terminal nu se mai tranzitionează"
    assert rezultat["expiry_committed"] == 1
    assert ("commit_decision", 9) in rec.calls
    assert not [c for c in rec.calls if c[0] == "fail_decision_commit"]


def test_tinta_disparuta_e_esec_explicit_nu_no_op(rec, monkeypatch):
    tranzitii = _pregateste_faza_c(
        rec, monkeypatch,
        decizie={"id": 10, "evidence": {"decision_kind": "expiry", "training_run_id": "tr_fantoma"}},
        challenger=None,
    )

    rezultat = cl.run_cycle()

    assert tranzitii == []
    assert rezultat["expiry_committed"] == 0
    esecuri = [c for c in rec.calls if c[0] == "fail_decision_commit"]
    assert len(esecuri) == 1 and esecuri[0][1] == 10


def test_evidence_fara_tinta_e_refuzata(rec, monkeypatch):
    tranzitii = _pregateste_faza_c(
        rec, monkeypatch,
        decizie={"id": 11, "evidence": {"decision_kind": "expiry"}},
        challenger={"training_run_id": "x", "state": "EVALUATING"},
    )

    cl.run_cycle()

    assert tranzitii == []
    esecuri = [c for c in rec.calls if c[0] == "fail_decision_commit"]
    assert len(esecuri) == 1 and esecuri[0][1] == 11


def test_esecul_tranzitiei_nu_se_raporteaza_ca_succes(rec, monkeypatch):
    _pregateste_faza_c(
        rec, monkeypatch,
        decizie={"id": 12, "evidence": {"decision_kind": "expiry", "training_run_id": "tr_x"}},
        challenger={"training_run_id": "tr_x", "state": "EVALUATING"},
    )

    def _explodeaza(tid, to_state, rejection_reason=None):
        raise cl.challenger_manager.ChallengerManagerError("FSM refuza tranzitia")

    monkeypatch.setattr(cl.challenger_manager, "transition", _explodeaza)

    rezultat = cl.run_cycle()

    assert rezultat["expiry_committed"] == 0
    assert [c for c in rec.calls if c[0] == "fail_decision_commit"]
    assert ("commit_decision", 12) not in rec.calls


# ── contraponderi: celelalte două tipuri de decizie rămân neatinse ──────────

def test_decizia_de_promovare_nu_ajunge_pe_calea_de_expirare(rec, monkeypatch):
    """Regresie: `decision_kind` absent înseamnă promovare (implicit istoric)."""
    tranzitii = _pregateste_faza_c(
        rec, monkeypatch,
        decizie={"id": 13, "evidence": {"training_run_id": "tr_promovabil"}},
        challenger={"training_run_id": "tr_promovabil", "state": "SUCCEEDED"},
    )
    apeluri = []
    monkeypatch.setattr(cl, "promote_challenger",
                        lambda training_run_id, algorithm_family, league_scope, promoted_by:
                            apeluri.append(training_run_id) or type(
                                "R", (), {"status": "promoted", "reason": None})())

    rezultat = cl.run_cycle()

    assert apeluri == ["tr_promovabil"]
    assert tranzitii == [], "promovarea nu trece prin transition() aici"
    assert rezultat["committed"] == 1
    assert rezultat["expiry_committed"] == 0


def test_decizia_de_rollback_nu_ajunge_pe_calea_de_expirare(rec, monkeypatch):
    tranzitii = _pregateste_faza_c(
        rec, monkeypatch,
        decizie={"id": 14, "evidence": {
            "decision_kind": "rollback", "predecessor_training_run_id": "tr_pred",
            "reason": "degradare",
        }},
        challenger={"training_run_id": "tr_pred", "state": "PROMOTED"},
    )
    monkeypatch.setattr(
        cl.rollback_service, "rollback_champion",
        lambda **kw: type("R", (), {"status": "rolled_back", "reason": None})(),
    )

    rezultat = cl.run_cycle()

    assert rezultat["rollback_committed"] == 1
    assert rezultat["expiry_committed"] == 0
    assert tranzitii == []


def test_rezumatul_ciclului_expune_ambii_contori_de_expirare(rec, monkeypatch):
    _config(monkeypatch)
    monkeypatch.setattr(cl.sb, "count_active_challengers", lambda f, l: 0)
    monkeypatch.setattr(cl.sb, "get_latest_challenger", lambda f, l: {"created_at": "x"})
    monkeypatch.setattr(cl, "_count_finished_matches", lambda league, since=None: 0)

    rezultat = cl.run_cycle()

    assert rezultat["expiry_proposed"] == 0
    assert rezultat["expiry_committed"] == 0


# ════════════════════════════════════════════════════════════════════════
# REGRESIE — aprobarea omului nu se anulează la următorul ciclu
#
# Defect real, observat live pe 2026-09-06, între aprobare și execuție.
# `propose_decision()` e idempotentă pe `target_key` și întoarce decizia deja
# DESCHISĂ dacă există — iar `_OPEN_DECISION_STATUSES` include `approved`.
# Producătorul primea înapoi id-ul deciziei aprobate de om, o „surfaca", și o
# dădea în `pending`. Aprobarea dispărea, Faza C nu mai găsea nimic de
# executat, iar la ciclul următor totul se repeta — blocaj perfect tăcut.
#
# Calea de promovare era protejată accidental (tranziția SUCCEEDED eșuează la
# a doua încercare și iese înainte de propunere); calea de expirare nu avea
# nicio astfel de plasă, fiindcă deliberat nu atinge FSM-ul.
# ════════════════════════════════════════════════════════════════════════

def test_nu_se_repropune_cand_o_decizie_aprobata_asteapta_executia(rec, monkeypatch):
    """GARDA CENTRALĂ a regresiei: cu o decizie aprobată în așteptare, ciclul
    nu mai propune nimic — deci nu mai are ce să „surfaceze" înapoi."""
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    _challenger_in_monitoring(monkeypatch, n=506, training_run_id="tr_blocat")
    monkeypatch.setattr(cl.challenger_manager, "get_challenger",
                        lambda tid: {"training_run_id": tid, "state": "EVALUATING"})
    rec.approved_for_target[TARGET] = [
        {"id": 4, "evidence": {"decision_kind": "expiry", "training_run_id": "tr_blocat"}}
    ]

    rezultat = cl.run_cycle()

    assert _propuneri(rec) == [], (
        "o decizie aprobată, neexecutată încă, nu trebuie repropusă — "
        "repropunerea îi rescrie evidence-ul și îi anulează aprobarea"
    )
    assert ("surface_decision", 4) not in rec.calls
    assert rezultat["expiry_proposed"] == 0
    # ...dar execuția merge mai departe în același ciclu:
    assert rezultat["expiry_committed"] == 1


def test_starea_de_asteptare_a_executiei_e_consemnata(rec, monkeypatch):
    _config(monkeypatch, challenger_expiry_proposals_enabled=True)
    _challenger_in_monitoring(monkeypatch, n=506, training_run_id="tr_blocat")
    monkeypatch.setattr(cl.challenger_manager, "get_challenger",
                        lambda tid: {"training_run_id": tid, "state": "EVALUATING"})
    rec.approved_for_target[TARGET] = [
        {"id": 4, "evidence": {"decision_kind": "expiry", "training_run_id": "tr_blocat"}}
    ]

    cl.run_cycle()

    rezumate = [c[2] for c in rec.calls if c[0] == "complete_run" and c[2]]
    marcate = [s for s in rezumate if s.get("expiry_decision_awaiting_execution")]
    assert marcate, "starea aprobat-in-curs-de-executie trebuie sa fie vizibila in jurnal"
