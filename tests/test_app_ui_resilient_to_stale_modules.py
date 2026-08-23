"""Gardă anti-regresie pentru incidentul live din 2026-08-23 (ADR-062).

CE S-A ÎNTÂMPLAT: după deploy-ul ADR-062, aplicația live a căzut cu
`ImportError` pe `from database.queries import (TEAM_PROFILE_TEST_THRESHOLD,
TEAM_PROFILE_WINDOW)`, deși ambele simboluri existau corect în codul
comis pe `main` (verificat).

CAUZA REALĂ: Streamlit re-execută `app.py` la hot-reload, dar NU reimportă
modulele deja aflate în `sys.modules`. `database.queries` intră acolo la
pornirea procesului (prin `oracle_engine.py`, import la nivel de modul).
Deci noul `app.py` cerea un simbol NOU de la versiunea VECHE, cache-uită, a
modulului. Se rezolvă la un restart complet — dar până atunci întreg cardul
de meci se prăbușea, pentru o bară de progres a unui experiment NEPROMOVAT.

REGULA IMPUSĂ AICI: constantele Team Profile nu se importă prin
`from database.queries import <CONSTANTA>` în `app.py` — se citesc prin
`getattr(modul, ..., implicit)`, ca un modul învechit să degradeze grațios
în loc să arunce. Fără rețea, fără Streamlit — analiză AST pură.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parent.parent / "app.py"

# Constante care au fost adăugate DUPĂ ce app.py rula deja în producție —
# exact clasa de simboluri vulnerabile la un modul învechit în sys.modules.
_FRAGILE_NAMES = {"TEAM_PROFILE_WINDOW", "TEAM_PROFILE_TEST_THRESHOLD"}


def _tree() -> ast.AST:
    return ast.parse(APP.read_text(encoding="utf-8"), filename=str(APP))


def test_app_nu_importa_direct_constantele_team_profile():
    """`from database.queries import TEAM_PROFILE_*` e interzis în app.py —
    un `database.queries` învechit în sys.modules ar arunca ImportError și ar
    dărâma randarea întregului card de meci (incident real, 2026-08-23)."""
    offenders = []
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if module.split(".")[-1] != "queries":
            continue
        for alias in node.names:
            if alias.name in _FRAGILE_NAMES:
                offenders.append(f"linia {node.lineno}: from {module} import {alias.name}")

    assert offenders == [], (
        "Constantele Team Profile trebuie citite prin getattr(modul, ..., implicit), "
        "nu importate direct — vezi antetul acestui fișier:\n  " + "\n  ".join(offenders)
    )


def test_app_citeste_constantele_prin_getattr_cu_implicit():
    """Complementul pozitiv: constantele chiar SUNT citite prin getattr cu
    o valoare implicită (nu doar 'nu sunt importate direct')."""
    source = APP.read_text(encoding="utf-8")
    for name in _FRAGILE_NAMES:
        assert f'getattr(_dbq, "{name}"' in source, (
            f"{name} ar trebui citit prin getattr(_dbq, \"{name}\", <implicit>) în app.py"
        )

    # si fiecare getattr are exact 3 argumente (deci o valoare implicita)
    for node in ast.walk(_tree()):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"):
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.Constant):
            continue
        if node.args[1].value in _FRAGILE_NAMES:
            assert len(node.args) == 3, (
                f"getattr pentru {node.args[1].value} (linia {node.lineno}) nu are valoare "
                "implicita — ar arunca AttributeError pe un modul invechit"
            )


def test_blocul_team_profile_e_invelit_in_try_except():
    """Indicatorul e pentru un experiment NEPROMOVAT — nu are voie, in niciun
    scenariu, sa dărâme randarea cardului de meci. Verifica structural ca
    apelul `_finishing_data_readiness()` se afla in interiorul unui `try`."""
    inside_try = False
    for node in ast.walk(_tree()):
        if not isinstance(node, ast.Try):
            continue
        for sub in ast.walk(node):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id == "_finishing_data_readiness"):
                inside_try = True
                break
        if inside_try:
            break

    assert inside_try, (
        "_finishing_data_readiness() trebuie apelat in interiorul unui try/except — "
        "altfel un esec al indicatorului dărâmă tot cardul de meci"
    )
