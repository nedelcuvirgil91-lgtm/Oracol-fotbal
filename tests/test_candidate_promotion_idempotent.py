"""[ADR-084 Etapa 0] Candidatura de promovare e IDEMPOTENTĂ.

DEFECTUL, măsurat pe producție: `ALLOWED_TRANSITIONS["SUCCEEDED"]` e
`{"PROMOTED", "REJECTED"}` — nu se conține pe sine. Iar
`_handle_candidate_for_promotion` începea cu `transition(tid, "SUCCEEDED")` și
trata eșecul ca fatal. Deci A DOUA zi consecutivă în care un Challenger atingea
poarta nu producea NICIO propunere.

S-a întâmplat de 4 ori, pe 3 zile — `automation_runs` 355 (23 aug), 1288 și
1291 (24 oct), 1413 (30 oct). Ultima a costat măsurabil: `dda4f7f3` era 3/3 la
n=378 (Brier, log-loss ȘI acuratețe), iar propunerea de promovare s-a pierdut
tăcut, la două zile de TTL-ul deciziei #13.

Fără rețea, fără Supabase: `ar` (automation_runs) și `challenger_manager` sunt
substituite. Niciun test de aici nu atinge baza.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

import learning_core.continuous_learning as cl

# ── De ce NU importăm `challenger_manager` aici ──────────────────────────────
#
# `tests/test_challenger_manager.py::test_module_has_single_known_importer` e o
# gardă ADR-016: modulul poate fi importat DOAR de cinci module Learning Core
# numite, fiindcă un scriitor necontrolat ar reintroduce problema de ownership
# dublu. Garda scanează tot repo-ul, inclusiv testele, și a prins prima versiune
# a acestui fișier — avea dreptate.
#
# Consecință, deliberată: aici se testează COMPORTAMENTUL handlerului, cu un
# fals care poartă propria lui regulă de tranziție (copie fidelă, mai jos).
# Afirmațiile despre TABELA REALĂ (`ALLOWED_TRANSITIONS` neatinsă, zero
# self-loop-uri) trăiesc în `tests/test_challenger_manager.py`, singurul fișier
# de test căruia garda îi permite importul. Cele două jumătăți se completează:
# acolo se apără regula, aici comportamentul dat regula.


class _EroareFsm(Exception):
    """Ține locul lui `challenger_manager.ChallengerManagerError`.

    Funcționează fiindcă handlerul prinde `challenger_manager.
    ChallengerManagerError`, iar `challenger_manager` e substituit de `_Fsm` —
    deci se resolvă la atributul de clasă de mai jos, nu la modulul real."""


class _Ar:
    """Substituie `automation_runs` — captează, nu scrie."""

    def __init__(self, surface_ok: bool = True):
        self.apeluri: list = []
        self.evidence_propusa: dict | None = None
        self._surface_ok = surface_ok
        self._next = 100

    def write_run(self, producer, process_type, tier, target_key=None):
        self.apeluri.append(("write_run", process_type, target_key))
        self._next += 1
        return self._next

    def start_run(self, run_id):
        self.apeluri.append(("start_run", run_id)); return True

    def complete_run(self, run_id, summary=None):
        self.apeluri.append(("complete_run", run_id, summary)); return True

    def fail_run(self, run_id, error_detail):
        self.apeluri.append(("fail_run", run_id, error_detail)); return True

    def propose_decision(self, decision_run_id, **kwargs):
        self.apeluri.append(("propose_decision", decision_run_id))
        self.evidence_propusa = kwargs.get("evidence")
        return 777

    def surface_decision(self, decision_id):
        self.apeluri.append(("surface_decision", decision_id))
        return self._surface_ok

    # ── interogări de comoditate ───────────────────────────────────────────
    def felurile(self) -> list[str]:
        return [a[0] for a in self.apeluri]

    def s_a_propus(self) -> bool:
        return "propose_decision" in self.felurile()

    def a_eșuat(self) -> bool:
        return "fail_run" in self.felurile()


class _Fsm:
    """Substituie `challenger_manager`, păstrând regula reală de tranziție.

    `ALLOWED_TRANSITIONS` e o COPIE a tabelei reale din
    `learning_core/challenger_manager.py` — nu o importăm, vezi explicația de
    sus. Dacă tabela reală se schimbă, copia asta NU o urmează; divergența e
    prinsă de gărzile din `tests/test_challenger_manager.py`, care citesc
    originalul. Separarea e deliberată, nu o scăpare."""

    ChallengerManagerError = _EroareFsm
    ALLOWED_TRANSITIONS = {
        "CREATED": {"WAITING", "REJECTED"},
        "WAITING": {"EVALUATING", "REJECTED"},
        "EVALUATING": {"SUCCEEDED", "REJECTED"},
        "SUCCEEDED": {"PROMOTED", "REJECTED"},
        "PROMOTED": set(),
        "REJECTED": set(),
    }

    def __init__(self, stare_in_baza: str):
        self.stare_in_baza = stare_in_baza
        self.tranzitii: list = []

    def transition(self, training_run_id, to_state, rejection_reason=None):
        self.tranzitii.append((training_run_id, to_state))
        permise = self.ALLOWED_TRANSITIONS[self.stare_in_baza]
        if to_state not in permise:
            raise self.ChallengerManagerError(
                f"tranziție invalidă: {self.stare_in_baza} -> {to_state} "
                f"(permise din {self.stare_in_baza}: {sorted(permise) or 'nimic'})"
            )
        self.stare_in_baza = to_state
        return {"training_run_id": training_run_id, "state": to_state}


_REZULTAT = {
    "status": "candidate_for_promotion", "n_matches_evaluated": 378,
    "delta_brier": -0.021, "brier_significant": True,
    "delta_logloss": -0.0313, "logloss_significant": True,
    "delta_accuracy": 0.0556, "accuracy_significant": True,
}


def _ruleaza(monkeypatch, stare_in_baza: str, stare_pasata, surface_ok=True):
    ar = _Ar(surface_ok=surface_ok)
    fsm = _Fsm(stare_in_baza)
    monkeypatch.setattr(cl, "ar", ar)
    monkeypatch.setattr(cl, "challenger_manager", fsm)
    summary = {"proposed": 0}
    cl._handle_candidate_for_promotion(
        1, "dda4f7f3", "xgboost_v1|all", dict(_REZULTAT), summary,
        stare_curenta=stare_pasata,
    )
    return ar, fsm, summary


# ── Defectul, ca regresie ───────────────────────────────────────────────────

def test_REGRESIE_deja_SUCCEEDED_propune_si_NU_mai_tranzitioneaza(monkeypatch):
    """Cazul care a eșuat de 4 ori în producție."""
    ar, fsm, summary = _ruleaza(monkeypatch, "SUCCEEDED", "SUCCEEDED")
    assert fsm.tranzitii == [], "tranziția no-op nu trebuie nici încercată"
    assert not ar.a_eșuat(), f"fail_run apelat degeaba: {ar.apeluri}"
    assert ar.s_a_propus(), "propunerea de promovare s-a pierdut — exact defectul"
    assert summary["proposed"] == 1


def test_din_EVALUATING_comportamentul_ramane_cel_de_dinainte(monkeypatch):
    ar, fsm, summary = _ruleaza(monkeypatch, "EVALUATING", "EVALUATING")
    assert fsm.tranzitii == [("dda4f7f3", "SUCCEEDED")]
    assert fsm.stare_in_baza == "SUCCEEDED"
    assert ar.s_a_propus() and not ar.a_eșuat()
    assert summary["proposed"] == 1


def test_stare_None_incearca_tranzitia_compatibil_in_urma(monkeypatch):
    """Apelanții care nu pasează starea nu se schimbă."""
    ar, fsm, summary = _ruleaza(monkeypatch, "EVALUATING", None)
    assert fsm.tranzitii == [("dda4f7f3", "SUCCEEDED")]
    assert ar.s_a_propus()


# ── Ramura defensivă: stări terminale ───────────────────────────────────────
#
# NOTĂ de acoperire, scrisă ca să nu pară mai mult decât e: apelantul unic ia
# starea din `get_active_challenger`, care filtrează
# `.not_.in_("state", ["PROMOTED","REJECTED"])`. Deci prin calea reală garda nu
# vede NICIODATĂ o stare terminală. Testele de mai jos apără comportamentul
# pentru un apelant viitor sau o tranziție concurentă — nu un caz de producție.

@pytest.mark.parametrize("terminala", ["REJECTED", "PROMOTED"])
def test_stare_terminala_esueaza_ZGOMOTOS_si_NU_propune(monkeypatch, terminala):
    ar, fsm, summary = _ruleaza(monkeypatch, terminala, terminala)
    assert fsm.tranzitii == [("dda4f7f3", "SUCCEEDED")], "trebuie încercată, ca să eșueze"
    assert ar.a_eșuat(), "eșecul nu are voie să fie înghițit"
    assert not ar.s_a_propus(), "nu se propune nimic după o tranziție invalidă"
    assert summary["proposed"] == 0


# ── Proprietăți care nu au voie să se piardă ────────────────────────────────

def test_evidence_poarta_decision_kind_promotion(monkeypatch):
    """ADR-079 §4.3 — felul se scrie EXPLICIT, altfel ecranul arată
    „FEL NECUNOSCUT" pentru felul cu consecința cea mai mare."""
    ar, _, _ = _ruleaza(monkeypatch, "SUCCEEDED", "SUCCEEDED")
    assert ar.evidence_propusa is not None
    assert ar.evidence_propusa.get("decision_kind") == "promotion"
    assert ar.evidence_propusa.get("training_run_id") == "dda4f7f3"


def test_contorul_creste_doar_daca_surface_decision_reuseste(monkeypatch):
    """ADR-079 §4.4a — contorul raporta propuneri care nu s-au făcut."""
    _, _, summary = _ruleaza(monkeypatch, "SUCCEEDED", "SUCCEEDED", surface_ok=False)
    assert summary["proposed"] == 0


# ── Ce am decis să NU facem ─────────────────────────────────────────────────
#
# Afirmațiile despre tabela REALĂ — `ALLOWED_TRANSITIONS["SUCCEEDED"]` neatinsă
# și zero self-loop-uri — sunt în `tests/test_challenger_manager.py`
# (`test_ADR084_tabela_FSM_neatinsa_si_fara_self_loop`), fiindcă doar acolo
# garda ADR-016 permite importul modulului. Aici se verifică doar că falsul
# nostru reflectă aceeași regulă:

def test_falsul_reflecta_regula_pe_care_o_judeca():
    """Contrapondere: dacă falsul ar permite `SUCCEEDED -> SUCCEEDED`, testele
    de mai sus ar trece fără să dovedească nimic — exact clasa „un test care nu
    poate distinge ramurile pe care le judecă"."""
    assert "SUCCEEDED" not in _Fsm.ALLOWED_TRANSITIONS["SUCCEEDED"]
    fsm = _Fsm("SUCCEEDED")
    with pytest.raises(_EroareFsm):
        fsm.transition("x", "SUCCEEDED")


# ── Firul dintre cele două capete ───────────────────────────────────────────

def test_apelantul_PASEAZA_starea_citita_deja():
    """Lecția „verifici cele două capete și nu firul dintre ele" (M5/M16/M1):
    garda poate fi corectă, iar apelantul să n-o alimenteze. AST, nu text —
    comentariul de lângă apel conține chiar numele parametrului."""
    sursa = pathlib.Path(inspect.getfile(cl)).read_text(encoding="utf-8")
    arbore = ast.parse(sursa)

    apeluri = [
        n for n in ast.walk(arbore)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_handle_candidate_for_promotion"
    ]
    assert len(apeluri) == 1, f"se așteaptă exact un apelant, găsite {len(apeluri)}"

    chei = {kw.arg for kw in apeluri[0].keywords}
    assert "stare_curenta" in chei, (
        "apelantul nu pasează `stare_curenta` — garda devine inertă, iar "
        "defectul revine în forma în care a stat 4 rulări"
    )


def test_handlerul_accepta_parametrul_cu_implicit_None():
    semnatura = inspect.signature(cl._handle_candidate_for_promotion)
    p = semnatura.parameters.get("stare_curenta")
    assert p is not None, "parametrul lipsește din semnătură"
    assert p.default is None, "implicitul trebuie None — compatibilitate în urmă"
