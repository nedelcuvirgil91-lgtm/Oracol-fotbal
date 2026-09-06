"""
Teste pentru cache-ul de predicții partajat între sesiuni (varianta C).

Ceasul e injectat, deci expirarea se testează exact, fără să aștepte secunde.
"""
from __future__ import annotations

import prediction_cache as pc

TTL = 900.0


def test_scrie_si_citeste():
    d = {}
    pc.scrie(d, "fx1", "valoare", acum=1000.0, ttl=TTL)
    assert pc.citeste(d, "fx1", acum=1000.0, ttl=TTL) == "valoare"


def test_cheia_lipsa_intoarce_none():
    assert pc.citeste({}, "fx1", acum=0.0, ttl=TTL) is None


def test_intrarea_expirata_nu_se_intoarce():
    d = {}
    pc.scrie(d, "fx1", "valoare", acum=1000.0, ttl=TTL)
    assert pc.citeste(d, "fx1", acum=1000.0 + TTL + 0.1, ttl=TTL) is None


def test_exact_la_limita_ttl_inca_e_valida():
    """Pragul e strict „mai vechi decât TTL", nu „la fel de vechi"."""
    d = {}
    pc.scrie(d, "fx1", "valoare", acum=1000.0, ttl=TTL)
    assert pc.citeste(d, "fx1", acum=1000.0 + TTL, ttl=TTL) == "valoare"


def test_intrarea_expirata_se_sterge_la_citire():
    """Altfel un meci nemaicerut niciodată ar ocupa loc la nesfârșit."""
    d = {}
    pc.scrie(d, "fx1", "valoare", acum=1000.0, ttl=TTL)
    pc.citeste(d, "fx1", acum=1000.0 + TTL + 1, ttl=TTL)
    assert "fx1" not in d


def test_valoarea_none_nu_se_memoreaza():
    """O analiză eșuată nu are voie să blocheze reîncercarea pentru tot TTL-ul."""
    d = {}
    pc.scrie(d, "fx1", None, acum=1000.0, ttl=TTL)
    assert d == {}
    assert pc.citeste(d, "fx1", acum=1000.0, ttl=TTL) is None


def test_rescrierea_reimprospateaza_intrarea():
    d = {}
    pc.scrie(d, "fx1", "veche", acum=1000.0, ttl=TTL)
    pc.scrie(d, "fx1", "noua", acum=1000.0 + TTL - 1, ttl=TTL)
    assert pc.citeste(d, "fx1", acum=1000.0 + TTL + 1, ttl=TTL) == "noua"


def test_curata_elimina_doar_expiratele():
    d = {}
    pc.scrie(d, "veche", "a", acum=1000.0, ttl=TTL)
    pc.scrie(d, "noua", "b", acum=1000.0 + TTL, ttl=TTL)
    eliminate = pc.curata(d, acum=1000.0 + TTL + 1, ttl=TTL)
    assert eliminate == 1
    assert set(d) == {"noua"}


def test_plafonul_de_capacitate_elimina_cele_mai_vechi():
    d = {}
    for i in range(10):
        pc.scrie(d, f"fx{i}", i, acum=1000.0 + i, ttl=TTL, capacitate=4)
    assert len(d) == 4
    assert set(d) == {"fx6", "fx7", "fx8", "fx9"}


def test_capacitatea_implicita_e_declarata():
    assert pc.CAPACITATE_IMPLICITA == 500


def test_goleste_returneaza_cate_a_sters():
    d = {}
    for i in range(3):
        pc.scrie(d, f"fx{i}", i, acum=1000.0, ttl=TTL)
    assert pc.goleste(d) == 3
    assert d == {}


def test_modulul_nu_citeste_ceasul_si_nu_importa_streamlit():
    """Puritatea e ce face testele de mai sus exacte. Dacă cineva importă
    `time` sau `streamlit` aici, ele devin dependente de ceasul real."""
    import ast
    from pathlib import Path

    arbore = ast.parse((Path(__file__).resolve().parent.parent
                        / "prediction_cache.py").read_text(encoding="utf-8"))
    importate = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            importate |= {a.name.split(".")[0] for a in nod.names}
        elif isinstance(nod, ast.ImportFrom) and nod.module:
            importate.add(nod.module.split(".")[0])
    assert not (importate & {"time", "datetime", "streamlit", "supabase_client"})
