"""
Gărzi pentru întrerupătorul de provider (`provider_kill_switch.py`, 2026-10-16).

**Incidentul**: TheSportsDB a trecut peste noapte de la 0-2 eșecuri/zi la
**443 din 443** (HTTP 404). Distribuția latențelor a ieșit strict bimodală —
327 de apeluri sub 1 s și **117 între 20 și 120 s**, nimic între. Cele 117
(26% din apeluri) au consumat **106 din cele 109 minute**. `night_sync` a fost
anulată la plafonul de 180 min, după 10 rulări consecutive de 80-105 min.

Ce impun testele de aici, în ordinea gravității:

1. **Fail-open.** Un întrerupător care nu poate fi citit NU oprește nimic.
   Direcția inversă ar transforma o indisponibilitate Supabase într-o cădere
   totală a tuturor providerilor — mult mai rău decât incidentul reparat.
2. **Poarta e în `_get()`, punct unic.** Dacă cineva o mută la apelanți,
   următorul endpoint adăugat o ocolește tăcut.
3. **Configurația ciudată nu devine interpretare creativă.** Un șir în loc de
   listă iterat caracter cu caracter ar opri providerul „t".
4. **Cache cu TTL.** Fără el, poarta costă un drum la Supabase per cerere HTTP
   — mai mult decât providerul pe care îl oprește.

Zero rețea, zero Supabase: `supabase_client.load_config` e înlocuit prin
monkeypatch, iar sesiunea HTTP printr-un dublu care numără cererile.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import provider_kill_switch as pks

RADACINA = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _cache_curat():
    """Fiecare test pornește fără cache — altfel primul test ar fixa valoarea
    pentru toate celelalte, iar suita ar trece din întâmplare."""
    pks.goleste_cache()
    yield
    pks.goleste_cache()


def _config(monkeypatch, valoare, *, exploda=False):
    def fals(default):
        if exploda:
            raise RuntimeError("Supabase indisponibil")
        return {pks.CHEIE_CONFIG: valoare}
    monkeypatch.setattr(pks.sb, "load_config", fals)


# ── Comportamentul de bază ───────────────────────────────────────────────────

def test_implicit_nu_opreste_nimic(monkeypatch):
    """North Star #3: comportamentul NOU (oprirea) pornește STINS. Merge-ul
    singur nu are voie să schimbe nimic în producție."""
    monkeypatch.setattr(pks.sb, "load_config", lambda default: dict(default))
    assert pks.opriti() == frozenset()
    assert pks.este_oprit("thesportsdb") is False


def test_opreste_exact_providerul_cerut(monkeypatch):
    _config(monkeypatch, ["thesportsdb"])
    assert pks.este_oprit("thesportsdb") is True
    assert pks.este_oprit("espn") is False
    assert pks.este_oprit("oddsapi") is False


def test_numele_sunt_insensibile_la_majuscule_si_spatii(monkeypatch):
    """Cine scrie configurația o scrie de mână, sub presiune de incident."""
    _config(monkeypatch, ["  TheSportsDB  "])
    assert pks.este_oprit("thesportsdb") is True
    assert pks.este_oprit("THESPORTSDB") is True


def test_provider_necunoscut_nu_e_oprit_niciodata(monkeypatch):
    """Un URL al cărui provider nu a putut fi identificat nu poate fi oprit
    intenționat. A-l opri ar însemna să tăiem cereri la întâmplare."""
    _config(monkeypatch, ["unknown", "thesportsdb"])
    assert pks.este_oprit("unknown") is False
    assert pks.este_oprit("") is False
    assert pks.este_oprit(None) is False


# ── Fail-open: cel mai important test din fișier ─────────────────────────────

def test_eroare_de_citire_NU_opreste_nimic(monkeypatch):
    """Mutația care contează: `return frozenset()` → `return TOT`.

    Dacă citirea configurației ar fi fail-closed, o indisponibilitate Supabase
    ar opri TOȚI providerii simultan — o cădere mult mai gravă decât cea pe
    care modulul o repară."""
    _config(monkeypatch, None, exploda=True)
    assert pks.opriti() == frozenset()
    assert pks.este_oprit("thesportsdb") is False
    assert pks.este_oprit("espn") is False


def test_eroare_dupa_o_citire_reusita_pastreaza_ultima_valoare(monkeypatch):
    """O eroare tranzitorie nu are voie să REPORNEASCĂ un provider oprit
    deliberat — ar readuce exact incidentul, tăcut.

    Expirarea TTL-ului se simulează prin `acum`, NU prin `goleste_cache()`:
    golirea înseamnă „n-am știut niciodată nimic", stare în care fail-open
    spre mulțimea goală e comportamentul CORECT. Prima versiune a acestui
    test le confunda și cerea codului ceva imposibil."""
    _config(monkeypatch, ["thesportsdb"])
    assert pks.opriti(acum=1000.0) == frozenset({"thesportsdb"})

    _config(monkeypatch, None, exploda=True)
    dupa_expirare = pks.opriti(acum=1000.0 + pks.TTL_SECUNDE + 1)
    assert dupa_expirare == frozenset({"thesportsdb"}), (
        "a repornit providerul la o eroare tranzitorie de citire")


def test_fara_nicio_citire_reusita_eroarea_lasa_totul_pornit(monkeypatch):
    """Cealaltă jumătate, și e direcția care contează mai mult: dacă n-am
    reușit NICIODATĂ să citim configurația, nu oprim nimic."""
    _config(monkeypatch, None, exploda=True)
    assert pks.opriti() == frozenset()


# ── Configurație malformată ──────────────────────────────────────────────────

def test_sir_in_loc_de_lista_nu_e_iterat_caracter_cu_caracter(monkeypatch):
    """`"thesportsdb"` în loc de `["thesportsdb"]` ar produce, iterat,
    mulțimea {t,h,e,s,p,o,r,d,b} — și ar opri un provider numit „t". Mai rău:
    providerul ȚINTIT ar rămâne pornit, deci incidentul ar continua în timp ce
    configurația pare făcută."""
    _config(monkeypatch, "thesportsdb")
    assert pks.opriti() == frozenset()
    assert pks.este_oprit("thesportsdb") is False
    assert pks.este_oprit("t") is False


@pytest.mark.parametrize("valoare", [None, 42, {"thesportsdb": True}, True])
def test_valori_absurde_nu_opresc_nimic(monkeypatch, valoare):
    _config(monkeypatch, valoare)
    assert pks.opriti() == frozenset()


def test_intrari_goale_sunt_ignorate(monkeypatch):
    _config(monkeypatch, ["", "   ", "espn"])
    assert pks.opriti() == frozenset({"espn"})


# ── Cache ────────────────────────────────────────────────────────────────────

def test_cache_ul_evita_o_citire_per_cerere(monkeypatch):
    """Fără TTL, poarta ar costa un drum la Supabase la FIECARE apel HTTP —
    sute per rulare, deci mai mult decât providerul pe care îl oprește."""
    citiri = []

    def fals(default):
        citiri.append(1)
        return {pks.CHEIE_CONFIG: ["thesportsdb"]}

    monkeypatch.setattr(pks.sb, "load_config", fals)
    for _ in range(50):
        pks.este_oprit("thesportsdb")
    assert len(citiri) == 1, f"{len(citiri)} citiri pentru 50 de verificări"


def test_cache_ul_expira_dupa_TTL(monkeypatch):
    """O stingere făcută în timpul unei rulări trebuie să prindă efect, nu să
    aștepte repornirea procesului."""
    valori = [["espn"], ["thesportsdb"]]

    def fals(default):
        return {pks.CHEIE_CONFIG: valori[min(len(valori) - 1, _apeluri[0])]}

    _apeluri = [0]

    def numarat(default):
        rez = fals(default)
        _apeluri[0] += 1
        return rez

    monkeypatch.setattr(pks.sb, "load_config", numarat)
    assert pks.opriti(acum=1000.0) == frozenset({"espn"})
    assert pks.opriti(acum=1000.0 + pks.TTL_SECUNDE - 1) == frozenset({"espn"})
    assert pks.opriti(acum=1000.0 + pks.TTL_SECUNDE + 1) == frozenset({"thesportsdb"})


# ── Poarta e în `_get()`, punct unic ─────────────────────────────────────────

def test_poarta_e_in_get_nu_la_apelanti():
    """Dacă cineva mută verificarea la cele două locuri de apel TheSportsDB,
    următorul endpoint adăugat o ocolește tăcut. Toate cele 5 endpoint-uri
    trec azi prin `_get()`; acolo trebuie să stea poarta."""
    arbore = ast.parse((RADACINA / "oracle_api.py").read_text(encoding="utf-8"))
    get_def = next(
        (n for n in ast.walk(arbore)
         if isinstance(n, ast.FunctionDef) and n.name == "_get"), None)
    assert get_def is not None, "`_get` a dispărut din oracle_api.py"
    corp = ast.unparse(get_def)
    assert "provider_kill_switch" in corp, (
        "poarta nu mai e în `_get()` — un endpoint nou ar ocoli-o")
    assert "este_oprit" in corp


def test_poarta_ruleaza_inaintea_cererii_HTTP(monkeypatch):
    """Comportamental, nu structural: un provider oprit nu are voie să ajungă
    la `self._s.get`. Dacă ajunge, am plătit deja latența — exact costul pe
    care modulul îl elimină."""
    import oracle_api

    class _Sesiune:
        def __init__(self): self.cereri = []
        def get(self, url, **kw):  # pragma: no cover — nu trebuie atins
            self.cereri.append(url)
            raise AssertionError("cerere HTTP pentru un provider oprit")

    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = _Sesiune()
    _config(monkeypatch, ["thesportsdb"])

    rezultat = api._get(f"{oracle_api.THESPORTSDB_URL}/eventslast.php",
                        params={"id": "1"})
    assert rezultat is None
    assert api._s.cereri == []


def test_un_provider_NEoprit_trece_mai_departe(monkeypatch):
    """Contraponderea: dacă poarta ar bloca totul, testul de mai sus ar trece
    și el — dar am fi oprit tot proiectul."""
    import oracle_api

    class _Resp:
        status_code = 200
        headers: dict = {}
        def json(self): return {"ok": True}

    class _Sesiune:
        def __init__(self): self.cereri = []
        def get(self, url, **kw):
            self.cereri.append(url)
            return _Resp()

    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = _Sesiune()
    _config(monkeypatch, ["thesportsdb"])

    api._get("https://site.api.espn.com/ceva", params={})
    assert len(api._s.cereri) == 1, "o cerere legitimă a fost blocată"
