"""Teste pentru scripts/analyze_d2_vocabulary_drift.py — analiza read-only a
categoriei D2 (nume fragmentate care NU colizioneaza).

`classify()` e pura si primeste `normalize` prin injectie, deci se testeaza pe
un vocabular mic si explicit, fara Supabase si fara cele 854 de alias-uri reale.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analyze_d2_vocabulary_drift import classify  # noqa: E402

# Vocabular de test: sufixul de tara si forma lunga cad pe acelasi canonic.
_VOCAB = {
    "Liverpool FC (ENG)": "Liverpool",
    "Liverpool FC": "Liverpool",
    "AC Milan (ITA)": "AC Milan",
}


def _norm(name: str) -> str:
    return _VOCAB.get(name, name)


def _row(rid, home, away, kd="2026-01-01"):
    return {"id": rid, "home_team": home, "away_team": away, "kickoff_date": kd}


def test_nume_deja_canonic_nu_e_d2():
    """Un nume pe care normalizarea il lasa neschimbat nu are ce cauta in D2."""
    res = classify([_row(1, "Liverpool", "Arsenal")], _norm)
    assert res["d2_distinct_names"] == 0
    assert res["d2_affected_rows"] == 0
    assert res["rename_map"] == {}


def test_nume_fragmentat_e_detectat_pe_ambele_parti():
    res = classify([_row(1, "Liverpool FC (ENG)", "AC Milan (ITA)")], _norm)
    assert res["d2_distinct_names"] == 2
    assert res["d2_affected_rows"] == 1  # un singur RAND, doua aparitii
    assert res["d2_occurrences"] == 2
    assert res["rename_map"]["Liverpool FC (ENG)"] == "Liverpool"


def test_randul_afectat_e_numarat_o_singura_data():
    """Un rand cu ambele echipe fragmentate ramane UN rand afectat — altfel
    raportul ar exagera amploarea migrarii."""
    rows = [_row(1, "Liverpool FC (ENG)", "Liverpool FC"), _row(2, "Arsenal", "Chelsea")]
    res = classify(rows, _norm)
    assert res["d2_affected_rows"] == 1


def test_lant_rupt_cere_doua_nume_vii():
    """O identitate atinsa de un singur nume viu NU e un lant rupt, chiar daca
    acel nume e fragmentat — nu exista serie ELO paralela."""
    res = classify([_row(1, "Liverpool FC (ENG)", "Arsenal")], _norm)
    assert res["broken_chains"] == {}
    assert res["d2_distinct_names"] == 1


def test_lant_rupt_detectat_cand_ambele_forme_traiesc():
    rows = [_row(1, "Liverpool", "Arsenal"), _row(2, "Liverpool FC (ENG)", "Chelsea")]
    res = classify(rows, _norm)
    assert set(res["broken_chains"]) == {"Liverpool"}
    assert res["broken_chains"]["Liverpool"] == ["Liverpool", "Liverpool FC (ENG)"]


def test_lant_rupt_cu_trei_variante():
    rows = [
        _row(1, "Liverpool", "Arsenal"),
        _row(2, "Liverpool FC", "Chelsea"),
        _row(3, "Liverpool FC (ENG)", "Everton"),
    ]
    res = classify(rows, _norm)
    assert len(res["broken_chains"]["Liverpool"]) == 3


def test_fara_coliziune_cand_meciurile_difera():
    rows = [_row(1, "Liverpool FC (ENG)", "Arsenal"), _row(2, "Liverpool", "Chelsea")]
    res = classify(rows, _norm)
    assert res["collisions"] == {}


def test_coliziune_detectata_cand_redenumirea_suprapune_doua_randuri_vii():
    """Cazul care ar face redenumirea sa esueze pe indexul unic: doua randuri
    vii, nume diferite azi, aceeasi cheie dupa normalizare."""
    rows = [_row(1, "Liverpool FC (ENG)", "Arsenal"), _row(2, "Liverpool", "Arsenal")]
    res = classify(rows, _norm)
    assert len(res["collisions"]) == 1
    ids = next(iter(res["collisions"].values()))
    assert sorted(ids) == [1, 2]


def test_kickoff_date_diferit_nu_e_coliziune():
    """Cheia indexului include `kickoff_date` ca text EXACT — doua forme ale
    aceleiasi zile ('2026-01-01' vs '2026-01-01T19:00:00Z') sunt chei diferite
    pentru index, deci nu colizioneaza. A le trunchia la 10 caractere ar fi
    `match_key()`, o cheie diferita."""
    rows = [
        _row(1, "Liverpool FC (ENG)", "Arsenal", "2026-01-01"),
        _row(2, "Liverpool", "Arsenal", "2026-01-01T19:00:00Z"),
    ]
    res = classify(rows, _norm)
    assert res["collisions"] == {}


def test_coliziune_raportata_chiar_fara_redenumire():
    """Daca doua randuri vii au deja aceeasi cheie exacta (stare care ar trebui
    sa fie imposibila sub indexul unic), analiza trebuie sa o arate, nu sa o
    ascunda — e o incalcare de invariant, nu un detaliu."""
    rows = [_row(1, "Arsenal", "Chelsea"), _row(2, "Arsenal", "Chelsea")]
    res = classify(rows, _norm)
    assert len(res["collisions"]) == 1


def test_nume_lipsa_nu_arunca():
    rows = [{"id": 1, "home_team": None, "away_team": "", "kickoff_date": "2026-01-01"}]
    res = classify(rows, _norm)
    assert res["d2_distinct_names"] == 0
    assert res["live_distinct_names"] == 0


def test_aparitiile_sunt_numarate_pe_ambele_parti():
    rows = [_row(1, "Liverpool", "Arsenal"), _row(2, "Arsenal", "Liverpool")]
    res = classify(rows, _norm)
    assert res["raw_occurrences"]["Liverpool"] == 2
    assert res["raw_occurrences"]["Arsenal"] == 2


def test_lista_goala_nu_arunca():
    res = classify([], _norm)
    assert res["live_rows"] == 0
    assert res["broken_chains"] == {}
    assert res["collisions"] == {}


def test_scriptul_nu_contine_nicio_operatie_de_scriere():
    """Garda structurala: analiza D2 e declarata read-only. Orice apel de
    scriere Supabase in modul e o regresie de contract, nu un detaliu de stil.

    Verificarea e pe AST, nu pe subsir: `sys.path.insert(...)` contine literal
    '.insert(' fara sa fie o scriere in baza. O cautare textuala ar da fals
    pozitiv exact acolo si ar fi dezactivata la prima frictiune — adica exact
    momentul in care garda ar trebui sa functioneze.
    """
    import ast

    src = (Path(__file__).resolve().parent.parent / "scripts"
           / "analyze_d2_vocabulary_drift.py").read_text(encoding="utf-8")
    interzise = {"insert", "update", "upsert", "delete", "rpc"}

    gasite = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in interzise:
            continue
        # `sys.path.insert` nu e o scriere in baza — e bootstrap de import.
        if fn.attr == "insert" and ast.unparse(fn.value) == "sys.path":
            continue
        gasite.append(f"linia {node.lineno}: {ast.unparse(fn)}(...)")

    assert not gasite, "apeluri de scriere interzise: " + "; ".join(gasite)
