"""Teste pentru scripts/detect_identity_alias_candidates.py — detectorul de
candidati de vocabular (categoria D3).

`find_candidates()` e pura, testata pe randuri sintetice. Accentul cade pe
VETO: istoria proiectului (v1.2, 141 fuziuni false dupa prefix-matching) face
ca falsul pozitiv sa fie modul de esec costisitor, nu falsul negativ.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detect_identity_alias_candidates import find_candidates  # noqa: E402


def _row(rid, home, away, kd="2026-01-01", league="L1", hg=1, ag=0, res="H"):
    return {"id": rid, "home_team": home, "away_team": away, "kickoff_date": kd,
            "league": league, "actual_home_goals": hg, "actual_away_goals": ag,
            "actual_result": res}


def test_acelasi_meci_sub_doua_nume_e_candidat():
    rows = [_row(1, "Almere City", "Ajax"), _row(2, "Almere City FC", "Ajax")]
    c = find_candidates(rows)
    assert len(c) == 1
    assert c[0]["nume_a"] == "Almere City" and c[0]["nume_b"] == "Almere City FC"
    assert c[0]["respins_veto"] is False
    assert c[0]["perechi"] == 1


def test_detectie_si_pe_partea_de_oaspete():
    rows = [_row(1, "Ajax", "Almere City"), _row(2, "Ajax", "Almere City FC")]
    c = find_candidates(rows)
    assert len(c) == 1 and c[0]["respins_veto"] is False


def test_veto_cand_cele_doua_nume_s_au_infruntat():
    """Modul de esec critic: doua cluburi diferite pot coincide accidental pe
    (zi, liga, scor). Daca s-au infruntat vreodata, sunt cluburi diferite —
    veto absolut. Caz real: FCSB / Sepsi OSK."""
    rows = [
        _row(1, "FCSB", "Rapid"), _row(2, "Sepsi OSK", "Rapid"),
        _row(3, "FCSB", "Sepsi OSK", kd="2025-05-05"),
    ]
    c = find_candidates(rows)
    assert len(c) == 1
    assert c[0]["respins_veto"] is True


def test_vetoul_bate_orice_cantitate_de_dovada_pozitiva():
    """Chiar si cu multe coincidente, un singur meci direct invalideaza
    perechea. Cantitatea nu invinge imposibilitatea logica."""
    rows = [_row(i, "FCSB", "Rapid", kd=f"2025-01-{i:02d}") for i in range(1, 10)]
    rows += [_row(100 + i, "Sepsi OSK", "Rapid", kd=f"2025-01-{i:02d}") for i in range(1, 10)]
    rows.append(_row(999, "FCSB", "Sepsi OSK", kd="2025-06-01"))
    c = find_candidates(rows)
    assert len(c) == 1
    assert c[0]["perechi"] == 9
    assert c[0]["respins_veto"] is True


def test_veto_indiferent_de_ordinea_gazda_oaspete():
    rows = [
        _row(1, "A", "X"), _row(2, "B", "X"),
        _row(3, "B", "A", kd="2025-05-05"),   # inversat fata de (A, B)
    ]
    assert find_candidates(rows)[0]["respins_veto"] is True


def test_veto_se_aplica_si_din_meciuri_fara_rezultat():
    """Un meci VIITOR programat intre A si B e la fel de concludent ca unul
    jucat — vetoul se construieste din toate randurile, nu doar din cele cu
    rezultat."""
    viitor = _row(3, "A", "B", kd="2027-01-01", res=None)
    viitor["actual_home_goals"] = None
    viitor["actual_away_goals"] = None
    rows = [_row(1, "A", "X"), _row(2, "B", "X"), viitor]
    assert find_candidates(rows)[0]["respins_veto"] is True


def test_scoruri_diferite_nu_produc_candidat():
    rows = [_row(1, "A", "X", hg=1, ag=0), _row(2, "B", "X", hg=2, ag=0)]
    assert find_candidates(rows) == []


def test_zile_diferite_nu_produc_candidat():
    rows = [_row(1, "A", "X", kd="2026-01-01"), _row(2, "B", "X", kd="2026-01-02")]
    assert find_candidates(rows) == []


def test_ligi_diferite_nu_produc_candidat():
    rows = [_row(1, "A", "X", league="L1"), _row(2, "B", "X", league="L2")]
    assert find_candidates(rows) == []


def test_ambele_parti_diferite_nu_produc_candidat():
    """Daca ambele echipe difera, nu exista ancora: nu se poate spune CARE
    nume corespunde carui nume. Se ignora, nu se ghiceste."""
    rows = [_row(1, "A", "X"), _row(2, "B", "Y")]
    assert find_candidates(rows) == []


def test_meciuri_identice_nu_produc_candidat():
    """Doua randuri complet identice ca nume sunt un duplicat de alt tip
    (treaba reconcilierii), nu un candidat de vocabular."""
    rows = [_row(1, "A", "X"), _row(2, "A", "X")]
    assert find_candidates(rows) == []


def test_dovezile_se_acumuleaza_pe_aceeasi_pereche():
    rows = [
        _row(1, "A", "X", kd="2026-01-01"), _row(2, "B", "X", kd="2026-01-01"),
        _row(3, "A", "Y", kd="2026-02-01"), _row(4, "B", "Y", kd="2026-02-01"),
    ]
    c = find_candidates(rows)
    assert len(c) == 1 and c[0]["perechi"] == 2


def test_ordonare_candidatii_acceptati_inaintea_celor_respinsi():
    rows = [
        _row(1, "A", "X"), _row(2, "B", "X"),
        _row(3, "C", "Y"), _row(4, "D", "Y"),
        _row(5, "C", "D", kd="2025-05-05"),
    ]
    c = find_candidates(rows)
    assert c[0]["respins_veto"] is False
    assert c[-1]["respins_veto"] is True


def test_randuri_fara_nume_nu_arunca():
    rows = [_row(1, None, "X"), _row(2, "B", "X"), _row(3, "C", None)]
    assert find_candidates(rows) == []


def test_lista_goala_nu_arunca():
    assert find_candidates([]) == []


def test_detectorul_nu_scrie_nicaieri_si_nu_atinge_mappings():
    """Garda structurala pe AST. Doua contracte separate: nicio scriere in
    Supabase, si niciun `open(...)` — detectorul propune aliasuri, nu le scrie
    in mappings.py."""
    import ast

    src = (Path(__file__).resolve().parent.parent / "scripts"
           / "detect_identity_alias_candidates.py").read_text(encoding="utf-8")
    interzise = {"insert", "update", "upsert", "delete", "rpc", "write_text", "write"}

    gasite = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id == "open":
            gasite.append(f"linia {node.lineno}: open(...)")
            continue
        if not isinstance(fn, ast.Attribute) or fn.attr not in interzise:
            continue
        if fn.attr == "insert" and ast.unparse(fn.value) == "sys.path":
            continue
        gasite.append(f"linia {node.lineno}: {ast.unparse(fn)}(...)")

    assert not gasite, "operatii interzise: " + "; ".join(gasite)
