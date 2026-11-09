"""Severitatea lui `check_data_health`: ce constatare COLOREAZA jobul.

DE CE EXISTA ACEST FISIER. Pana la 2026-11-09, `main()` intorcea
`1 if findings else 0`: ORICARE dintre cele 11 clase facea jobul rosu. Masurat
pe GitHub Actions, rularile 77-84: rosu 8 zile din 8, iar pe 8 noiembrie
trageau 5 clase, niciuna informatie noua. Un cod de iesire care nu se poate
schimba nu transporta informatie — iar clasa 10 (declansatorul D-15), singura a
carei constatare ar fi o veste care cere decizie umana, era inecata prin
constructie.

Reparatia copiaza tiparul deja dovedit la `night_sync` (2026-10-21): `critic`
implicit False, decizia intr-o functie PURA, procesul iese doar din `__main__`.

GARDA CENTRALA E AST, NU TEXT, si aici e OBLIGATORIU: blocul de severitate din
`check_data_health.py` contine, ca explicatie, chiar sirul
`1 if findings else 0`. O verificare textuala ar gasi exact comentariul care
documenteaza reparatia, iar „reparatia" evidenta ar fi stergerea explicatiei.
A NOUA instanta a clasei `pipefail`, dupa pipefail insusi (27 aug), numele de
secrete (14 oct), docstring-ul ADR-073, `decizie #` din app.py (20 oct),
`require_referee` (27 oct), comentariul TTL `events`, comentariul garzii
`/odds` (2 nov) si nota de eliminare `btts`. AST-ul ignora comentariile PRIN
CONSTRUCTIE — nu e o reparatie, e o imposibilitate.
"""
from __future__ import annotations

import ast
from pathlib import Path

from scripts.check_data_health import clase_critice, cod_de_iesire, constata

SURSA = Path(__file__).resolve().parent.parent / "scripts" / "check_data_health.py"

# 11 clase; majoritate = 6. Peste atat, mecanismul ar fi redevenit pe furis un
# `exit 1` global, adica exact boala reparata.
_TOTAL_CLASE = 11
_PRAG_MAJORITATE = 6


def _arbore() -> ast.Module:
    return ast.parse(SURSA.read_text(encoding="utf-8"))


def _apeluri_constata(arbore: ast.Module) -> list[ast.Call]:
    return [n for n in ast.walk(arbore)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "constata"]


# ── Functia pura ─────────────────────────────────────────────────────────────

def test_registru_gol_inseamna_verde():
    assert clase_critice([]) == []
    assert cod_de_iesire([]) == 0


def test_doar_constatari_necritice_lasa_jobul_verde():
    """Inima reparatiei: clasele cronice care trag NU mai coloreaza jobul.

    Exact situatia masurata pe 8 noiembrie (clasele 1, 4, 8, 9)."""
    registru = [(1, False), (4, False), (8, False), (9, False)]
    assert clase_critice(registru) == []
    assert cod_de_iesire(registru) == 0


def test_o_singura_clasa_critica_face_jobul_rosu():
    assert clase_critice([(10, True)]) == [10]
    assert cod_de_iesire([(10, True)]) == 1


def test_critica_bate_necriticele_oricate_ar_fi():
    registru = [(1, False), (4, False), (8, False), (9, False), (10, True)]
    assert clase_critice(registru) == [10]
    assert cod_de_iesire(registru) == 1


def test_clasele_critice_sunt_sortate_si_deduplicate():
    assert clase_critice([(11, True), (10, True), (11, True)]) == [10, 11]


def test_constata_e_necritic_IMPLICIT():
    """North Star #3 aplicat la ceva ce nu e flag de produs: o clasa noua
    adaugata fara sa se gandeasca nimeni la severitate NU poate inrosi jobul."""
    registru: list[tuple[int, bool]] = []
    constata(registru, 7)
    assert registru == [(7, False)]
    assert cod_de_iesire(registru) == 0


def test_constata_marcheaza_cand_i_se_cere_explicit():
    registru: list[tuple[int, bool]] = []
    constata(registru, 10, critic=True)
    assert registru == [(10, True)]
    assert cod_de_iesire(registru) == 1


def test_critic_fals_la_rulare_nu_coloreaza():
    """Clasa 11 paseaza `critic=bool(gol["delta_sync"])`, deci severitatea ei se
    decide LA RULARE. Sub-clasa `extragere` (reziduu ADR-076) trebuie sa lase
    jobul verde; doar `delta_sync` il inroseste."""
    registru: list[tuple[int, bool]] = []
    constata(registru, 11, critic=bool([]))          # doar `extragere`
    assert cod_de_iesire(registru) == 0
    registru.clear()
    constata(registru, 11, critic=bool(["un meci"]))  # `delta_sync` nevid
    assert cod_de_iesire(registru) == 1


# ── Garzi structurale, AST (vezi docstring-ul fisierului) ───────────────────

def test_niciun_findings_plus_plus_a_ramas_in_sursa():
    """Defectul original era `findings += 1`. Garda e pe AST: comentariul care
    explica reparatia conține chiar textul vechi."""
    arbore = _arbore()
    augmentari = [n for n in ast.walk(arbore)
                  if isinstance(n, ast.AugAssign)
                  and isinstance(n.target, ast.Name)
                  and n.target.id == "findings"]
    assert augmentari == [], (
        "`findings += 1` a reaparut — codul de iesire redevine `exit 1` global."
    )


def test_fiecare_clasa_raporteaza_exact_o_data():
    """Contrapondere: garda nu are voie sa treaca VID daca fisierul se goleste
    sau apelurile se redenumesc."""
    apeluri = _apeluri_constata(_arbore())
    assert len(apeluri) == _TOTAL_CLASE, (
        f"asteptam {_TOTAL_CLASE} apeluri `constata`, am gasit {len(apeluri)}"
    )
    numere = []
    for apel in apeluri:
        assert len(apel.args) == 2, "forma asteptata: constata(constatari, N)"
        numar = apel.args[1]
        assert isinstance(numar, ast.Constant) and isinstance(numar.value, int), (
            "numarul clasei trebuie sa fie un INTREG LITERAL, ca garda sa-l poata citi"
        )
        numere.append(numar.value)
    assert sorted(numere) == list(range(1, _TOTAL_CLASE + 1))


def test_clasele_critice_NU_devin_majoritare():
    """Garda care impiedica mecanismul sa redevina pe furis `exit 1` global.

    Se numara apelurile care pot fi critice LA RULARE: orice `critic=` care nu
    e literalmente `False`. Clasa 11 paseaza o expresie, nu `True`, deci o
    numaratoare pe `critic=True` ar rata-o."""
    potential_critice = 0
    for apel in _apeluri_constata(_arbore()):
        for kw in apel.keywords:
            if kw.arg != "critic":
                continue
            literal_fals = (isinstance(kw.value, ast.Constant)
                            and kw.value.value is False)
            if not literal_fals:
                potential_critice += 1
    assert 0 < potential_critice < _PRAG_MAJORITATE, (
        f"{potential_critice} din {_TOTAL_CLASE} clase pot colora jobul. "
        "Sub 1 = mecanismul e mort; peste jumatate = `exit 1` global deghizat. "
        "Largirea listei e o DECIZIE, nu o consecinta — cere aprobare."
    )


def test_clasa_10_si_clasa_11_sunt_cele_marcate():
    """Setul critic a fost ales pe datele de 8 noiembrie, nu presupus.
    Schimbarea lui trebuie sa fie vizibila, nu tacuta."""
    marcate = set()
    for apel in _apeluri_constata(_arbore()):
        for kw in apel.keywords:
            if kw.arg == "critic" and not (
                isinstance(kw.value, ast.Constant) and kw.value.value is False
            ):
                marcate.add(apel.args[1].value)
    assert marcate == {10, 11}


def test_clasa_11_decide_severitatea_LA_RULARE_nu_literal():
    """Clasa 11 NU are voie sa fie `critic=True` fix.

    Are doua sub-clase cu cauze si remedii OPUSE: `delta_sync` (0 randuri azi;
    un rand nou = regresie ADR-085, veste reala) si `extragere` (7 randuri azi,
    MLS septembrie, reziduul cunoscut al penei ADR-076). Marcata critic
    neconditionat, ar inrosi jobul zilnic pe reziduu — adica exact defectul
    reparat. Nicio alta garda din acest fisier nu prinde mutatia asta:
    `{10, 11}` ar ramane multimea marcata."""
    apel_11 = next(a for a in _apeluri_constata(_arbore())
                   if a.args[1].value == 11)
    kw = next(k for k in apel_11.keywords if k.arg == "critic")
    assert not isinstance(kw.value, ast.Constant), (
        "clasa 11 a devenit critica NECONDITIONAT — jobul redevine rosu zilnic "
        "pe reziduul `extragere`, care nu cere nicio decizie."
    )


def test_main_decide_prin_functia_pura_nu_prin_contor():
    """`main()` trebuie sa se termine cu `return cod_de_iesire(...)`.

    Se citeste ULTIMA INSTRUCTIUNE din corpul lui `main`, nu ultima returnare
    gasita de `ast.walk` — `walk` e BFS, deci nu da ordinea din sursa. Prima
    versiune a acestui test cadea exact din acest motiv, pe cod CORECT."""
    arbore = _arbore()
    main = next(n for n in ast.walk(arbore)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    ultima = main.body[-1]
    assert isinstance(ultima, ast.Return), "`main()` nu se termina cu return"
    assert (isinstance(ultima.value, ast.Call)
            and isinstance(ultima.value.func, ast.Name)
            and ultima.value.func.id == "cod_de_iesire"), (
        "`main()` nu mai delega decizia functiei pure — codul de iesire a fost "
        "recalculat inline, deci a devenit netestabil fara o rulare."
    )


def test_esecul_de_INFRASTRUCTURA_ramane_rosu():
    """Returnarile timpurii (`return 1`) trebuie PASTRATE.

    Daca verificarea nu poate rula deloc — fara client Supabase, fara date —
    raspunsul onest e ROSU, niciodata verde: „n-am putut verifica" nu e
    „totul e in ordine" (Regula #8). Relaxarea severitatii NU are voie sa
    transforme o imposibilitate de a masura intr-un succes."""
    arbore = _arbore()
    main = next(n for n in ast.walk(arbore)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    timpurii = [n for n in ast.walk(main)
                if isinstance(n, ast.Return) and n is not main.body[-1]]
    assert timpurii, "returnarile timpurii au disparut — un esec de infrastructura ar deveni VERDE"
    for nod in timpurii:
        assert isinstance(nod.value, ast.Constant) and nod.value.value == 1, (
            f"returnarea timpurie de la linia {nod.lineno} nu mai e 1 (rosu)"
        )


def test_procesul_iese_doar_din_main_dunder():
    """`main()` NU are voie sa apeleze `sys.exit`/`SystemExit` — altfel orice
    apelant programatic ar fi omorat. Aceeasi regula ca la `night_sync.run()`."""
    arbore = _arbore()
    main = next(n for n in ast.walk(arbore)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    for nod in ast.walk(main):
        if isinstance(nod, ast.Call):
            tinta = nod.func
            nume = (tinta.attr if isinstance(tinta, ast.Attribute)
                    else getattr(tinta, "id", ""))
            assert nume not in {"exit", "_exit", "SystemExit"}, (
                "`main()` omoara procesul; decizia apartine lui `__main__`."
            )
