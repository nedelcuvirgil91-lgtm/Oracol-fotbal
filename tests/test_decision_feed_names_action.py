"""D-11 — Decision Feed trebuie să NUMEASCĂ acțiunea pe care o aprobi.

DE CE EXISTĂ. Titlul era `f"[{tier}] decizie #{id} · run_id={run_id}"` — mut
despre acțiune. Omul vedea `[T3a] decizie #7 · run_id=786`, un `st.json` brut și
un buton VERDE „✅ Aprobă". A produs o confuzie reală: proprietarul produsului a
raportat „am promovat noul candidat"; verificat, aprobase o EXPIRARE.

E guvernanță, nu cosmetică: ADR-002 face aprobarea umană SINGURA cale de
promovare și rollback. Un titlu mut plus un buton verde transformă
consimțământul informat în consimțământ PREZUMAT. Același ecran va servi și
propuneri de promovare și de rollback.

DOUĂ FORME REALE DE `evidence`, măsurate pe producție pe 2026-10-20 — nu
inventate pentru test:

  #8  expirare : decision_kind='expiry', training_run_id, n_matches_evaluated=301
  #6  consens  : NICIUN decision_kind — verdict='surface_worthy', study_run_id,
                 n_samples_evaluated=965

A doua e motivul pentru care funcția nu poate presupune că `decision_kind`
există. Un titlu gol pe deciziile vechi ar fi fost exact defectul reparat, mutat.

GARDA PE `app.py` FOLOSEȘTE AST, NU TEXT. Comentariul pe care l-am scris acolo
conține chiar șirul vechi (`decizie #7 · run_id=786`), ca explicație. O gardă
textuală l-ar găsi pe el și ar trece după ștergerea codului real — a patra
instanță a clasei, după `pipefail` (27 aug), numele de secrete (14 oct) și
docstring-ul ADR-073. AST-ul ignoră comentariile PRIN CONSTRUCȚIE, deci nu e o
reparație, e o imposibilitate.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import automation_runs as ar

RADACINA = Path(__file__).resolve().parent.parent
APP = RADACINA / "app.py"


# Dovezile REALE, copiate din producție (`decision_feed`, 2026-10-20).
DOVADA_EXPIRARE = {
    "status": "monitoring",
    "decision_kind": "expiry",
    "training_run_id": "174e7e17-347e-498e-912f-893a855f742b",
    "n_matches_evaluated": 301,
    "baseline_source": "shadow_control",
    "min_matches_for_expiry": 300,
}

DOVADA_CONSENS = {
    "verdict": "surface_worthy",
    "metric_name": "agreement_score",
    "study_run_id": 1216,
    "n_samples_evaluated": 965,
}


# ════════════════════════════════════════════════════════════════════════════
# Funcția pură
# ════════════════════════════════════════════════════════════════════════════

def test_expirarea_isi_spune_numele():
    """Garda centrală, pe cazul care te așteaptă chiar acum (decizia #8)."""
    rez = ar.rezuma_decizia({"id": 8, "tier": "T3a", "evidence": DOVADA_EXPIRARE})
    assert "EXPIRARE" in rez["titlu"]
    assert "174e7e17" in rez["titlu"], "ținta nu apare — nu știi PE CINE expiri"
    assert "n=301" in rez["titlu"]
    assert rez["actiune"] == "EXPIRARE Challenger"


def test_titlul_NU_mai_e_forma_muta():
    """Contraponderea directă: vechiul titlu nu numea nimic."""
    rez = ar.rezuma_decizia({"id": 8, "tier": "T3a", "evidence": DOVADA_EXPIRARE})
    vechi = "[T3a] decizie #8 · run_id=1142"
    assert rez["titlu"] != vechi
    assert not rez["titlu"].startswith("[T3a] decizie #")


def test_consensul_fara_decision_kind_NU_minte():
    """Forma reală a deciziei #6: n-are `decision_kind` deloc.

    `verdict` NU e promovat la rangul de acțiune — se arată etichetat ca
    verdict, iar acțiunea rămâne explicit necunoscută (Regula #8)."""
    rez = ar.rezuma_decizia({"id": 6, "tier": "T3a", "evidence": DOVADA_CONSENS})
    assert ar.FEL_NECUNOSCUT in rez["actiune"]
    assert "surface_worthy" in rez["actiune"], "verdictul se arată, nu se ascunde"
    assert "studiu #1216" in rez["titlu"]
    assert "n=965" in rez["titlu"]


def test_fel_necunoscut_cand_nu_exista_nimic():
    """Nici `decision_kind`, nici `verdict`. Niciodată gol, niciodată ghicit."""
    rez = ar.rezuma_decizia({"id": 3, "tier": "T3a", "evidence": {}})
    assert rez["actiune"] == ar.FEL_NECUNOSCUT
    assert ar.FEL_NECUNOSCUT in rez["titlu"]


@pytest.mark.parametrize("dovada", [None, "nu e dict", 42, []])
def test_nu_arunca_pe_dovada_stricata(dovada):
    """Ecranul de aprobare nu are voie să cadă — ar bloca singura cale de
    promovare/rollback (ADR-002)."""
    rez = ar.rezuma_decizia({"id": 1, "tier": "T3a", "evidence": dovada})
    assert rez["actiune"] == ar.FEL_NECUNOSCUT
    assert rez["titlu"]


def test_fel_NOU_se_arata_brut_nu_se_inventeaza():
    """Un fel necunoscut hărții NU primește o etichetă plauzibilă inventată —
    apare brut, ca să fie vizibil că e nou."""
    rez = ar.rezuma_decizia({"id": 9, "tier": "T2",
                             "evidence": {"decision_kind": "recalibration"}})
    assert "RECALIBRATION" in rez["actiune"]


def test_promovarea_si_rollbackul_au_eticheta():
    """Cele două pentru care ADR-002 există. Azi nu sunt produse de niciun cod,
    dar ecranul le va servi — iar ele sunt exact cazurile în care un titlu mut
    ar costa cel mai mult."""
    for fel, asteptat in (("promotion", "PROMOVARE"), ("rollback", "ROLLBACK")):
        rez = ar.rezuma_decizia({"id": 1, "tier": "T3a",
                                 "evidence": {"decision_kind": fel}})
        assert asteptat in rez["actiune"]


def test_familia_apare_cand_exista():
    rez = ar.rezuma_decizia({"id": 8, "tier": "T3a", "evidence": {
        "decision_kind": "expiry", "algorithm_family": "blend_v1",
        "training_run_id": "174e7e17-347e"}})
    assert "blend_v1/174e7e17" in rez["titlu"]


# ════════════════════════════════════════════════════════════════════════════
# Garda structurală pe `app.py` — AST, imună la comentarii prin construcție
# ════════════════════════════════════════════════════════════════════════════

def _arbore_app() -> ast.Module:
    return ast.parse(APP.read_text(encoding="utf-8"))


def _apeluri(arbore: ast.Module, nume_atribut: str) -> list[ast.Call]:
    return [n for n in ast.walk(arbore)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == nume_atribut]


def test_app_cheama_rezumatul():
    """Dacă cineva rescrie blocul fără rezumat, titlul redevine mut."""
    arbore = _arbore_app()
    assert any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "rezuma_decizia"
        for n in ast.walk(arbore)
    ), "app.py nu mai apelează rezuma_decizia — titlul Decision Feed e iar mut"


def test_niciun_expander_nu_are_titlu_mut():
    """Garda care prinde întoarcerea defectului.

    Caută f-string-uri date direct lui `st.expander` care conțin `decizie #`.
    AST-ul nu vede comentarii, deci explicația din `app.py` — care conține chiar
    șirul vechi — nu poate păcăli garda. Asta e proprietatea care lipsea la
    `pipefail`."""
    vinovati = []
    for apel in _apeluri(_arbore_app(), "expander"):
        if not apel.args:
            continue
        prim = apel.args[0]
        if isinstance(prim, ast.JoinedStr):
            literal = "".join(v.value for v in prim.values
                              if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if "decizie #" in literal:
                vinovati.append(f"linia {apel.lineno}: {literal!r}")
    assert not vinovati, (
        "titlu de expander care numește doar id-ul, nu acțiunea:\n  "
        + "\n  ".join(vinovati))


def test_butoanele_de_decizie_nu_au_eticheta_STATICA():
    """Butonul e ULTIMUL lucru văzut înainte de scriere.

    Un `"✅ Aprobă"` constant e exact consimțământul prezumat: titlul se citește
    o dată, butonul se apasă. Cerem o etichetă compusă (f-string), deci
    dependentă de decizia concretă."""
    statice = []
    for apel in _apeluri(_arbore_app(), "button"):
        if not apel.args:
            continue
        prim = apel.args[0]
        if isinstance(prim, ast.Constant) and isinstance(prim.value, str):
            text = prim.value
            if "Aprobă" in text or "Respinge" in text:
                statice.append(f"linia {apel.lineno}: {text!r}")
    assert not statice, (
        "buton de decizie cu etichetă STATICĂ — nu spune ce aprobi:\n  "
        + "\n  ".join(statice))
