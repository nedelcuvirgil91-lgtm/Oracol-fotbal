"""Un cache nu are voie să rupă apelantul (reparat 2026-10-21).

DEFECTUL, și de ce a fost invizibil patru nopți. `_path()` construia numele
de fișier prin concatenare directă a cheii. `oracle_api.get_matches_for_week()`
își face cheia din numele TUTUROR competițiilor urmărite, deci numele creștea
cu fiecare ligă adăugată. Pe 17 octombrie, trei ligi noi (Austria, Elveția,
Danemarca) l-au dus de la **249 la 304 octeți** — plafonul ext4 e **255**.

Consecința nu a fost un cache ratat, ci o **excepție în apelant**:
`Path.exists()` pe Python 3.11 aruncă `ENAMETOOLONG`, fiindcă `pathlib` ignoră
doar errno `(2, 20, 9, 40)`; 36 nu e printre ele. Etapa „Challenger Shadow
Batch" a murit la 2,3 s în fiecare rulare de noapte, iar `night_sync` a
raportat verde — nu are cod de ieșire pe eșec de etapă.

**Pe Python 3.12+ același cod NU aruncă** (`exists()` înghite orice `OSError`),
deci aplicația de pe Streamlit Cloud a mers mai departe fără cache L1, în timp
ce runnerul GitHub cădea. Același cod, două comportamente, după versiunea
interpretorului. De aceea niciun test existent și nicio privire pe ecran nu
puteau prinde defectul.

CE VERIFICĂ FIȘIERUL ĂSTA, și ce NU. Nu verifică „cheia de la
`get_matches_for_week` e scurtă" — asta ar fi o listă, care se învechește la
următoarea ligă adăugată. Verifică **invariantul**: orice cheie, oricât de
lungă, produce un nume mărginit și nu aruncă niciodată. Plus garda AST care
ține `_path()` singurul punct de acces la disc — altfel o metodă nouă ar putea
reintroduce defectul pe lângă marginire.
"""
from __future__ import annotations

import ast
import errno
import inspect
from pathlib import Path

import pytest

import cache_manager as cm
import mappings as m


LIMITA = cm._LIMITA_NUME_FISIER


def _cheia_reala_de_productie() -> str:
    """Exact cheia pe care `oracle_api.get_matches_for_week()` o construiește
    pentru batch-ul ADR-056 și pentru `app.py` — ambele pasează lista completă
    de competiții. Construită din `mappings`, nu copiată: dacă se adaugă o
    ligă, testul o vede automat."""
    comps = sorted(m.TRACKED_COMPETITIONS)
    return f"week_2026-10-21_7_{','.join(comps)}"


# ════════════════════════════════════════════════════════════════════════════
# Regresia reală, cu contrapondere ca testul să nu poată trece vid
# ════════════════════════════════════════════════════════════════════════════

def test_contrapondere_cheia_reala_DEPASESTE_plafonul_altfel_testul_e_vid():
    """Fără asta, testul de mai jos ar trece și pe un cod fără nicio gardă, în
    ziua în care lista de competiții s-ar scurta. Dacă pică, nu înseamnă că
    reparația e greșită — înseamnă că regresia nu mai e reproductibilă și
    fixtura trebuie regândită."""
    brut = f"{_cheia_reala_de_productie()}.json"
    assert len(brut.encode("utf-8")) > LIMITA, (
        f"numele brut are {len(brut.encode())} octeti, sub plafonul {LIMITA} — "
        "testul central nu mai dovedește nimic")


def test_cheia_reala_de_productie_produce_nume_marginit(tmp_path):
    mgr = cm.CacheManager(base_dir=tmp_path)
    p = mgr._path("matches", _cheia_reala_de_productie())
    assert len(p.name.encode("utf-8")) <= LIMITA


@pytest.fixture
def fara_nivel_2(monkeypatch):
    """Nivelul 2 (Supabase) scos din ecuație, EXPLICIT.

    `get`/`set` fac `import supabase_client` în interiorul funcției și îl
    apelează. Aici lipsesc credențialele, deci ar întoarce `None` oricum — dar
    pe o mașină de dezvoltare care LE ARE, testele ar atinge rețeaua, contra
    regulii proiectului. Un test care trece doar fiindcă mediul e sărac nu e
    un test fără rețea, e unul norocos."""
    import supabase_client as sb
    monkeypatch.setattr(sb, "get_cached_response", lambda *a, **k: None)
    monkeypatch.setattr(sb, "set_cached_response", lambda *a, **k: False)
    return sb


@pytest.mark.parametrize("operatie", [
    lambda mgr, k: mgr.get_raw("matches", k),
    lambda mgr, k: mgr.get("matches", k),
    lambda mgr, k: mgr.get_age_hours("matches", k),
    lambda mgr, k: mgr.invalidate("matches", k),
    lambda mgr, k: mgr.exists("matches", k),
])
def test_nicio_operatie_nu_mai_arunca_pe_cheie_lunga(tmp_path, fara_nivel_2, operatie):
    """Modul exact în care defectul s-a manifestat: o EXCEPȚIE, nu o valoare
    greșită."""
    mgr = cm.CacheManager(base_dir=tmp_path)
    cheie = "x" * 400
    try:
        operatie(mgr, cheie)
    except OSError as exc:
        pytest.fail(
            f"a aruncat OSError {exc.errno} "
            f"({errno.errorcode.get(exc.errno)}) — exact defectul reparat")


def test_cache_ul_CHIAR_functioneaza_prin_garda_nu_doar_tace(tmp_path, fara_nivel_2):
    """Deosebirea dintre reparația asta și un `try/except`: scrie și apoi
    CITEȘTE înapoi. Un `except` ar fi făcut testul de mai sus să treacă, iar
    pe ăsta să cadă — cache-ul ar fi fost dezactivat tăcut pentru exact cheia
    cea mai scumpă din proiect."""
    mgr = cm.CacheManager(base_dir=tmp_path)
    cheie = _cheia_reala_de_productie()
    assert mgr.set("matches", cheie, {"meciuri": [1, 2, 3]}) is not False
    assert mgr.get_raw("matches", cheie) == {"meciuri": [1, 2, 3]}


# ════════════════════════════════════════════════════════════════════════════
# Injectivitate — coliziunea tăcută ar fi mai rea decât excepția reparată
# ════════════════════════════════════════════════════════════════════════════

def test_doua_chei_care_difera_DOAR_dupa_punctul_de_tai_dau_nume_diferite():
    """Capcana variantei naive „trunchiază și gata". Amprenta e peste cheia
    întreagă tocmai pentru asta: altfel cele două ar citi una răspunsul
    celeilalte — un rezultat GREȘIT servit ca valid, nu o eroare."""
    comun = "week_2026-10-21_7_" + "A" * 400
    a, b = comun + "_Eliteserien", comun + "_Allsvenskan"
    assert a[:LIMITA] == b[:LIMITA], "fixtura e greșită — diferă înainte de tai"
    assert cm._scurteaza_nume(a) != cm._scurteaza_nume(b)


def test_acelasi_cheie_acelasi_nume_determinist():
    k = _cheia_reala_de_productie() + "_" + "z" * 300
    assert cm._scurteaza_nume(k) == cm._scurteaza_nume(k)


def test_amprenta_apare_in_nume_nu_doar_prefixul():
    k = "q" * 400
    nume = cm._scurteaza_nume(k)
    assert "~" in nume and nume.endswith(".json")
    amprenta = nume.rsplit("~", 1)[1][: -len(".json")]
    assert len(amprenta) == 16 and all(c in "0123456789abcdef" for c in amprenta)


# ════════════════════════════════════════════════════════════════════════════
# CONTRAPONDERI — cele ~18 chei scurte existente nu au voie să se schimbe
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("category,key,nume_asteptat", [
    ("odds", "odds_soccer_epl", "odds_soccer_epl.json"),
    ("h2h", "freelf_h2h_123456", "freelf_h2h_123456.json"),
    ("standings", "Premier League_2026", "Premier_League_2026.json"),
    ("matches", "week_2026-10-21_7_", "week_2026-10-21_7_.json"),
    ("teams", "team_id:arsenal", "team_id_arsenal.json"),
])
def test_cheile_scurte_rAman_octet_cu_octet_ce_erau(tmp_path, category, key, nume_asteptat):
    """Reparația are voie să atingă EXCLUSIV cheile peste plafon. Dacă ar
    rescrie și numele scurte, fiecare intrare de cache existentă ar deveni
    inaccesibilă dintr-odată — o invalidare în masă, tăcută."""
    mgr = cm.CacheManager(base_dir=tmp_path)
    assert mgr._path(category, key).name == nume_asteptat


def test_granita_exact_la_plafon_NU_se_scurteaza(tmp_path):
    mgr = cm.CacheManager(base_dir=tmp_path)
    cheie = "k" * (LIMITA - len(".json"))
    nume = mgr._path("matches", cheie).name
    assert len(nume.encode("utf-8")) == LIMITA
    assert "~" not in nume, "o cheie exact la plafon a fost scurtată degeaba"


def test_granita_cu_un_octet_peste_SE_scurteaza(tmp_path):
    mgr = cm.CacheManager(base_dir=tmp_path)
    cheie = "k" * (LIMITA - len(".json") + 1)
    nume = mgr._path("matches", cheie).name
    assert len(nume.encode("utf-8")) <= LIMITA
    assert "~" in nume


# ════════════════════════════════════════════════════════════════════════════
# Octeți, nu caractere — un nume cu diacritice atinge plafonul mai repede
# ════════════════════════════════════════════════════════════════════════════

def test_plafonul_e_in_OCTETI_nu_in_caractere(tmp_path):
    """`'ö'` ocupă doi octeți. O cheie de 200 de caractere cu diacritice trece
    de 255 de octeți fără să pară lungă — exact clasa de eroare pe care
    dezbrăcarea sufixului de țară a avut-o în `mappings` (reparată în aceeași
    zi, din altă cauză)."""
    cheie = "ö" * 200
    assert len(cheie) < LIMITA and len(cheie.encode("utf-8")) > LIMITA
    mgr = cm.CacheManager(base_dir=tmp_path)
    nume = mgr._path("matches", cheie).name
    assert len(nume.encode("utf-8")) <= LIMITA
    assert "~" in nume


def test_trunchierea_nu_lasa_un_caracter_multi_octet_rupt(tmp_path, fara_nivel_2):
    cheie = "ü" * 300
    nume = cm._scurteaza_nume(cheie)
    nume.encode("utf-8").decode("utf-8")  # nu trebuie să ridice
    mgr = cm.CacheManager(base_dir=tmp_path)
    mgr.set("matches", cheie, {"a": 1})
    assert mgr.get_raw("matches", cheie) == {"a": 1}


# ════════════════════════════════════════════════════════════════════════════
# Garda de CLASĂ — `_path()` rămâne singurul punct de acces la disc
# ════════════════════════════════════════════════════════════════════════════

# `replace` lipsește deliberat: pe `str` e înlocuire de text, pe `Path` e
# redenumire atomică. Ambiguitatea ar produce fals pozitive pe sanitizarea
# cheii din `_path` însuși. Metodele care chiar îl folosesc pe `Path`
# (`get`/`set`) sunt oricum prinse prin celelalte apeluri de disc.
_ACCES_DISC = {
    "read_text", "write_text", "stat", "exists", "unlink",
    "glob", "iterdir", "mkdir", "touch", "rename", "open",
}


def _metode_care_ating_discul_cu_o_cheie() -> list[str]:
    arbore = ast.parse(inspect.getsource(cm))
    clasa = next(n for n in ast.walk(arbore)
                 if isinstance(n, ast.ClassDef) and n.name == "CacheManager")
    vinovate = []
    for fn in [n for n in clasa.body if isinstance(n, ast.FunctionDef)]:
        parametri = {a.arg for a in fn.args.args}
        if "key" not in parametri:
            continue  # nu primește cheie -> nu poate construi un nume din ea
        atinge = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr in _ACCES_DISC
            for n in ast.walk(fn)
        )
        prin_path = any(
            isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_path"
            for n in ast.walk(fn)
        )
        if atinge and not prin_path:
            vinovate.append(fn.name)
    return vinovate


def test_orice_metoda_cu_cheie_care_atinge_discul_trece_prin_path():
    """AST, nu text — prin construcție nu poate găsi explicațiile din
    comentarii. A cincea instanță a lecției, după `pipefail`, numele de
    secrete, docstring-ul ADR-073 și titlul Decision Feed-ului.

    Dacă pică: o metodă nouă construiește un nume de fișier pe lângă `_path`,
    deci marginirea nu o acoperă și defectul se poate întoarce pe acolo."""
    vinovate = _metode_care_ating_discul_cu_o_cheie()
    assert not vinovate, (
        "metode care ating discul cu o cheie fără să treacă prin `_path()`: "
        + ", ".join(vinovate))


def test_contrapondere_garda_AST_chiar_vede_metodele(tmp_path):
    """Previne trecerea VIDĂ: dacă `_ACCES_DISC` ar fi golit sau clasa
    redenumită, garda de mai sus ar trece fără să verifice nimic."""
    arbore = ast.parse(inspect.getsource(cm))
    clasa = next(n for n in ast.walk(arbore)
                 if isinstance(n, ast.ClassDef) and n.name == "CacheManager")
    cu_cheie = [fn.name for fn in clasa.body
                if isinstance(fn, ast.FunctionDef)
                and "key" in {a.arg for a in fn.args.args}]
    assert len(cu_cheie) >= 4, f"garda vede doar {cu_cheie} — prea puțin"
    assert "_path" in cu_cheie and "get" in cu_cheie and "set" in cu_cheie
