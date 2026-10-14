"""Gardă: niciun test nu are voie să fie ȘTERS TĂCUT de un omonim.

DE CE EXISTĂ — o eroare reală, 2026-10-14
Adăugând gărzile pentru D-10 în `tests/test_shadow_pagination.py`, am scris
două funcții cu nume deja folosite în ACELAȘI fișier
(`test_o_singura_pagina_nu_cere_a_doua_degeaba`,
`test_supabase_indisponibil_intoarce_lista_goala`). Python păstrează doar
ULTIMA definiție a unui nume, deci cele două gărzi existente — care verificau
`get_shadow_predictions()` — au dispărut din suită, iar ale mele le-au luat
locul verificând cu totul altceva (`get_distinct_experiments()`).

**Suita a rămas VERDE tot timpul.** `pytest` nu are de unde să știe că o
funcție a fost suprascrisă: vede un singur obiect și îl rulează. Nicio
eroare, niciun avertisment, nicio diferență vizibilă într-un raport
`N passed`.

CUM A IEȘIT LA IVEALĂ: din aritmetică, nu dintr-un eșec. Fișierul crescuse cu
10 teste, dar totalul suitei doar cu 8 (3427 -> 3435). Diferența de 2 era
exact numărul de gărzi șterse. Dacă adăugam 10 teste într-un fișier și nu
comparam cu totalul, pierderea trecea complet neobservată — iar cele două
gărzi ar fi rămas „prezente" în cod, vizibile la citire, dar nerulate
NICIODATĂ.

E aceeași familie cu lecțiile deja plătite în proiect, unde verificarea
exista dar nu verifica: garda `pipefail` care își găsea propriul comentariu
(2026-08-27), garda de izolare POC care își găsea propriul docstring
(2026-10-14), și testul de zero cost pe care `except Exception` îl anula
(2026-10-14). Acolo garda era oarbă; aici garda nici nu mai exista.

CE APĂRĂ
  1. Niciun fișier din `tests/` nu conține două funcții `test_*` cu același
     nume la nivel de modul.
  2. Nicio clasă de test nu conține două metode `test_*` cu același nume.
  3. Contrapondere: dacă folderul s-ar goli sau redenumi, garda ar trece VIDĂ.

Nu interzice același nume în FIȘIERE diferite — acolo nu există suprascriere,
iar numele descriptive se repetă legitim între module.

Prin AST, nu prin regex: un `def test_x` dintr-un docstring sau dintr-un șir
nu e o definiție, iar o gardă textuală l-ar număra.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import collections
import pathlib

TESTE = pathlib.Path(__file__).resolve().parent


def _fisiere() -> list[pathlib.Path]:
    return sorted(TESTE.glob("test_*.py"))


def _nume_duplicate(corp: list[ast.stmt]) -> list[str]:
    """Numele `test_*` definite de mai multe ori în ACELAȘI corp.

    Doar corpul direct, fără recursivitate în funcții imbricate: un helper
    definit în interiorul unui test nu intră în coliziune cu nimic.
    """
    nume = [
        n.name for n in corp
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name.startswith("test_")
    ]
    return sorted(n for n, k in collections.Counter(nume).items() if k > 1)


def test_niciun_test_nu_e_suprascris_de_un_omonim():
    """GARDA CENTRALĂ. Un test suprascris dispare din suită fără niciun semnal."""
    incalcari: list[str] = []
    for p in _fisiere():
        try:
            arbore = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as exc:
            incalcari.append(f"{p.name}: nu se parsează ({exc})")
            continue

        for dup in _nume_duplicate(arbore.body):
            incalcari.append(f"{p.name}: `{dup}` definit de mai multe ori la nivel de modul")

        for nod in arbore.body:
            if isinstance(nod, ast.ClassDef):
                for dup in _nume_duplicate(nod.body):
                    incalcari.append(f"{p.name}::{nod.name}: `{dup}` definit de mai multe ori")

    assert not incalcari, (
        "Teste șterse tăcut de un omonim — Python păstrează doar ultima "
        "definiție, iar suita rămâne VERDE în timp ce garda a dispărut. "
        "Redenumește, nu șterge:\n  " + "\n  ".join(incalcari))


def test_detectorul_chiar_prinde_un_omonim():
    """CONTRAPONDERE — construiește exact defectul din 14 octombrie.

    Fără ea, garda de mai sus ar putea trece fiindcă `_nume_duplicate` are un
    bug, nu fiindcă totul e curat."""
    rau = ast.parse(
        "def test_a():\n    pass\n"
        "def test_b():\n    pass\n"
        "def test_a():\n    pass\n"
    )
    assert _nume_duplicate(rau.body) == ["test_a"]

    bun = ast.parse(
        "def test_a():\n    def test_ajutor():\n        pass\n    pass\n"
        "def test_b():\n    def test_ajutor():\n        pass\n    pass\n"
    )
    assert _nume_duplicate(bun.body) == [], (
        "helperele imbricate cu acelasi nume NU sunt coliziuni — nu se suprascriu")

    intr_o_clasa = ast.parse(
        "class TestX:\n    def test_a(self):\n        pass\n"
        "    def test_a(self):\n        pass\n"
    )
    assert _nume_duplicate(intr_o_clasa.body[0].body) == ["test_a"]


def test_exista_fisiere_de_verificat():
    """Dacă folderul s-ar goli sau redenumi, garda de mai sus ar trece VIDĂ
    și nimeni n-ar observa că nu mai apără nimic."""
    n = len(_fisiere())
    assert n >= 100, f"doar {n} fișiere de test găsite în {TESTE} — garda pare oarbă"
