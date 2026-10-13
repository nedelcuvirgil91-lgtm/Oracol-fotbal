"""Gardă: niciun constructor de cerere paginată nu se reutilizează între pagini.

CE APĂRĂ
`postgrest.BaseRPCRequestBuilder.range()` face `params.add("offset", …)` —
**adaugă**, nu înlocuiește — și mută `self`, întorcându-l. Deci un constructor
creat o singură dată ÎNAINTEA buclei și apelat repetat cu `.range()` acumulează
parametrii:

    offset=0&limit=1000
    offset=0&offset=1000&limit=1000&limit=1000
    offset=0&offset=1000&offset=2000&limit=1000&limit=1000&limit=1000

Găsit live pe 2026-10-13, în log-ul unei rulări `night_sync` reale: 24 de
perechi la offset=23000. Funcționa doar fiindcă PostgREST ia ULTIMUL parametru
duplicat — dacă l-ar lua pe primul, bucla ar reciti la nesfârșit pagina 0,
buclă infinită. Plus URL-ul creștea nelimitat.

DE CE O GARDĂ ȘI NU DOAR UN FIX
Era UNA singură din 14 locuri de paginare din proiect; celelalte 13
construiau deja cererea în buclă. Tiparul corect era deci cunoscut și aplicat
aproape peste tot — exact genul de regulă care se pierde la următoarea
adăugare, dacă nimic n-o impune.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import pathlib

PROIECT = pathlib.Path(__file__).resolve().parent.parent

# Rădăcini de lanț acceptate ca „proaspăt construit la fiecare apel":
# `client.table(...)`, `sb.table(...)`, `self._client.table(...)`.
_RADACINI_PROASPETE = {"client", "sb", "self"}


def _radacina_lantului(nod: ast.AST) -> ast.AST:
    """Coboară `a.b().c().d()` până la expresia de bază."""
    cur = nod
    while True:
        if isinstance(cur, ast.Call):
            cur = cur.func
        elif isinstance(cur, ast.Attribute):
            cur = cur.value
        else:
            return cur


def _fisiere_de_productie() -> list[pathlib.Path]:
    return [
        p for p in sorted(PROIECT.rglob("*.py"))
        if "__pycache__" not in str(p)
        and not str(p.relative_to(PROIECT)).startswith("tests/")
    ]


def _apeluri_range_pe_variabila() -> list[tuple[str, int, str]]:
    """Locurile unde `.range()` e apelat pe un NUME simplu, nu pe un lanț
    construit pe loc și nu pe rezultatul unei fabrici apelate."""
    gasite = []
    for cale in _fisiere_de_productie():
        try:
            arbore = ast.parse(cale.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for nod in ast.walk(arbore):
            if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)
                    and nod.func.attr == "range"):
                continue
            receptor = nod.func.value
            # `fabrica().range(...)` — constructor nou la fiecare apel, corect.
            if isinstance(receptor, ast.Call):
                continue
            radacina = _radacina_lantului(receptor)
            if isinstance(radacina, ast.Name) and radacina.id not in _RADACINI_PROASPETE:
                gasite.append((str(cale.relative_to(PROIECT)), nod.lineno, radacina.id))
    return gasite


def _nume_atribuite_in_bucla(arbore: ast.AST) -> set[tuple[int, str]]:
    """(linie_a_apelului_range, nume) pentru care numele e REATRIBUIT în
    interiorul aceleiași bucle care conține apelul — cazul corect."""
    sigure: set[tuple[int, str]] = set()
    for bucla in ast.walk(arbore):
        if not isinstance(bucla, (ast.While, ast.For)):
            continue
        atribuite = {
            t.id for n in ast.walk(bucla) if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)
        }
        for nod in ast.walk(bucla):
            if (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)
                    and nod.func.attr == "range"):
                radacina = _radacina_lantului(nod.func.value)
                if isinstance(radacina, ast.Name) and radacina.id in atribuite:
                    sigure.add((nod.lineno, radacina.id))
    return sigure


def test_niciun_constructor_paginat_nu_e_reutilizat_intre_pagini():
    """GARDA CENTRALĂ.

    Un `.range()` pe o variabilă e acceptabil DOAR dacă variabila e
    reatribuită în interiorul aceleiași bucle — adică reconstruită la fiecare
    pagină. Altfel, parametrii se acumulează tăcut."""
    incalcari = []
    for cale_rel, linie, nume in _apeluri_range_pe_variabila():
        arbore = ast.parse((PROIECT / cale_rel).read_text(encoding="utf-8"))
        if (linie, nume) not in _nume_atribuite_in_bucla(arbore):
            incalcari.append(f"{cale_rel}:{linie} — `.range()` pe `{nume}`, "
                             f"neconstruit în bucla care îl folosește")
    assert not incalcari, (
        "Constructor de cerere reutilizat între pagini — `.range()` ADAUGĂ "
        "`offset`/`limit`, nu îi înlocuiește:\n  " + "\n  ".join(incalcari))


def test_detectorul_chiar_prinde_tiparul_gresit(tmp_path):
    """CONTRAPONDERE — fără ea, garda de mai sus ar putea trece fiindcă nu
    găsește nimic, nu fiindcă totul e corect. Construiește defectul explicit
    și verifică faptul că e raportat."""
    gresit = tmp_path / "gresit.py"
    gresit.write_text(
        "def f(client):\n"
        "    q = client.table('t').select('*')\n"
        "    offset = 0\n"
        "    while True:\n"
        "        res = q.range(offset, offset + 999).execute()\n"
        "        offset += 1000\n", encoding="utf-8")
    arbore = ast.parse(gresit.read_text(encoding="utf-8"))
    apeluri = [n for n in ast.walk(arbore)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "range"]
    assert len(apeluri) == 1
    assert (apeluri[0].lineno, "q") not in _nume_atribuite_in_bucla(arbore), \
        "detectorul NU prinde constructorul reutilizat — garda e oarbă"


def test_detectorul_accepta_reconstructia_in_bucla(tmp_path):
    """Contrapondere în cealaltă direcție: tiparul CORECT nu trebuie raportat,
    altfel garda ar deveni zgomot și s-ar dezactiva."""
    corect = tmp_path / "corect.py"
    corect.write_text(
        "def f(client):\n"
        "    offset = 0\n"
        "    while True:\n"
        "        q = client.table('t').select('*')\n"
        "        res = q.range(offset, offset + 999).execute()\n"
        "        offset += 1000\n", encoding="utf-8")
    arbore = ast.parse(corect.read_text(encoding="utf-8"))
    apeluri = [n for n in ast.walk(arbore)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "range"]
    assert (apeluri[0].lineno, "q") in _nume_atribuite_in_bucla(arbore)


def test_exista_locuri_de_paginare_de_verificat():
    """Dacă proiectul n-ar mai avea niciun `.range()`, garda ar trece VID și
    nimeni n-ar observa că nu mai apără nimic."""
    total = 0
    for cale in _fisiere_de_productie():
        try:
            arbore = ast.parse(cale.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        total += sum(1 for n in ast.walk(arbore)
                     if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "range")
    assert total >= 10, f"doar {total} apeluri `.range()` găsite — garda pare oarbă"
