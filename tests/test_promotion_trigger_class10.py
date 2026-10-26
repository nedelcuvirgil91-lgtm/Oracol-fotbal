"""[D-15] Clasa 10 din `check_data_health` — declanșatorul de servire.

APROBAT 2026-10-26: 3/3 pe 10 zile de evaluare consecutive ȘI n ≥ 500.

DE CE E CABLAT, nu lăsat în document: ADR-057 a trăit exact așa, iar condiția
lui s-a împlinit pe 23 august și a fost descoperită pe 6 septembrie — 14 zile
fără nicio antrenare. Clasa 10 e reparația acelei clase de eșec.

Toată judecata stă într-o funcție PURĂ (`serie_3_din_3`), deci testele de aici
nu ating Supabase și nu cer o rulare de noapte. Cele patru convenții aprobate
sunt fiecare păzite separat, fiindcă fiecare a fost aleasă împotriva unei
alternative plauzibile:

  1. mai multe rânduri pe aceeași zi  -> contează ULTIMUL
  2. zile LIPSĂ                        -> neutre, dar peste 2 seria e suspectă
  3. orice zi sub 3/3                  -> RESETEAZĂ la zero
  4. n ≥ 500                           -> pe ULTIMA zi a seriei
"""
from __future__ import annotations

import ast
from datetime import date, timedelta
from pathlib import Path

import pytest

from scripts.check_data_health import (_MAX_ZILE_LIPSA_IN_SERIE,
                                       _PRAG_N_DECLANSATOR,
                                       _PRAG_ZILE_3_DIN_3, serie_3_din_3)

RADACINA = Path(__file__).resolve().parent.parent
BAZA = date(2026, 10, 25)


def _rand(zi_offset: int, *, sem: int = 3, n: int = 600,
          familie: str = "xgboost_v1", run: str = "dda4f7f3-aaaa",
          ora: str = "08:00:00") -> dict:
    """Un rând de evaluare. `sem` = câte metrici sunt semnificative."""
    zi = BAZA - timedelta(days=zi_offset)
    flags = [True] * sem + [False] * (3 - sem)
    return {
        "algorithm_family": familie, "training_run_id": run,
        "evaluated_at": f"{zi.isoformat()}T{ora}+00:00",
        "n_matches_evaluated": n,
        "accuracy_significant": flags[0],
        "brier_significant": flags[1],
        "logloss_significant": flags[2],
    }


def _unul(randuri):
    rez = serie_3_din_3(randuri)
    assert len(rez) == 1, f"asteptam un singur challenger, am {len(rez)}"
    return rez[0]


# ──────────────────────────────────────────────────────────────────────
# Declanșarea propriu-zisă
# ──────────────────────────────────────────────────────────────────────

def test_zece_zile_3_din_3_si_n_mare_DECLANSEAZA():
    s = _unul([_rand(i) for i in range(10)])
    assert s["serie"] == 10
    assert s["declansat"] is True


def test_noua_zile_NU_declanseaza():
    """Granița: pragul e `>=`, deci 9 nu trece. Un test la 10 singur n-ar
    distinge `>= 10` de `>= 9`."""
    s = _unul([_rand(i) for i in range(9)])
    assert s["serie"] == 9
    assert s["declansat"] is False


def test_serie_lunga_dar_n_SUB_prag_nu_declanseaza():
    """Convenția 4 — ambele condiții, nu una. La n mic o singură rundă poate
    inversa semnul; demonstrat pe 25 oct, ambii Challengeri."""
    s = _unul([_rand(i, n=499) for i in range(15)])
    assert s["serie"] == 15
    assert s["n_curent"] == 499
    assert s["declansat"] is False


def test_n_se_citeste_pe_ULTIMA_zi_nu_pe_prima():
    """Convenția 4, explicit: `n` crește monoton, deci constrângerea care
    leagă e pe ziua cea mai recentă. O citire pe prima zi a seriei ar folosi
    cel mai mic `n` și n-ar declanșa niciodată."""
    randuri = [_rand(i, n=600 - i * 20) for i in range(10)]  # azi 600, acum 10 zile 420
    s = _unul(randuri)
    assert s["n_curent"] == 600
    assert s["declansat"] is True


# ──────────────────────────────────────────────────────────────────────
# Convenția 3 — orice zi sub 3/3 resetează
# ──────────────────────────────────────────────────────────────────────

def test_o_zi_sub_3_din_3_RESETEAZA_seria_la_zero():
    """Cazul real din 25 oct: 23-24 oct erau 3/3, 25 oct a rupt. Seria
    CURENTĂ e 0, nu 2 — iar distincția a produs deja o cifră raportată greșit."""
    randuri = [_rand(0, sem=2)] + [_rand(i) for i in range(1, 12)]
    s = _unul(randuri)
    assert s["serie"] == 0
    assert s["sem_ultima_zi"] == 2
    assert s["declansat"] is False


def test_ruptura_la_mijloc_taie_seria_acolo():
    randuri = ([_rand(i) for i in range(4)] + [_rand(4, sem=1)]
               + [_rand(i) for i in range(5, 20)])
    s = _unul(randuri)
    assert s["serie"] == 4, "seria se numără de la ziua recentă până la prima rupere"
    assert s["declansat"] is False


def test_seriile_NU_se_cumuleaza_peste_rupere():
    """4 zile bune + rupere + 20 de zile bune nu fac 24."""
    randuri = ([_rand(i) for i in range(4)] + [_rand(4, sem=0)]
               + [_rand(i) for i in range(5, 25)])
    assert _unul(randuri)["serie"] == 4


# ──────────────────────────────────────────────────────────────────────
# Convenția 1 — mai multe rânduri pe aceeași zi
# ──────────────────────────────────────────────────────────────────────

def test_doua_randuri_in_aceeasi_zi_castiga_ULTIMUL():
    """S-a întâmplat pe 17 oct pentru `174e7e17` — două evaluări, aceeași zi.
    Dacă ar câștiga primul, o zi reparată mai târziu ar rămâne raportată ca
    ruptă."""
    randuri = [_rand(0, sem=0, ora="06:00:00"), _rand(0, sem=3, ora="09:00:00")]
    randuri += [_rand(i) for i in range(1, 10)]
    s = _unul(randuri)
    assert s["sem_ultima_zi"] == 3
    assert s["serie"] == 10


def test_ultimul_rand_al_zilei_poate_si_RUPE_seria():
    """Simetric — convenția nu e „câștigă cel mai bun", e „câștigă ultimul"."""
    randuri = [_rand(0, sem=3, ora="06:00:00"), _rand(0, sem=1, ora="09:00:00")]
    randuri += [_rand(i) for i in range(1, 10)]
    assert _unul(randuri)["serie"] == 0


# ──────────────────────────────────────────────────────────────────────
# Convenția 2 — zile lipsă
# ──────────────────────────────────────────────────────────────────────

def test_doua_zile_lipsa_sunt_NEUTRE_si_seria_declanseaza():
    """Dacă `night_sync` a eșuat, modelul nu s-a înrăutățit — doar nu ne-am
    uitat. Golurile mici nu resetează."""
    offsets = [0, 1, 2, 4, 5, 6, 8, 9, 10, 11]   # lipsesc 3 și 7
    s = _unul([_rand(i) for i in offsets])
    assert s["serie"] == 10
    assert s["zile_lipsa"] == 2
    assert s["suspecta"] is False
    assert s["declansat"] is True


def test_peste_prag_zile_lipsa_face_seria_SUSPECTA_si_NU_declanseaza():
    """Altfel o pană prelungită ar putea «conserva» o serie bună peste o
    perioadă în care nu ne-am uitat deloc."""
    offsets = [0, 1, 2, 3, 4, 10, 11, 12, 13, 14]  # 5 zile lipsă în mijloc
    s = _unul([_rand(i) for i in offsets])
    assert s["serie"] == 10
    assert s["zile_lipsa"] > _MAX_ZILE_LIPSA_IN_SERIE
    assert s["suspecta"] is True
    assert s["declansat"] is False, "serie suspectă nu are voie să declanșeze"


# ──────────────────────────────────────────────────────────────────────
# Robustețe / Regula #8
# ──────────────────────────────────────────────────────────────────────

def test_lista_goala_nu_arunca():
    assert serie_3_din_3([]) == []


def test_camp_de_semnificatie_LIPSA_conteaza_ca_nesemnificativ():
    """Regula #8 — necunoscutul nu se aproximează. Și direcția conservatoare
    e cea corectă: greșeala ieftină e să NU declanșezi."""
    rand = _rand(0)
    del rand["brier_significant"]
    s = _unul([rand] + [_rand(i) for i in range(1, 12)])
    assert s["sem_ultima_zi"] == 2
    assert s["serie"] == 0


def test_null_in_loc_de_True_conteaza_ca_nesemnificativ():
    rand = _rand(0)
    rand["brier_significant"] = None
    assert _unul([rand] + [_rand(i) for i in range(1, 12)])["serie"] == 0


def test_data_corupta_e_sarita_nu_arunca():
    rau = _rand(0)
    rau["evaluated_at"] = "nu-e-o-data"
    s = _unul([rau] + [_rand(i) for i in range(1, 11)])
    assert s["serie"] == 10


def test_challengeri_diferiti_sunt_SEPARATI():
    randuri = ([_rand(i, familie="xgboost_v1", run="aaa") for i in range(10)]
               + [_rand(i, familie="blend_v1", run="bbb", sem=2) for i in range(10)])
    rez = serie_3_din_3(randuri)
    assert len(rez) == 2
    pe_run = {r["training_run_id"]: r for r in rez}
    assert pe_run["aaa"]["declansat"] is True
    assert pe_run["bbb"]["serie"] == 0


# ──────────────────────────────────────────────────────────────────────
# Gărzi structurale
# ──────────────────────────────────────────────────────────────────────

def _sursa(nume: str) -> str:
    return (RADACINA / nume).read_text(encoding="utf-8")


def _corpul_fara_docstring(nume_fisier: str, nume_functie: str) -> list:
    """Corpul unei funcții FĂRĂ docstring-ul ei.

    Există pentru că o gardă textuală care caută un șir în fișier îl găsește
    și în documentația care EXPLICĂ acel șir. S-a întâmplat exact aici: o
    mutație care ștergea filtrul de familii de test a TRECUT, fiindcă
    `"gate_validation"` supraviețuia în docstring. Clasa `pipefail`, a cincea
    instanță în proiect."""
    arbore = ast.parse(_sursa(nume_fisier))
    fn = next(n for n in ast.walk(arbore)
              if isinstance(n, ast.FunctionDef) and n.name == nume_functie)
    corp = list(fn.body)
    if (corp and isinstance(corp[0], ast.Expr)
            and isinstance(corp[0].value, ast.Constant)
            and isinstance(corp[0].value.value, str)):
        corp = corp[1:]          # scoate docstring-ul
    return corp


def test_familiile_de_test_sunt_excluse_la_SURSA():
    """Cele 5 artefacte `gate_validation_test` din 14 iulie (n = 250) nu pot
    declanșa azi, dar suprafața de fals pozitiv se închide explicit.

    [ÎNTĂRITĂ] Verifică CODUL, nu fișierul: prima versiune trecea cu filtrul
    șters, fiindcă șirul rămânea în docstring."""
    corp = _corpul_fara_docstring("database/queries.py",
                                  "get_challenger_significance_days")
    text = " ".join(ast.dump(n) for n in corp)
    assert "gate_validation" in text, \
        "filtrul de familii de test a dispărut din COD (docstring-ul nu contează)"


def test_interogarea_e_PAGINATA():
    """Plafonul implicit PostgREST de 1000 e clasa cu PATRU instanțe
    documentate în proiect. `challenger_evaluations` crește cu ~2 rânduri/zi și
    va trece pragul; atunci seria ar fi calculată pe un subset ales de bază.

    [ÎNTĂRITĂ] Prima versiune cerea doar ca `_PAGE_SIZE` și un `while` să
    EXISTE undeva în funcție — și a trecut cu `.limit(_PAGE_SIZE)` șters,
    fiindcă `_PAGE_SIZE` supraviețuia în comparația de oprire. Verifica cele
    două capete și nu firul dintre ele, exact ca mutația M5 de la raportul
    `night_sync`. Acum cere legătura: un apel `.limit()` cu chiar acea
    constantă ca argument."""
    corp = _corpul_fara_docstring("database/queries.py",
                                  "get_challenger_significance_days")
    bucle = [n for c in corp for n in ast.walk(c) if isinstance(n, ast.While)]
    assert bucle, "paginarea trebuie să fie o buclă, nu un singur select"
    limite = [n for c in corp for n in ast.walk(c)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "limit"
              and any(isinstance(a, ast.Name) and a.id == "_PAGE_SIZE"
                      for a in n.args)]
    assert limite, "lipsește `.limit(_PAGE_SIZE)` — cererea nu e mărginită"


def test_la_eroare_se_intoarce_None_nu_lista_goala():
    """Un `[]` pe eroare ar arăta identic cu «niciun Challenger evaluat» —
    adică exact cu starea în care declanșatorul nu poate fi atins."""
    arbore = ast.parse(_sursa("database/queries.py"))
    fn = next(n for n in ast.walk(arbore)
              if isinstance(n, ast.FunctionDef)
              and n.name == "get_challenger_significance_days")
    handlere = [h for h in ast.walk(fn) if isinstance(h, ast.ExceptHandler)]
    assert handlere, "lipsește tratarea erorii"
    for h in handlere:
        returns = [r for r in ast.walk(h) if isinstance(r, ast.Return)]
        assert returns, "handler fără return"
        for r in returns:
            assert isinstance(r.value, ast.Constant) and r.value.value is None, \
                "la eroare trebuie None (NECUNOSCUT), nu [] (sănătos)"


def test_detectorul_e_READ_ONLY():
    """Clasa 10 raportează; nu repară, nu promovează, nu scrie.

    [ÎNTĂRITĂ] Prima versiune căuta `"insert("` ca TEXT și a căzut pe
    `sys.path.insert(0, ...)` — un apel legitim, fără nicio legătură cu baza.
    Aceeași clasă ca garda `pipefail`, care își găsea propriul comentariu: o
    potrivire de text nu știe despre ce obiect vorbește. AST-ul știe —
    verificăm numele metodei ȘI receptorul."""
    arbore = ast.parse(_sursa("scripts/check_data_health.py"))
    SCRIERI = {"insert", "upsert", "update", "delete", "promote_challenger",
               "propose_decision", "approve_decision"}
    gasite = []
    for nod in ast.walk(arbore):
        if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)):
            continue
        if nod.func.attr not in SCRIERI:
            continue
        receptor = ast.unparse(nod.func.value)
        if receptor == "sys.path":        # `sys.path.insert` — listă, nu bază
            continue
        gasite.append(f"{receptor}.{nod.func.attr}()")
    assert not gasite, f"detectorul nu are voie să scrie: {gasite}"


def test_pragurile_sunt_CONSTANTE_nu_literale_in_raport():
    """Dacă proprietarul schimbă declanșatorul, se schimbă într-un loc."""
    arbore = ast.parse(_sursa("scripts/check_data_health.py"))
    fn = next(n for n in ast.walk(arbore)
              if isinstance(n, ast.FunctionDef) and n.name == "serie_3_din_3")
    text = ast.dump(fn)
    assert "_PRAG_ZILE_3_DIN_3" in text and "_PRAG_N_DECLANSATOR" in text
    for literal in (10, 500):
        assert f"value={literal}" not in text, \
            f"pragul {literal} e scris ca literal în loc de constantă"


def test_raportul_numara_zece_clase():
    assert "{findings}/10" in _sursa("scripts/check_data_health.py")


def test_constatarea_se_numara_DOAR_la_declansare():
    """Seria se AFIȘEAZĂ mereu (avertisment din timp), dar nu colorează
    raportul decât la declanșare — altfel clasa ar fi roșie în fiecare zi în
    care un Challenger e la 3/3 de câteva zile, adică exact boala
    «roșu-mereu te antrenează să ignori» deja documentată la acest script."""
    sursa = _sursa("scripts/check_data_health.py")
    # [ÎNTĂRITĂ] Ancora „CLASA 10" apare de DOUĂ ori (comentariul funcției pure
    # + secțiunea din raport), deci `index()` prindea tot fișierul și număra
    # toate cele 10 incrementări. Ancorăm pe linia de raport, care e unică.
    i = sursa.index('print("  10. DECLANȘATOR DE SERVIRE')
    bloc = sursa[i:sursa.index("Clase cu constatări")]
    assert bloc.count("findings += 1") == 1, \
        f"clasa 10 incrementează de {bloc.count('findings += 1')} ori"
    pozitie_declansati = bloc.index("if declansati:")
    assert pozitie_declansati < bloc.index("findings += 1"), \
        "incrementul trebuie să fie în interiorul ramurii de declanșare"


def test_pragurile_aprobate_nu_s_au_schimbat_tacit():
    """Declanșatorul e o decizie aprobată explicit (D-15). O schimbare a lui
    cere o decizie nouă, nu o editare."""
    assert _PRAG_ZILE_3_DIN_3 == 10
    assert _PRAG_N_DECLANSATOR == 500
    assert _MAX_ZILE_LIPSA_IN_SERIE == 2
