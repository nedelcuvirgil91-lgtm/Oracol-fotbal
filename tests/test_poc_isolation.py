"""Gardă: niciun POC nu poate scrie nicăieri — impus, nu promis.

DE CE EXISTĂ
Proiectul folosește POC-uri izolate, temporare, pentru a valida o sursă sau o
cheie nouă înainte de orice integrare (regula din CLAUDE.md §chei API, aplicată
de 5 ori: API-Football, SofaScore, Transfermarkt ×3). Regula cere ca POC-ul să
nu importe modulele de producție și să nu fie infrastructură vie.

Până azi, respectarea ei se verifica **manual**, de fiecare dată, de mine. Pe
2026-10-14 proprietarul produsului a întrebat de două ori, pe bună dreptate,
„asta afectează predicțiile?" — iar răspunsul se sprijinea pe o verificare
ad-hoc pe care o rulam și o raportam. O garanție care depinde de disciplina
cuiva nu e o garanție.

CE APĂRĂ
  1. Niciun `_poc_*.py` nu importă un modul care știe să scrie în Supabase.
     Fără import, funcția de scriere nu există în memoria procesului.
  2. Niciun `_poc_*.py` nu conține apeluri de scriere (`upsert`, `.insert(`,
     `.update(`, `.delete(`, `execute_sql`, `rpc(`).
  3. Niciun `_poc_*.py` nu citează numele unui secret de bază de date.
  4. Niciun workflow care rulează un `_poc_*` nu îi dă secrete Supabase —
     deci chiar dacă primele trei ar fi ocolite, scrierea ar eșua.

DE CE CONTEAZĂ CONCRET, pentru accidentări
Verificat în `oracle_engine.py`: există EXACT o cale prin care date de
accidentări ating o predicție — `freelf_lineup_snapshot` ->
`get_freelf_lineup_snapshot()` (linia 1810) -> `apply_injury_penalty()` ->
`home_xg`/`away_xg` -> Poisson. Singurii scriitori ai tabelei sunt
`freelf_lineup_adapter.py` și `database/queries.py`. Un POC care nu îi importă
nu poate schimba nicio predicție — iar garda asta o impune.

CONTRAPONDEREA E DIFERITĂ DE CELELALTE GĂRZI DIN PROIECT
În mod normal un test „verifică faptul că există ce verific" (ex.
`test_exista_workflow_uri_de_verificat`). Aici ar fi GREȘIT: POC-urile se ȘTERG
după închiderea investigației, deci **zero POC-uri e starea normală**, nu un
semn de gardă oarbă. Contraponderea corectă e un fișier sintetic cu defectul
construit explicit, verificat la fiecare rulare.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

PROIECT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS = PROIECT / ".github" / "workflows"

# Module care stiu sa scrie in Supabase, direct sau prin tranzitivitate.
MODULE_DE_SCRIERE = {
    "supabase_client", "database", "freelf_lineup_adapter", "oracle_engine",
    "injury_manager", "supabase", "oracle_api", "key_manager", "app",
    "shadow_testing", "automation_runs",
}

# Metode fara coliziune cu tipurile native: orice aparitie e scriere.
_SCRIERE_NEAMBIGUA = {"upsert", "rpc", "execute_sql"}
# Metode care EXISTA si pe list/dict — se raporteaza doar daca lantul de apel
# trece printr-un `.table(...)`, adica e un query Supabase, nu `list.insert()`.
_SCRIERE_AMBIGUA = {"insert", "update", "delete"}

NUME_DE_SECRETE = ("SUPABASE_URL", "SUPABASE_SECRET_KEY", "SUPABASE_KEY")


def _fisiere_poc() -> list[pathlib.Path]:
    """DOAR POC-urile izolate, temporare, din radacina — `_poc_*.py`.

    SCOP DELIBERAT RESTRANS, dupa ce prima versiune a acestei garzi a cazut pe
    realitate. `sync/poc_*.py` (23 de fisiere) sunt scripturi de DIAGNOSTIC
    istorice, care aveau voie sa importe module de productie: rulau analize pe
    datele noastre, nu validau o sursa externa noua. Regula stricta de izolare
    din CLAUDE.md §chei API se aplica POC-urilor care valideaza o cheie sau un
    provider nou — exact clasa `_poc_*_temp.py` din radacina.

    A impune regula retroactiv pe 23 de scripturi care n-au fost scrise sub ea
    ar fi transformat garda in zgomot, iar o garda zgomotoasa se dezactiveaza.
    """
    return sorted(PROIECT.glob("_poc_*.py"))


def _apeluri_de_scriere(sursa: str) -> list[str]:
    """Detectie prin AST, nu prin cautare de text.

    Prima versiune cauta sirul `.insert(` si a raportat 23 de fisiere — toate
    pentru `sys.path.insert(0, str(root))`, boilerplate standard de script.
    Un fals pozitiv atat de gros ar fi facut garda inutilizabila din prima zi.
    """
    try:
        arbore = ast.parse(sursa)
    except SyntaxError:
        return []
    gasite: list[str] = []
    for nod in ast.walk(arbore):
        if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)):
            continue
        metoda = nod.func.attr
        if metoda in _SCRIERE_NEAMBIGUA:
            gasite.append(f"{metoda}() la linia {nod.lineno}")
        elif metoda in _SCRIERE_AMBIGUA:
            # Lantul contine `.table(...)`? Atunci e query Supabase.
            cur = nod.func.value
            while isinstance(cur, (ast.Call, ast.Attribute)):
                if isinstance(cur, ast.Call) and isinstance(cur.func, ast.Attribute) \
                        and cur.func.attr == "table":
                    gasite.append(f"{metoda}() pe .table() la linia {nod.lineno}")
                    break
                cur = cur.func if isinstance(cur, ast.Call) else cur.value
    return gasite


def _importuri(sursa: str) -> set[str]:
    try:
        arbore = ast.parse(sursa)
    except SyntaxError:
        return set()
    gasite: set[str] = set()
    for n in ast.walk(arbore):
        if isinstance(n, ast.Import):
            gasite.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.module:
            gasite.add(n.module.split(".")[0])
    return gasite


def test_niciun_poc_nu_importa_module_de_scriere():
    """GARDA 1. Fara import, functia de scriere nu exista in proces."""
    incalcari = []
    for p in _fisiere_poc():
        rele = _importuri(p.read_text(encoding="utf-8")) & MODULE_DE_SCRIERE
        if rele:
            incalcari.append(f"{p.name}: importa {sorted(rele)}")
    assert not incalcari, (
        "POC-uri care importa module capabile sa scrie in Supabase:\n  "
        + "\n  ".join(incalcari))


def test_niciun_poc_nu_contine_apeluri_de_scriere():
    """GARDA 2. Chiar si fara importurile de mai sus, un apel de scriere pe un
    client construit local ar fi o portita."""
    incalcari = []
    for p in _fisiere_poc():
        gasite = _apeluri_de_scriere(p.read_text(encoding="utf-8"))
        if gasite:
            incalcari.append(f"{p.name}: contine {gasite}")
    assert not incalcari, "POC-uri cu apeluri de scriere:\n  " + "\n  ".join(incalcari)


def test_niciun_poc_nu_citeaza_nume_de_secrete():
    """GARDA 3. Un POC care citeste un secret il poate si folosi. Si tine
    verificarea un `in` strict: pe 2026-10-14 chiar aceasta regula a prins
    docstring-ul meu, care CITA numele secretului in propozitia ce explica de
    ce nu il primeste. O garda cu exceptii de interpretat e o garda care, la a
    doua citire, lasa sa treaca exact ce trebuia sa prinda."""
    incalcari = []
    for p in _fisiere_poc():
        sursa = p.read_text(encoding="utf-8")
        gasite = [s for s in NUME_DE_SECRETE if s in sursa]
        if gasite:
            incalcari.append(f"{p.name}: citeaza {gasite}")
    assert not incalcari, (
        "POC-uri care citeaza nume de secrete (chiar si in comentarii — "
        "reformuleaza, nu face exceptie):\n  " + "\n  ".join(incalcari))


def _workflow_ruleaza_poc(d: dict) -> bool:
    for job in (d.get("jobs") or {}).values():
        for pas in (job or {}).get("steps") or []:
            if "_poc_" in str((pas or {}).get("run", "")):
                return True
    return False


def test_niciun_workflow_de_poc_nu_primeste_secrete_supabase():
    """GARDA 4, ultima linie de aparare. Chiar daca primele trei ar fi
    ocolite, fara credentiale scrierea esueaza."""
    incalcari = []
    for p in sorted(WORKFLOWS.glob("*.yml")):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue   # raportat de tests/test_workflow_yaml_valid.py
        if not isinstance(d, dict) or not _workflow_ruleaza_poc(d):
            continue
        text = p.read_text(encoding="utf-8")
        cod = "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))
        if "SUPABASE" in cod:
            incalcari.append(f"{p.name}: expune un secret Supabase unui POC")
    assert not incalcari, "\n  ".join(incalcari)


def test_detectorul_chiar_prinde_un_poc_care_scrie(tmp_path):
    """CONTRAPONDERE — construieste defectul explicit.

    NU se verifica „exista cel putin N POC-uri", cum fac celelalte garzi din
    proiect: POC-urile se STERG dupa inchiderea investigatiei, deci ZERO e
    starea normala, nu un semn ca garda e oarba."""
    rau = tmp_path / "_poc_rau_temp.py"
    rau.write_text(
        "from database.queries import upsert_freelf_lineup_snapshot\n"
        "import os\n"
        "def f(c):\n"
        "    c.table('freelf_lineup_snapshot').upsert({'x': 1}).execute()\n"
        "    return os.environ['SUPABASE_SECRET_KEY']\n", encoding="utf-8")
    sursa = rau.read_text(encoding="utf-8")

    assert _importuri(sursa) & MODULE_DE_SCRIERE, "garda 1 nu prinde importul"
    assert _apeluri_de_scriere(sursa), "garda 2 nu prinde apelul"
    assert [s for s in NUME_DE_SECRETE if s in sursa], "garda 3 nu prinde secretul"

    bun = tmp_path / "_poc_bun_temp.py"
    # Include `sys.path.insert(...)` DELIBERAT: e boilerplate-ul care a facut
    # prima versiune a garzii sa raporteze 23 de fisiere pe nedrept.
    bun.write_text(
        "import json\nimport sys\nfrom pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).parent))\n"
        "lista = []\nlista.insert(0, 1)\n"
        "print(json.dumps({'ok': True}))\n", encoding="utf-8")
    sb = bun.read_text(encoding="utf-8")
    assert not (_importuri(sb) & MODULE_DE_SCRIERE)
    assert not _apeluri_de_scriere(sb), "fals pozitiv pe cod curat"
    assert not [s for s in NUME_DE_SECRETE if s in sb], "garda da fals pozitiv"


def test_detectorul_de_workflow_prinde_expunerea_de_secret(tmp_path):
    """Contrapondere pentru garda 4: un workflow care ruleaza un POC si ii da
    secrete trebuie detectat."""
    d_rau = yaml.safe_load(
        "on:\n  workflow_dispatch:\n"
        "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: python _poc_ceva_temp.py\n")
    assert _workflow_ruleaza_poc(d_rau), "detectorul nu recunoaste un pas de POC"

    d_bun = yaml.safe_load(
        "on:\n  workflow_dispatch:\n"
        "jobs:\n  x:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: python sync/run_daily.py\n")
    assert not _workflow_ruleaza_poc(d_bun), "detectorul da fals pozitiv"
