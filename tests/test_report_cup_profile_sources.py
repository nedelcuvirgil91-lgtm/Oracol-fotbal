"""
Teste pentru raportul de surse ale profilului la meciurile de cupă.

Zero rețea, zero Supabase: toate cititoarele sunt injectate.

Testul cel mai important nu verifică o numărătoare, ci sincronizarea cu
motorul: `test_pragul_e_acelasi_cu_al_motorului` citește sursa lui
`oracle_engine._build_profile()` și cade dacă pragul de acolo se schimbă fără
ca raportul să fie actualizat. Fără el, raportul ar continua să afișeze cifre
plauzibile, dar despre altă cascadă decât cea care rulează.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from scripts.report_cup_profile_sources import (
    CUPE,
    NIVEL_DB,
    NIVEL_FS,
    NIVEL_FS2,
    NIVEL_NATIONAL,
    NIVEL_SUB_FS2,
    ORDINEA_NIVELURILOR,
    PRAG_ISTORIC_DB,
    nivel_servit,
)

REPO = Path(__file__).resolve().parent.parent


def _cititoare(*, istoric=(), national=None, clasament=None, context=()):
    return {
        "citeste_istoric": lambda e, c: list(istoric),
        "citeste_national": lambda e: national,
        "citeste_clasament": lambda e, c: clasament,
        "citeste_context": lambda e: list(context),
    }


def _meciuri(n: int):
    return [{"actual_result": "H"}] * n


# ── Sincronizarea cu motorul ─────────────────────────────────────────────────

def test_pragul_e_acelasi_cu_al_motorului():
    """`MIN_DB_MATCHES` e o variabilă locală în `_build_profile()`, deci nu se
    poate importa — se citește din sursă. Dacă motorul își schimbă pragul,
    testul cade și raportul trebuie actualizat, în loc să mintă tăcut."""
    sursa = (REPO / "oracle_engine.py").read_text(encoding="utf-8")
    gasite = re.findall(r"^\s*MIN_DB_MATCHES\s*=\s*(\d+)\s*$", sursa, re.M)
    assert gasite, "MIN_DB_MATCHES nu mai există în oracle_engine.py"
    assert len(set(gasite)) == 1, f"MIN_DB_MATCHES definit cu valori diferite: {gasite}"
    assert int(gasite[0]) == PRAG_ISTORIC_DB


def test_numele_nivelurilor_sunt_cele_scrise_de_motor():
    """Etichetele raportului trebuie să fie exact șirurile pe care motorul le
    atribuie lui `data_source` — altfel raportul descrie niveluri inexistente."""
    sursa = (REPO / "oracle_engine.py").read_text(encoding="utf-8")
    for nivel in (NIVEL_DB, NIVEL_NATIONAL, NIVEL_FS, NIVEL_FS2):
        assert f'"{nivel}"' in sursa, f"motorul nu mai produce data_source={nivel!r}"


def test_ordinea_declarata_acopera_toate_nivelurile():
    assert ORDINEA_NIVELURILOR == (NIVEL_DB, NIVEL_NATIONAL, NIVEL_FS,
                                   NIVEL_FS2, NIVEL_SUB_FS2)
    assert len(set(ORDINEA_NIVELURILOR)) == 5


def test_cele_trei_cupe_sunt_cele_asteptate():
    assert set(CUPE) == {"Champions League", "Europa League", "Conference League"}


# ── Cascada, nivel cu nivel ──────────────────────────────────────────────────

def test_istoricul_suficient_castiga_primul():
    nivel = nivel_servit("X", "Champions League",
                         **_cititoare(istoric=_meciuri(3), context=[{"result": "W"}]))
    assert nivel == NIVEL_DB


def test_istoric_sub_prag_nu_activeaza_nivelul_DB():
    nivel = nivel_servit("X", "Champions League",
                         **_cititoare(istoric=_meciuri(2), context=[{"result": "W"}]))
    assert nivel == NIVEL_FS2


def test_nationalele_vin_inaintea_clasamentului():
    nivel = nivel_servit("X", "Champions League",
                         **_cititoare(national={"off": 1.0},
                                      clasament={"form": ["W", "D"]}))
    assert nivel == NIVEL_NATIONAL


def test_clasamentul_cu_forma_reala_serveste():
    nivel = nivel_servit("X", "Champions League",
                         **_cititoare(clasament={"form": ["W", "D", "L"]},
                                      context=[{"result": "W"}]))
    assert nivel == NIVEL_FS


def test_clasamentul_cu_forma_GOALA_e_sarit():
    """Cazul real al fazei principale: toate cele 108 rânduri de clasament au
    `played=0` și formă goală. Un `results=[]` ar produce form_score=0.0 —
    cel mai rău caz, nu neutru (Regula #8). Motorul îl sare; raportul la fel."""
    for gol in ([], None):
        nivel = nivel_servit("X", "Champions League",
                             **_cititoare(clasament={"played": 0, "form": gol},
                                          context=[{"result": "W"}]))
        assert nivel == NIVEL_FS2


def test_contextul_de_meci_prinde_echipele_fara_clasament():
    nivel = nivel_servit("X", "Conference League",
                         **_cititoare(context=[{"result": "W"}, {"result": "L"}]))
    assert nivel == NIVEL_FS2


def test_fara_nimic_ramane_sub_ultimul_nivel_util():
    assert nivel_servit("X", "Europa League", **_cititoare()) == NIVEL_SUB_FS2


def test_cititoarele_care_intorc_None_nu_arunca():
    nivel = nivel_servit("X", "Europa League", **{
        "citeste_istoric": lambda e, c: None,
        "citeste_national": lambda e: None,
        "citeste_clasament": lambda e, c: None,
        "citeste_context": lambda e: None,
    })
    assert nivel == NIVEL_SUB_FS2


def test_pragul_e_parametru_nu_constanta_ascunsa():
    cititoare = _cititoare(istoric=_meciuri(2))
    assert nivel_servit("X", "Champions League", prag_db=2, **cititoare) == NIVEL_DB
    assert nivel_servit("X", "Champions League", prag_db=3, **cititoare) == NIVEL_SUB_FS2


# ── Garda: raportul nu scrie nimic ───────────────────────────────────────────

SCRIERI = {"insert", "upsert", "update", "delete", "rpc"}


def _scrieri_pe_baza_de_date(sursa: str) -> list[str]:
    """Metodele de scriere apelate pe un lanț care pornește dintr-un `.table(...)`.

    Căutarea pe text ar fi greșită: `sys.path.insert(0, ...)` e o operație pe
    listă, nu pe baza de date — prima versiune a acestei gărzi a raportat exact
    acel fals pozitiv. Se verifică deci lanțul de apel, nu numele metodei."""
    gasite: list[str] = []
    for nod in ast.walk(ast.parse(sursa)):
        if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)):
            continue
        if nod.func.attr not in SCRIERI:
            continue
        if any(isinstance(x, ast.Attribute) and x.attr == "table"
               for x in ast.walk(nod.func.value)):
            gasite.append(nod.func.attr)
    return gasite


def test_raportul_nu_contine_nicio_operatie_de_scriere():
    sursa = (REPO / "scripts" / "report_cup_profile_sources.py").read_text(encoding="utf-8")
    assert _scrieri_pe_baza_de_date(sursa) == []


def test_garda_de_scriere_chiar_prinde_o_incalcare():
    """Contra-test: fără el, garda de mai sus ar putea trece vidă."""
    assert _scrieri_pe_baza_de_date("def f(c):\n    c.table('x').insert({})\n") == ["insert"]
    assert _scrieri_pe_baza_de_date(
        "def f(c):\n    c.table('x').upsert([], on_conflict='a').execute()\n") == ["upsert"]


def test_garda_nu_da_fals_pozitiv_pe_operatii_de_lista():
    """Exact eroarea primei versiuni."""
    assert _scrieri_pe_baza_de_date("import sys\nsys.path.insert(0, 'x')\n") == []
    assert _scrieri_pe_baza_de_date("d = {}\nd.update({'a': 1})\n") == []


def test_raportul_nu_importa_motorul():
    """Raportul măsoară cascada, nu o rulează: nu importă `oracle_engine`, deci
    nu poate declanșa nicio predicție ca efect secundar."""
    arbore = ast.parse((REPO / "scripts" / "report_cup_profile_sources.py")
                       .read_text(encoding="utf-8"))
    importate = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            importate |= {a.name.split(".")[0] for a in nod.names}
        elif isinstance(nod, ast.ImportFrom) and nod.module:
            importate.add(nod.module.split(".")[0])
    assert "oracle_engine" not in importate
