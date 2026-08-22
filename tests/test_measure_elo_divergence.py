"""Teste pentru scripts/measure_elo_divergence.py — masuratoarea divergentei
ELO (read-only) care precede decizia de rebuild.

`summarize()` e pura, testata direct. Praguri: neglijabil < 5, material >= 50.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from measure_elo_divergence import (  # noqa: E402
    PRAG_MATERIAL,
    PRAG_NEGLIJABIL,
    summarize,
)


def test_lista_goala_nu_arunca():
    """O baza fara niciun ELO persistat trebuie sa dea zerouri, nu exceptie."""
    st = summarize([])
    assert st["n"] == 0
    assert st["max"] == 0
    assert st["media"] == 0.0


def test_toate_identice_inseamna_zero_divergenta():
    st = summarize([0, 0, 0, 0])
    assert st["n"] == 4
    assert st["zero"] == 4
    assert st["neglijabil"] == 0
    assert st["material"] == 0
    assert st["max"] == 0


def test_diferenta_zero_nu_e_numarata_ca_neglijabila():
    """`zero` si `neglijabil` sunt categorii disjuncte — altfel raportul ar
    numara acelasi rand de doua ori si ar exagera problema."""
    st = summarize([0, 1, 2])
    assert st["zero"] == 1
    assert st["neglijabil"] == 2
    assert st["zero"] + st["neglijabil"] == 3


def test_pragul_material_e_inclusiv():
    """Exact 50 conteaza ca material — pragul e >=, nu >."""
    st = summarize([PRAG_MATERIAL - 1, PRAG_MATERIAL, PRAG_MATERIAL + 1])
    assert st["material"] == 2


def test_pragul_neglijabil_e_exclusiv():
    """Exact 5 NU mai e neglijabil — pragul e <, nu <=."""
    st = summarize([PRAG_NEGLIJABIL - 1, PRAG_NEGLIJABIL])
    assert st["neglijabil"] == 1


def test_statistici_de_pozitie_pe_set_cunoscut():
    diffs = [0, 10, 20, 30, 100]
    st = summarize(diffs)
    assert st["max"] == 100
    assert st["media"] == 32.0
    assert st["mediana"] == 20
    assert st["material"] == 1


def test_ordinea_de_intrare_nu_conteaza():
    """Masuratoarea nu are voie sa depinda de ordinea in care vin diferentele."""
    a = summarize([100, 0, 50, 3])
    b = summarize([3, 50, 0, 100])
    assert a == b


def test_p95_nu_iese_din_lista():
    """Garda de indice: pe liste mici, p95 nu are voie sa arunce IndexError."""
    for n in range(1, 12):
        st = summarize(list(range(n)))
        assert 0 <= st["p95"] <= n - 1


def test_un_singur_element():
    st = summarize([77])
    assert st["n"] == 1
    assert st["max"] == st["mediana"] == st["p95"] == 77
    assert st["material"] == 1
    assert st["zero"] == 0
