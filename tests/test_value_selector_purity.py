"""
Garda structurala pentru Value Selector V1 (ADR-071) — T11, T12, T13.

Verifica INVARIANTUL, citind codul sursa prin AST, nu efectele observate pe
cateva fixture-uri: un selector poate trece toate testele de comportament si
totusi sa importe motorul, sa scrie in baza de date sau sa se ramifice pe tipul
selectiei intr-o cale netestata.

Lectie deja platita de doua ori in acest proiect (garda `pipefail`, garda
`_doar_cod()`): o garda care cauta text isi poate gasi propriul comentariu
explicativ si trece dupa ce codul real a fost sters. De aceea:
  - analiza se face pe AST, unde comentariile nu exista deloc;
  - docstring-urile sunt eliminate explicit inainte de verificarea literalelor;
  - fiecare garda are un CONTRA-TEST care ii injecteaza incalcarea si verifica
    ca o prinde (altfel garda ar putea fi vida si tot ar trece).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
NUCLEU = REPO / "value_selector.py"
ADAPTOR = REPO / "value_selector_adapter.py"

# Module de la care selectorul NU are voie sa depinda: motorul, providerii,
# stratul de date. Dependinta "in sus" e interzisa (North Star #10).
MODULE_INTERZISE = {
    "oracle_engine", "oracle_api", "feature_engine", "ml_predictor",
    "recalibration", "supabase_client", "database", "shadow_testing",
    "learning_core", "requests", "httpx", "streamlit",
}

# Orice ar face selectorul impur: I/O, ceas de sistem, aleatoriu.
APELURI_INTERZISE = {
    "open", "print", "input",
    "datetime.now", "datetime.utcnow", "date.today", "time.time",
    "random.random", "random.choice",
}

# Etichetele de selectie. Nucleul nu are voie sa le contina deloc ca literale —
# asa e imposibil sa se ramifice pe tipul selectiei.
LITERALE_DE_SELECTIE = {
    "1", "X", "2", "H", "D", "A",
    "Home Win", "Draw", "Away Win", "home", "draw", "away",
}


# ── Utilitare de analiza ─────────────────────────────────────────────────────

def _arbore(sursa: str) -> ast.Module:
    return ast.parse(sursa)


def _importuri(sursa: str) -> set[str]:
    gasite: set[str] = set()
    for nod in ast.walk(_arbore(sursa)):
        if isinstance(nod, ast.Import):
            for alias in nod.names:
                gasite.add(alias.name.split(".")[0])
        elif isinstance(nod, ast.ImportFrom) and nod.module:
            gasite.add(nod.module.split(".")[0])
    return gasite


def _apeluri(sursa: str) -> set[str]:
    gasite: set[str] = set()
    for nod in ast.walk(_arbore(sursa)):
        if not isinstance(nod, ast.Call):
            continue
        tinta = nod.func
        if isinstance(tinta, ast.Name):
            gasite.add(tinta.id)
        elif isinstance(tinta, ast.Attribute):
            gasite.add(tinta.attr)
            if isinstance(tinta.value, ast.Name):
                gasite.add(f"{tinta.value.id}.{tinta.attr}")
    return gasite


def _noduri_docstring(arbore: ast.Module) -> set[int]:
    """Id-urile nodurilor care sunt docstring-uri — se exclud din verificarea
    de literale, ca documentatia sa poata explica exact ce e interzis in cod."""
    ids: set[int] = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            corp = getattr(nod, "body", [])
            if corp and isinstance(corp[0], ast.Expr) and isinstance(corp[0].value, ast.Constant) \
                    and isinstance(corp[0].value.value, str):
                ids.add(id(corp[0].value))
    return ids


def literale_de_selectie_in_cod(sursa: str) -> set[str]:
    """Literalele de selectie prezente in COD (docstring-urile excluse)."""
    arbore = _arbore(sursa)
    docstrings = _noduri_docstring(arbore)
    gasite: set[str] = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Constant) and isinstance(nod.value, str) \
                and id(nod) not in docstrings and nod.value in LITERALE_DE_SELECTIE:
            gasite.add(nod.value)
    return gasite


# ── T11 — nicio dependinta catre Oracle Engine ───────────────────────────────

def test_T11_nucleul_nu_importa_motorul_sau_stratul_de_date():
    interzise = _importuri(NUCLEU.read_text(encoding="utf-8")) & MODULE_INTERZISE
    assert not interzise, f"value_selector.py importa module interzise: {sorted(interzise)}"


def test_T11b_adaptorul_nu_importa_motorul():
    """Adaptorul citeste `MatchPrediction` prin getattr, nu prin import."""
    interzise = _importuri(ADAPTOR.read_text(encoding="utf-8")) & MODULE_INTERZISE
    assert not interzise, f"value_selector_adapter.py importa module interzise: {sorted(interzise)}"


def test_T11c_garda_de_import_chiar_prinde_o_incalcare():
    """CONTRA-TEST: fara el, garda ar putea fi vida si tot ar trece."""
    mutant = "import oracle_engine\n\ndef f():\n    return 1\n"
    assert _importuri(mutant) & MODULE_INTERZISE == {"oracle_engine"}

    mutant_from = "from database.queries import upsert_match\n"
    assert _importuri(mutant_from) & MODULE_INTERZISE == {"database"}


# ── T12 — nicio scriere in baza de date, nicio impuritate ────────────────────

def test_T12_nucleul_nu_face_IO_si_nu_citeste_ceasul():
    gasite = _apeluri(NUCLEU.read_text(encoding="utf-8")) & APELURI_INTERZISE
    assert not gasite, f"value_selector.py face apeluri impure: {sorted(gasite)}"


def test_T12b_adaptorul_nu_face_IO_si_nu_citeste_ceasul():
    gasite = _apeluri(ADAPTOR.read_text(encoding="utf-8")) & APELURI_INTERZISE
    assert not gasite, f"value_selector_adapter.py face apeluri impure: {sorted(gasite)}"


def test_T12c_garda_de_puritate_chiar_prinde_o_incalcare():
    """CONTRA-TEST pentru fiecare forma de apel pe care garda trebuie s-o vada."""
    assert "datetime.now" in _apeluri("import datetime\nx = datetime.now()\n")
    assert "time.time" in _apeluri("import time\nx = time.time()\n")
    assert "open" in _apeluri("f = open('x')\n")


def test_T12d_selectorul_nu_are_acces_la_niciun_client_de_baza_de_date():
    """Verificare la nivel de runtime, complementara celei de AST: modulul
    importat nu expune niciun obiect care sa semene a client Supabase."""
    import value_selector

    suspecte = [nume for nume in dir(value_selector)
                if any(cheie in nume.lower() for cheie in ("client", "supabase", "session"))]
    assert not suspecte, f"value_selector expune obiecte suspecte: {suspecte}"


# ── T13 — zero logica conditionata de tipul selectiei ────────────────────────

def test_T13_nucleul_nu_contine_niciun_literal_de_selectie_in_cod():
    """Simetria H/X/A e structurala: daca in cod nu exista niciun literal de
    selectie, nu are cum sa existe o ramificatie pe tipul selectiei."""
    gasite = literale_de_selectie_in_cod(NUCLEU.read_text(encoding="utf-8"))
    assert not gasite, (
        "value_selector.py contine literale de selectie in cod (nu in docstring): "
        f"{sorted(gasite)} — simetria H/X/A nu mai e garantata structural"
    )


def test_T13b_nucleul_nu_compara_niciodata_campul_de_selectie():
    """A doua garda, independenta de prima: nicio comparatie si niciun `if` nu
    are voie sa atinga `selection_code`/`selection_label`."""
    arbore = _arbore(NUCLEU.read_text(encoding="utf-8"))
    atinse: list[str] = []
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Compare):
            for parte in [nod.left, *nod.comparators]:
                if isinstance(parte, ast.Attribute) and parte.attr in {
                        "selection_code", "selection_label"}:
                    atinse.append(parte.attr)
    assert not atinse, f"value_selector.py compara campul de selectie: {atinse}"


def test_T13c_garda_de_simetrie_chiar_prinde_o_incalcare():
    """CONTRA-TEST, direct impotriva erorii deja facute de doua ori in proiect:
    garda trebuie sa prinda incalcarea din COD, si sa NU se declanseze pe un
    docstring care doar vorbeste despre ea."""
    mutant = (
        'def f(c):\n'
        '    if c.selection_code == "X":\n'
        '        return 0.0\n'
        '    return 1.0\n'
    )
    assert literale_de_selectie_in_cod(mutant) == {"X"}

    doar_docstring = (
        '"""Acest modul nu compara niciodata selection_code cu "X" sau "1"."""\n'
        'def f(c):\n'
        '    """Nici aici nu se compara cu "Draw"."""\n'
        '    return 1.0\n'
    )
    assert literale_de_selectie_in_cod(doar_docstring) == set()


def test_T13d_garda_nu_trece_vida_daca_fisierul_dispare_sau_e_gol():
    """Contrapondere: o garda care analizeaza un fisier gol ar trece mereu."""
    sursa = NUCLEU.read_text(encoding="utf-8")
    assert len(sursa) > 2000, "nucleul selectorului pare gol — garda ar trece degeaba"
    assert "def select(" in sursa


# ── Contract public stabil ───────────────────────────────────────────────────

def test_nucleul_expune_contractul_asteptat_de_F2():
    import value_selector

    for nume in ("SelectionCandidate", "SelectorPolicy", "SelectorResult", "select",
                 "select_by_day", "to_shadow_rows", "RANKERS", "shrink_probability",
                 "Category", "GateId", "RejectionReason", "Verdict"):
        assert hasattr(value_selector, nume), f"lipseste din contractul public: {nume}"


def test_toate_rankerele_cerute_pentru_F2_exista():
    from value_selector import RANKERS

    assert set(RANKERS) == {
        "probability_first", "probability_plus_value", "shrunk_ev",
        "market_controlled", "legacy_relative_edge",
    }


def test_profilele_de_F2_acopera_familia_de_shrinkage_ceruta():
    from value_selector_config import F2_PROFILES

    ponderi = {p.shrinkage_w for nume, p in F2_PROFILES.items() if nume.startswith("shrunk_")}
    assert ponderi == {1.00, 0.75, 0.50, 0.25}
    assert F2_PROFILES["market_only"].shrinkage_w == 0.0
    assert F2_PROFILES["market_only"].require_positive_value is False


def test_profilele_de_F2_acopera_pragurile_de_piata_cerute():
    from value_selector_config import F2_PROFILES

    praguri = {p.market_plausibility_floor for nume, p in F2_PROFILES.items()
               if nume.startswith("market_floor_")}
    assert praguri == {0.20, 0.25, 0.30, 0.35, 0.40}


def test_fiecare_profil_de_F2_are_policy_id_distinct():
    from value_selector_config import F2_PROFILES

    ids = [p.policy_id for p in F2_PROFILES.values()]
    assert len(ids) == len(set(ids)), "doua profile F2 au acelasi policy_id"


# ── Consecventa cu sursa canonica (architecture-review) ──────────────────────

def test_clasa_de_calitate_insuficienta_ramane_sincronizata_cu_sursa_canonica():
    """`value_selector_adapter` NU are voie sa importe `oracle_engine`
    (North Star #10, garda T11), deci re-declara literalul clasei de calitate
    insuficienta. Ca sa nu devina o a doua sursa de adevar care se desincronizeaza
    tacit, echivalenta e fixata AICI — testele au voie sa importe motorul,
    codul de productie nu.

    Daca `oracle_engine` redenumeste sau adauga o clasa de calitate, acest test
    cade si obliga la o decizie explicita, in loc sa lase adaptorul sa filtreze
    dupa o valoare care nu mai exista."""
    import oracle_engine
    from value_selector_adapter import INSUFFICIENT_DATA_QUALITY

    assert INSUFFICIENT_DATA_QUALITY == {oracle_engine.DATA_QUALITY_NEUTRAL}

    # Cele patru clase cunoscute azi; adaugarea uneia noi trebuie sa fie o
    # decizie constienta, nu o scapare.
    assert {oracle_engine.DATA_QUALITY_LIVE, oracle_engine.DATA_QUALITY_PARTIAL,
            oracle_engine.DATA_QUALITY_ELO, oracle_engine.DATA_QUALITY_NEUTRAL} == {
        "live", "partial", "elo", "neutral"}


# ── Rezolvarea profilului numit (ADR-071 §10) ────────────────────────────────
# Garda nascuta dintr-un defect real, prins la un pas de activarea in
# productie: `build_policy()` construia politica din chei individuale, deci a
# scrie doar `value_selector_policy_profile = "shrunk_050"` producea o politica
# NUMITA shrunk_050 dar identica comportamental cu legacy (amprenta 5555df84 in
# loc de 32ccbf4a). Ecranul ar fi aratat aceleasi 48 de meciuri sub un nume
# care pretindea altceva, iar UI-ul si experimentul shadow ar fi masurat lucruri
# diferite fara niciun semnal.

def test_fiecare_profil_numit_se_rezolva_identic_cu_catalogul():
    """Invariantul care lipsea. Pentru ORICE profil din catalog, politica pe
    care o construieste configuratia trebuie sa aiba aceeasi amprenta cu cea
    pe care o foloseste colectorul shadow — altfel UI-ul si experimentul nu
    mai sunt comparabile."""
    from value_selector_config import F2_PROFILES, build_policy

    for nume, canonic in F2_PROFILES.items():
        produs = build_policy({"value_selector_policy_profile": nume})
        assert produs == canonic, f"profilul {nume} nu se rezolva din catalog"
        assert produs.policy_id == canonic.policy_id, (
            f"{nume}: amprenta UI {produs.policy_id} != amprenta shadow "
            f"{canonic.policy_id}")


def test_profilul_numit_ignora_cheile_individuale():
    """Un profil canonic e un tot. O cheie ramasa din alta configuratie nu are
    voie sa-i schimbe tacit comportamentul pastrandu-i numele."""
    from value_selector_config import F2_PROFILES, build_policy

    produs = build_policy({
        "value_selector_policy_profile": "shrunk_050",
        "value_selector_top_n_matches": 99,
        "value_selector_require_rank_one": False,
        "value_selector_shrinkage_w": 1.0,
    })
    assert produs == F2_PROFILES["shrunk_050"]
    assert produs.top_n_matches == 5
    assert produs.require_rank_one is True
    assert produs.shrinkage_w == 0.5


def test_configuratia_implicita_ramane_legacy():
    from value_selector import LEGACY_POLICY
    from value_selector_config import build_policy

    assert build_policy({}) == LEGACY_POLICY


def test_un_profil_necunoscut_se_construieste_camp_cu_camp():
    """Flexibilitatea nu se pierde: o politica ad-hoc, care nu e in catalog,
    ramane posibila fara cod nou."""
    from value_selector_config import build_policy

    produs = build_policy({
        "value_selector_policy_profile": "experiment_ad_hoc",
        "value_selector_require_rank_one": True,
        "value_selector_top_n_matches": 3,
    })
    assert produs.profile == "experiment_ad_hoc"
    assert produs.require_rank_one is True
    assert produs.top_n_matches == 3
