"""Teste pentru scripts/audit_penalty_shootout_rows.py — auditul read-only al
scorurilor corupte de bugul penalty-shootout.

`truth_from_score()` si `season_to_api_year()` sunt pure, testate direct pe
payload-uri sintetice, fara retea si fara Supabase.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from audit_penalty_shootout_rows import season_to_api_year, truth_from_score  # noqa: E402


def test_meci_normal_ia_fulltime():
    score = {"duration": "REGULAR", "fullTime": {"home": 2, "away": 1}}
    assert truth_from_score(score) == (2, 1, "REGULAR")


def test_penalty_shootout_ia_regulartime_nu_fulltime():
    """Cazul real fd_524100: fullTime 1-5 include loviturile de departajare,
    scorul meciului e 0-1 din regularTime."""
    score = {
        "duration": "PENALTY_SHOOTOUT",
        "fullTime": {"home": 1, "away": 5},
        "regularTime": {"home": 0, "away": 1},
        "penalties": {"home": 1, "away": 4},
    }
    assert truth_from_score(score) == (0, 1, "PENALTY_SHOOTOUT")


def test_duration_e_case_insensitive():
    score = {"duration": "penalty_shootout",
             "fullTime": {"home": 1, "away": 5},
             "regularTime": {"home": 0, "away": 1}}
    assert truth_from_score(score)[:2] == (0, 1)


def test_extra_time_foloseste_fulltime():
    """Prelungiri FARA penalty-uri: fullTime E scorul real al meciului.
    A trata EXTRA_TIME ca shootout ar strica meciuri corecte."""
    score = {"duration": "EXTRA_TIME",
             "fullTime": {"home": 3, "away": 2},
             "regularTime": {"home": 2, "away": 2}}
    assert truth_from_score(score) == (3, 2, "EXTRA_TIME")


def test_shootout_fara_regulartime_da_necunoscut_nu_aproximare():
    """North Star #8: o stare necunoscuta ramane necunoscuta. Daca regularTime
    lipseste, NU se cade inapoi pe fullTime — ar reintroduce exact bugul."""
    score = {"duration": "PENALTY_SHOOTOUT", "fullTime": {"home": 1, "away": 5}}
    assert truth_from_score(score) == (None, None, "PENALTY_SHOOTOUT")


def test_score_gol_nu_arunca():
    assert truth_from_score({}) == (None, None, "")


def test_duration_lipsa_e_tratat_ca_normal():
    score = {"fullTime": {"home": 0, "away": 0}}
    assert truth_from_score(score) == (0, 0, "")


def test_scor_zero_nu_e_confundat_cu_absent():
    """0 e o valoare valida, nu 'lipsa' — o garda scrisa cu `or` ar strica
    exact meciurile 0-0."""
    h, a, _ = truth_from_score({"duration": "REGULAR", "fullTime": {"home": 0, "away": 0}})
    assert h == 0 and a == 0
    assert h is not None and a is not None


def test_sezon_interval_da_anul_de_start():
    assert season_to_api_year("2023-2024") == 2023


def test_sezon_simplu():
    assert season_to_api_year("2023") == 2023


def test_sezon_absent_sau_invalid_da_none():
    for val in (None, "", "necunoscut", "23-24", "20233"):
        assert season_to_api_year(val) is None, val


def test_auditul_nu_contine_nicio_operatie_de_scriere():
    """Garda structurala pe AST (nu pe subsir — `sys.path.insert` ar da fals
    pozitiv): auditul e declarat read-only si trebuie sa ramana asa."""
    import ast

    src = (Path(__file__).resolve().parent.parent / "scripts"
           / "audit_penalty_shootout_rows.py").read_text(encoding="utf-8")
    interzise = {"insert", "update", "upsert", "delete", "rpc"}

    gasite = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in interzise:
            continue
        if fn.attr == "insert" and ast.unparse(fn.value) == "sys.path":
            continue
        gasite.append(f"linia {node.lineno}: {ast.unparse(fn)}(...)")

    assert not gasite, "apeluri de scriere interzise: " + "; ".join(gasite)
