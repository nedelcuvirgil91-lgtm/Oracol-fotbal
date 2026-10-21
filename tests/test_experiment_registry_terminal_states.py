"""Stari terminale in `experiment_registry` (ADR-080, 2026-10-21).

GOLUL MASURAT. `shadow_testing` defineste `promote_experiment()` si
`deprecate_experiment()`, dar amandoua aveau ZERO apelanti de productie, iar
in baza nu exista NICIUN rand cu `promoted`/`deprecated`. Calea de promovare
(`promotion_service` -> `model_champions` + FSM) nu anunta niciodata registrul.

Consecinta, pe date reale: `blend_v1/8ac89c70` a ramas
`candidate_for_promotion` doua luni dupa ce devenise campion activ (23 aug),
iar evaluarea nocturna i-a recalculat acelasi verdict pe un set de randuri
INGHETAT din 23 aug 09:23 — cu 13 minute inainte de promovare. `last_evaluated_at`
se improspata in fiecare noapte, deci randul ARATA proaspat.

Forma INVERSATA a capcanei marcajului inghetat reparate pe 26 august: acolo
continutul se improspata si marcajul mintea ca e vechi; aici marcajul minte ca
e proaspat.

CE NU ACOPERA acest fisier, deliberat (ADR-080 §3.2): nu exista nicio garda
care sa sara experimentele „fara randuri noi". Un set inghetat poate produce
in continuare un verdict care se schimba, fiindca rezultatele se rezolva mai
tarziu (`actual_result` se completeaza dupa meci, deci `n_matches_evaluated`
creste). „Niciun rand nou" NU inseamna „verdictul nu se poate schimba".
"""
from __future__ import annotations

import ast
import pathlib

import pytest

import shadow_testing as st
from learning_core import continuous_learning as cl


# ════════════════════════════════════════════════════════════════════════════
# Multimea terminala — contract, nu lista de conveniente
# ════════════════════════════════════════════════════════════════════════════

def test_multimea_terminala_contine_ambele_stari_de_decizie():
    assert st.TERMINAL_REGISTRY_STATUSES == {"promoted", "deprecated"}


@pytest.mark.parametrize("verdict", ["candidate_for_promotion", "monitoring",
                                     "rejected", "insufficient_data"])
def test_niciun_verdict_STATISTIC_nu_e_terminal(verdict):
    """Contraponderea care tine ADR-080 onest: daca un verdict statistic ar
    ajunge terminal, evaluarea ar inceta sa mai atinga experimente VII —
    exact defectul D-10, reintrodus pe alta usa."""
    assert verdict not in st.TERMINAL_REGISTRY_STATUSES


# ════════════════════════════════════════════════════════════════════════════
# `_chei_terminale` — citire, filtrare, si degradare grațioasă
# ════════════════════════════════════════════════════════════════════════════

REGISTRU = [
    {"experiment_name": "blend_v1", "experiment_version": "8ac89c70",
     "league_scope": "all", "status": "promoted"},
    {"experiment_name": "blend_v1", "experiment_version": "174e7e17",
     "league_scope": "all", "status": "monitoring"},
    {"experiment_name": "xgboost_v1", "experiment_version": "e638c1dc",
     "league_scope": "all", "status": "rejected"},
    {"experiment_name": "vechi_v1", "experiment_version": "aaaa1111",
     "league_scope": "all", "status": "deprecated"},
    {"experiment_name": "blend_v1", "experiment_version": "zzzz9999",
     "league_scope": "Premier League", "status": "promoted"},
]


@pytest.fixture
def registru(monkeypatch):
    monkeypatch.setattr(st, "get_experiment_registry", lambda *a, **k: list(REGISTRU))


def test_cheile_terminale_le_prind_pe_ambele(registru):
    assert st._chei_terminale("all") == {("blend_v1", "8ac89c70"),
                                         ("vechi_v1", "aaaa1111")}


def test_verdictele_statistice_NU_ajung_in_multime(registru):
    chei = st._chei_terminale("all")
    assert ("blend_v1", "174e7e17") not in chei
    assert ("xgboost_v1", "e638c1dc") not in chei


def test_alt_league_scope_nu_se_amesteca(registru):
    """Registrul e cheiat pe (nume, versiune, league_scope). Un `promoted` pe
    Premier League nu are voie sa inghete evaluarea pe `all`."""
    assert ("blend_v1", "zzzz9999") not in st._chei_terminale("all")
    assert ("blend_v1", "zzzz9999") in st._chei_terminale("Premier League")


def test_eroarea_de_citire_da_multime_VIDA_nu_partiala(monkeypatch):
    """Un esec de citire NU are voie sa sara tacit experimente vii. Multimea
    vida = exact comportamentul de dinainte de ADR-080: se evalueaza tot."""
    def _explodeaza(*a, **k):
        raise RuntimeError("Supabase picat")

    monkeypatch.setattr(st, "get_experiment_registry", _explodeaza)
    assert st._chei_terminale("all") == set()


def test_registru_gol_da_multime_vida(monkeypatch):
    monkeypatch.setattr(st, "get_experiment_registry", lambda *a, **k: [])
    assert st._chei_terminale("all") == set()


# ════════════════════════════════════════════════════════════════════════════
# Bucla de evaluare — ce se sare si ce NU
# ════════════════════════════════════════════════════════════════════════════

EXPERIMENTE = [("blend_v1", "8ac89c70"), ("blend_v1", "174e7e17"),
               ("xgboost_v1", "e638c1dc"), ("vechi_v1", "aaaa1111")]


@pytest.fixture
def bucla(monkeypatch):
    evaluate = []
    monkeypatch.setattr(st, "get_distinct_experiments", lambda: list(EXPERIMENTE))

    def _fals(name, version, **kwargs):
        evaluate.append((name, version))
        return {"status": "monitoring", "n_matches_evaluated": 7}

    monkeypatch.setattr(st, "evaluate_experiment", _fals)
    return evaluate


def test_randurile_terminale_NU_se_mai_evalueaza(registru, bucla):
    st.evaluate_all_active_experiments()
    assert ("blend_v1", "8ac89c70") not in bucla
    assert ("vechi_v1", "aaaa1111") not in bucla


def test_randurile_VII_se_evalueaza_in_continuare(registru, bucla):
    st.evaluate_all_active_experiments()
    assert ("blend_v1", "174e7e17") in bucla
    assert ("xgboost_v1", "e638c1dc") in bucla


def test_rezultatul_nu_contine_experimentele_sarite(registru, bucla):
    rez = st.evaluate_all_active_experiments()
    nume = {(r["experiment_name"], r["experiment_version"]) for r in rez}
    assert nume == {("blend_v1", "174e7e17"), ("xgboost_v1", "e638c1dc")}


def test_registru_necitibil_inseamna_evalueaza_TOT(monkeypatch, bucla):
    """Contraponderea cea mai importanta: o cadere a registrului nu are voie
    sa opreasca evaluarea — ar fi un D-10 autoprodus."""
    def _explodeaza(*a, **k):
        raise RuntimeError("Supabase picat")

    monkeypatch.setattr(st, "get_experiment_registry", _explodeaza)
    st.evaluate_all_active_experiments()
    assert set(bucla) == set(EXPERIMENTE)


# ════════════════════════════════════════════════════════════════════════════
# Calea de promovare anunta registrul — si NU moare daca registrul moare
# ════════════════════════════════════════════════════════════════════════════

class _Apel:
    def __init__(self, rezultat=True, explodeaza=False):
        self.rezultat, self.explodeaza, self.primite = rezultat, explodeaza, []

    def __call__(self, **kwargs):
        if self.explodeaza:
            raise RuntimeError("registru picat")
        self.primite.append(kwargs)
        return self.rezultat


def test_marcarea_paseaza_exact_cheia_experimentului(monkeypatch):
    spion = _Apel()
    monkeypatch.setattr(st, "promote_experiment", spion)
    cl._marcheaza_in_registru("blend_v1", "8ac89c70", "all")
    assert spion.primite == [{"experiment_name": "blend_v1",
                              "experiment_version": "8ac89c70",
                              "league_scope": "all", "promoted_by": cl.PRODUCER}]


def test_marcarea_esuata_NU_ridica_exceptie(monkeypatch):
    """Registrul e evidenta, nu poarta: un esec de scriere e pierdere de
    INFORMATIE, o promovare oprita din cauza lui ar fi pierdere de DECIZIE."""
    monkeypatch.setattr(st, "promote_experiment", _Apel(rezultat=False))
    cl._marcheaza_in_registru("blend_v1", "8ac89c70", "all")


def test_exceptia_din_registru_NU_scapa_in_apelant(monkeypatch):
    monkeypatch.setattr(st, "promote_experiment", _Apel(explodeaza=True))
    cl._marcheaza_in_registru("blend_v1", "8ac89c70", "all")


def test_marcarea_raporteaza_esecul_in_log(monkeypatch, caplog):
    """Tacerea la esec ar readuce exact clasa pe care ADR-080 o repara."""
    monkeypatch.setattr(st, "promote_experiment", _Apel(rezultat=False))
    with caplog.at_level("WARNING"):
        cl._marcheaza_in_registru("blend_v1", "8ac89c70", "all")
    assert "experiment_registry" in caplog.text


# ════════════════════════════════════════════════════════════════════════════
# Garda structurala (AST, nu text) — cablarea nu se poate pierde tacit
#
# De ce AST: docstring-ul lui `_marcheaza_in_registru` numeste chiar
# `promote_experiment()` si `experiment_registry`, deci o garda textuala ar
# trece pe propria explicatie. A CINCEA instanta a clasei, dupa `pipefail`,
# numele de secrete, docstring-ul ADR-073 si comentariul D-11.
#
# [ADR-080 §7] Ultimul test pazeste invariantul ADR-019 pe care prima mea
# implementare l-a incalcat: `promotion_service` EXECUTA, nu decide, deci nu
# are voie sa atinga `shadow_testing`. Cablarea sta in orchestrator.
# ════════════════════════════════════════════════════════════════════════════

def _functie(cale: str, nume: str) -> ast.FunctionDef:
    arbore = ast.parse(pathlib.Path(cale).read_text(encoding="utf-8"))
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.FunctionDef) and nod.name == nume:
            return nod
    raise AssertionError(f"functia {nume!r} nu mai exista in {cale}")


def test_faza_C_chiar_apeleaza_marcarea_dupa_promovare():
    fn = _functie("learning_core/continuous_learning.py", "_phase_c_execute_approved")
    apeluri = [n.func.id for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "_marcheaza_in_registru" in apeluri


def test_bucla_de_evaluare_chiar_consulta_starile_terminale():
    fn = _functie("shadow_testing.py", "evaluate_all_active_experiments")
    apeluri = [n.func.id for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "_chei_terminale" in apeluri


def test_garda_nu_e_in_calea_de_scriere_a_registrului():
    """`_update_registry()` trebuie sa ramana o scriere simpla. O verificare
    acolo ar fi check-then-act pe calea de scriere, ceea ce proiectul
    interzice — motiv pentru care garda sta in bucla."""
    fn = _functie("shadow_testing.py", "_update_registry")
    nume = [n.id for n in ast.walk(fn) if isinstance(n, ast.Name)]
    assert "TERMINAL_REGISTRY_STATUSES" not in nume
    assert "_chei_terminale" not in nume


def test_promotion_service_ramane_CURAT_de_shadow_testing():
    """ADR-019, reconfirmat de ADR-080 §7: prima implementare a pus apelul in
    `promotion_service` si garda existenta a prins-o. Testul asta exista ca
    mutarea sa nu fie anulata din neatentie la o refactorizare viitoare."""
    arbore = ast.parse(pathlib.Path("learning_core/promotion_service.py")
                       .read_text(encoding="utf-8"))
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            assert all(a.name.split(".")[-1] != "shadow_testing" for a in nod.names)
        if isinstance(nod, ast.ImportFrom):
            assert (nod.module or "").split(".")[-1] != "shadow_testing"
