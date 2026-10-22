"""[ADR-081] Corpul raspunsului esuat devine INTEROGABIL, nu doar logat.

Trei capete de cablare, si firul dintre ele:
  1. `supabase_client._error_body_de_scris()` — functia pura care decide ce
     ajunge in coloana (garda de succes + plafon propriu);
  2. `RequestManager.record_result()` — parametrul trece prin calea comuna,
     deci orice adaptor nou de Sync Layer il capata gratuit (ADR-041 Faza 1);
  3. `soccerfootballinfo_client._get()` — singurul apelant cablat azi.

Lectia din reparatia `night_sync` (mutatia M5 care a trecut): verificarea
celor doua capete nu dovedeste firul dintre ele. De aceea exista aici si teste
care exercita MECANISMUL real — INSERT-ul cu client fals, si `_get()` cu o
sesiune falsa care intoarce un 400 adevarat — nu doar dictionare scrise de
mana.

Fara retea, fara Supabase: `get_client` e inlocuit cu un fals care doar
inregistreaza ce s-a scris.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

import supabase_client as sb
from request_manager import RequestManager

RADACINA = Path(__file__).resolve().parent.parent


# ──────────────────────────────────────────────────────────────────────────
# 1. Functia pura: ce ajunge efectiv in coloana
# ──────────────────────────────────────────────────────────────────────────

def test_pe_succes_corpul_e_mereu_None_chiar_daca_apelantul_il_paseaza():
    """Garda principala a ADR-081 §2 pct. 3. Un apelant neatent nu poate
    umple tabela cu corpuri de raspunsuri REUSITE."""
    assert sb._error_body_de_scris(True, "corp de raspuns reusit") is None


def test_pe_succes_nici_un_corp_lung_nu_trece():
    """Garda de succes se aplica INAINTEA plafonului, nu dupa — altfel am
    stoca 400 de caractere dintr-un raspuns reusit."""
    assert sb._error_body_de_scris(True, "x" * 5000) is None


def test_pe_esec_corpul_scurt_trece_neatins():
    assert sb._error_body_de_scris(False, '{"message":"Invalid date"}') == '{"message":"Invalid date"}'


def test_pe_esec_corpul_absent_ramane_None():
    """Esec fara raspuns (excepție de rețea, deci nicio pagina de citit).
    NULL = necunoscut, niciodata aproximat (Regula #8)."""
    assert sb._error_body_de_scris(False, None) is None


def test_pe_esec_corpul_gol_ramane_None_nu_sir_vid():
    """Un `''` stocat ar fi indistingibil de „am citit si era gol" — iar
    `_corp_diagnostic()` are deja propriul marcaj `<corp gol>` pentru asta."""
    assert sb._error_body_de_scris(False, "") is None


def test_plafonul_de_scriere_taie_la_400_de_caractere():
    rezultat = sb._error_body_de_scris(False, "y" * 900)
    assert rezultat is not None
    assert len(rezultat) == 400
    assert rezultat == "y" * 400


def test_exact_400_de_caractere_nu_se_taie():
    """Granita: plafonul e `>`, nu `>=` — un corp de exact 400 e intreg."""
    corp = "z" * 400
    assert sb._error_body_de_scris(False, corp) == corp


def test_plafonul_pastreaza_INCEPUTUL_nu_sfarsitul():
    """Mesajul de eroal RapidAPI e la inceputul corpului; un HTML de eroare
    are acolo titlul. Taierea de la coada ar pastra exact partea inutila."""
    corp = "MOTIVUL REFUZULUI" + ("." * 900)
    rezultat = sb._error_body_de_scris(False, corp)
    assert rezultat.startswith("MOTIVUL REFUZULUI")


def test_plafonul_de_scriere_e_independent_de_cel_din_corp_diagnostic():
    """Cele doua plafoane au proprietari diferiti (ADR-081 §2 pct. 4).
    Calea de scriere nu are voie sa aiba incredere in apelant: un adaptor
    VIITOR care paseaza un HTML brut de kilobytes, fara sa treaca prin
    `_corp_diagnostic()`, e tot marginit."""
    import soccerfootballinfo_client as sfi
    brut = "<html>" + ("a" * 50000) + "</html>"
    rezultat = sb._error_body_de_scris(False, brut)
    assert len(rezultat) <= sb._LUNGIME_MAXIMA_ERROR_BODY
    # Nu a trecut prin trunchierea sursei — dovada ca plafonul de scriere
    # lucreaza singur, nu moștenit de la SFI.
    assert "…[trunchiat]" not in rezultat
    assert sfi._LUNGIME_MAXIMA_CORP_DIAGNOSTIC == sb._LUNGIME_MAXIMA_ERROR_BODY


def test_valoare_care_nu_e_sir_nu_arunca():
    """Calea de scriere a unui apel de provider nu are voie sa cada din
    cauza unui tip neasteptat — ar transforma o imbunatatire de
    observabilitate in pierdere de date."""
    rezultat = sb._error_body_de_scris(False, 400)
    assert rezultat == "400"


# ──────────────────────────────────────────────────────────────────────────
# 2. Firul: INSERT-ul real, prin client fals
# ──────────────────────────────────────────────────────────────────────────

class _Interogare:
    def __init__(self, tabela, jurnal, raspuns_select):
        self._tabela = tabela
        self._jurnal = jurnal
        self._raspuns = raspuns_select

    def select(self, *a, **kw): return self

    def insert(self, payload):
        self._jurnal.append((self._tabela, payload))
        return self

    def update(self, payload): return self
    def eq(self, *a, **kw): return self
    def limit(self, *a, **kw): return self

    def execute(self):
        class _R:
            def __init__(self, data): self.data = data
        return _R(self._raspuns)


class _ClientFals:
    def __init__(self):
        self.jurnal: list[tuple[str, dict]] = []

    def table(self, nume):
        return _Interogare(nume, self.jurnal, [] if nume == "provider_metrics" else None)


@pytest.fixture
def client_fals(monkeypatch):
    c = _ClientFals()
    monkeypatch.setattr(sb, "get_client", lambda: c)
    return c


def _rand_de_log(client):
    randuri = [p for (t, p) in client.jurnal if t == "provider_call_log"]
    assert len(randuri) == 1, f"exact un rand de log asteptat, am {len(randuri)}"
    return randuri[0]


def test_INSERT_ul_real_scrie_corpul_pe_esec(client_fals):
    sb.record_provider_call("soccerfootballinfo", "matches/day/full/", False, 300.0,
                            http_status=400, failure_reason="client_error",
                            error_body='{"message":"You are not subscribed"}')
    assert _rand_de_log(client_fals)["error_body"] == '{"message":"You are not subscribed"}'


def test_INSERT_ul_real_scrie_NULL_pe_succes_chiar_daca_apelantul_paseaza_corp(client_fals):
    """Garda NU sta in apelant — e in calea de scriere. Aici se exercita
    mecanismul, nu functia pura: dovedeste ca `record_provider_call` chiar o
    foloseste, nu doar ca exista."""
    sb.record_provider_call("soccerfootballinfo", "matches/day/full/", True, 120.0,
                            http_status=200, error_body="corp care NU trebuie stocat")
    assert _rand_de_log(client_fals)["error_body"] is None


def test_INSERT_ul_real_taie_la_plafon(client_fals):
    sb.record_provider_call("x", "y", False, 1.0, error_body="q" * 1200)
    assert len(_rand_de_log(client_fals)["error_body"]) == 400


def test_apelantii_care_NU_paseaza_corpul_rămân_valizi(client_fals):
    """ADR-081 §2 pct. 1 — parametrul e opțional, deci `oracle_api.py` si
    `football_providers.py` nu au nevoie de nicio schimbare."""
    assert sb.record_provider_call("football_data", "/matches", False, 50.0,
                                   http_status=503) is True
    assert _rand_de_log(client_fals)["error_body"] is None


# ──────────────────────────────────────────────────────────────────────────
# 3. Firul: parametrul trece prin calea comuna RequestManager
# ──────────────────────────────────────────────────────────────────────────

def test_request_manager_paseaza_corpul_mai_departe(monkeypatch):
    primite = {}

    def _fals(provider, endpoint, success, latency_ms, **kw):
        primite.update(kw)
        primite["success"] = success
        return True

    monkeypatch.setattr(sb, "record_provider_call", _fals)
    RequestManager().record_result("soccerfootballinfo", "matches/day/full/", False, 10.0,
                                   status_code=400, error_body='{"message":"nope"}')
    assert primite["error_body"] == '{"message":"nope"}'
    assert primite["http_status"] == 400


def test_request_manager_fara_corp_trimite_None(monkeypatch):
    primite = {}
    monkeypatch.setattr(sb, "record_provider_call",
                        lambda *a, **kw: primite.update(kw) or True)
    RequestManager().record_result("api_football", "fixtures", True, 10.0)
    assert primite["error_body"] is None


def test_request_manager_nu_arunca_daca_scrierea_esueaza(monkeypatch):
    """Observabilitatea nu are voie sa rupa lucrul pe care il observa —
    aceeasi regula ca la rândul de audit `night_sync`."""
    def _arunca(*a, **kw):
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr(sb, "record_provider_call", _arunca)
    RequestManager().record_result("soccerfootballinfo", "p", False, 1.0,
                                   status_code=400, error_body="x")


# ──────────────────────────────────────────────────────────────────────────
# 4. Firul: SFI calculeaza corpul si il paseaza — pe calea REALA
# ──────────────────────────────────────────────────────────────────────────

class _RaspunsFals:
    def __init__(self, status, text, ok=None):
        self.status_code = status
        self.text = text
        self.ok = (200 <= status < 300) if ok is None else ok
        self.headers = {}

    def json(self):
        return {"data": "ok"}


class _SesiuneFalsa:
    def __init__(self, raspuns=None, arunca=None):
        self._raspuns = raspuns
        self._arunca = arunca
        self.apeluri = 0

    def get(self, *a, **kw):
        self.apeluri += 1
        if self._arunca is not None:
            raise self._arunca
        return self._raspuns


def _client_sfi(monkeypatch, sesiune, apeluri_inregistrate):
    import soccerfootballinfo_client as sfi

    class _KeyManagerFals:
        def is_available(self, _p): return True
        def get_headers(self, _p): return {"X-RapidAPI-Key": "SECRET-NU-TREBUIE-SA-APARA"}
        def record_request(self, _p): pass

    class _CacheFals:
        def get_raw(self, *a, **kw): return None
        def set(self, *a, **kw): pass

    class _RMFals:
        def get_ram(self, *a, **kw): return None
        def set_ram(self, *a, **kw): pass
        def should_request(self, _p): return True
        def try_acquire_inflight(self, *a, **kw): return True
        def release_inflight(self, *a, **kw): pass
        def record_response_headers(self, *a, **kw): pass

        def record_result(self, *a, **kw):
            apeluri_inregistrate.append((a, kw))

    c = sfi.SoccerFootballInfoClient.__new__(sfi.SoccerFootballInfoClient)
    c._key_manager = _KeyManagerFals()
    c._cache = _CacheFals()
    c._request_manager = _RMFals()
    c._session = sesiune
    monkeypatch.setattr(c, "_get_session", lambda: sesiune, raising=False)
    return c


def test_sfi_paseaza_corpul_pe_400_real(monkeypatch):
    """Cazul care a motivat ADR-081: HTTP 400 pe 100% din apeluri din 11
    oct, cu motivul doar in `logger.warning`."""
    inregistrate = []
    sesiune = _SesiuneFalsa(_RaspunsFals(400, '{"message":"Invalid API key"}'))
    c = _client_sfi(monkeypatch, sesiune, inregistrate)

    c._get("matches/day/full/", {"d": "20261022"}, "cat", "cheie")

    assert len(inregistrate) == 1
    kwargs = inregistrate[0][1]
    assert kwargs["error_body"] == '{"message":"Invalid API key"}'
    assert kwargs["status_code"] == 400


def test_sfi_NU_paseaza_corp_pe_succes(monkeypatch):
    inregistrate = []
    sesiune = _SesiuneFalsa(_RaspunsFals(200, '{"data":"ok"}'))
    c = _client_sfi(monkeypatch, sesiune, inregistrate)

    c._get("matches/day/full/", {"d": "20261022"}, "cat", "cheie")

    assert inregistrate[0][1]["error_body"] is None


def test_sfi_pe_excepție_de_retea_corpul_rămâne_None(monkeypatch):
    """Nicio pagina de citit, deci nimic de stocat — nu un sir inventat."""
    inregistrate = []
    sesiune = _SesiuneFalsa(arunca=OSError("connection reset"))
    c = _client_sfi(monkeypatch, sesiune, inregistrate)

    c._get("matches/day/full/", {"d": "20261022"}, "cat", "cheie")

    kwargs = inregistrate[0][1]
    assert kwargs["error_body"] is None
    assert kwargs["status_code"] is None


def test_sfi_trunchiaza_un_corp_uriaș_inainte_de_a_il_pasa(monkeypatch):
    inregistrate = []
    sesiune = _SesiuneFalsa(_RaspunsFals(400, "<html>" + "b" * 90000 + "</html>"))
    c = _client_sfi(monkeypatch, sesiune, inregistrate)

    c._get("matches/day/full/", {"d": "20261022"}, "cat", "cheie")

    corp = inregistrate[0][1]["error_body"]
    assert len(corp) <= 420  # 400 + marcajul de trunchiere al sursei


def test_cheia_API_nu_poate_ajunge_in_corp(monkeypatch):
    """Proprietatea pe care se sprijina ADR-081 §3: cheia circula exclusiv
    in header-ul de CERERE. Verificata, nu presupusa — header-ul fals
    conține un secret recognoscibil, iar corpul stocat vine din RASPUNS."""
    inregistrate = []
    sesiune = _SesiuneFalsa(_RaspunsFals(400, '{"message":"Invalid date format"}'))
    c = _client_sfi(monkeypatch, sesiune, inregistrate)

    c._get("matches/day/full/", {"d": "bad"}, "cat", "cheie")

    assert "SECRET-NU-TREBUIE-SA-APARA" not in (inregistrate[0][1]["error_body"] or "")


# ──────────────────────────────────────────────────────────────────────────
# 5. Garzi structurale (AST — ignora comentariile prin construcție)
# ──────────────────────────────────────────────────────────────────────────

def _functie(cale: Path, nume: str, clasa: str | None = None) -> ast.FunctionDef:
    arbore = ast.parse(cale.read_text(encoding="utf-8"))
    domeniu = arbore.body
    if clasa is not None:
        domeniu = next(n for n in arbore.body
                       if isinstance(n, ast.ClassDef) and n.name == clasa).body
    return next(n for n in domeniu
                if isinstance(n, ast.FunctionDef) and n.name == nume)


def test_corpul_se_calculeaza_O_SINGURA_DATA_in_sfi():
    """Doua apeluri separate la `_corp_diagnostic` ar putea divergea daca
    unul se muta — iar log-ul si coloana ar spune lucruri diferite despre
    acelasi raspuns. Clasa „al doilea scriitor pe un cîmp folosit de altul
    ca martor", deja documentata in proiect."""
    f = _functie(RADACINA / "soccerfootballinfo_client.py", "_get",
                 clasa="SoccerFootballInfoClient")
    apeluri = [n for n in ast.walk(f)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == "_corp_diagnostic"]
    assert len(apeluri) == 1, (
        f"_corp_diagnostic apelat {len(apeluri)} ori in _get; trebuie calculat "
        "o data si refolosit pentru AMBELE destinatii (log + error_body)"
    )


def test_sfi_paseaza_error_body_la_record_result():
    """Garda de cablare: `_corp_diagnostic` calculat si nefolosit ar fi exact
    defectul reparat de ADR-081, mutat cu un pas."""
    f = _functie(RADACINA / "soccerfootballinfo_client.py", "_get",
                 clasa="SoccerFootballInfoClient")
    apeluri = [n for n in ast.walk(f)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "record_result"]
    assert len(apeluri) == 1
    assert "error_body" in {kw.arg for kw in apeluri[0].keywords}


def test_request_manager_paseaza_error_body_mai_departe_structural():
    f = _functie(RADACINA / "request_manager.py", "record_result",
                 clasa="RequestManager")
    assert "error_body" in {a.arg for a in f.args.args}
    apeluri = [n for n in ast.walk(f)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "record_provider_call"]
    assert len(apeluri) == 1
    assert "error_body" in {kw.arg for kw in apeluri[0].keywords}


def test_calea_de_scriere_NU_foloseste_parametrul_brut():
    """Invariantul care face garda de succes imposibil de ocolit: valoarea
    pusa in INSERT trece OBLIGATORIU prin `_error_body_de_scris`, niciodata
    `error_body` direct. O rescriere care paseaza brut cade aici."""
    f = _functie(RADACINA / "supabase_client.py", "record_provider_call")
    dicturi = [n for n in ast.walk(f) if isinstance(n, ast.Dict)]
    gasit = False
    for d in dicturi:
        for cheie, valoare in zip(d.keys, d.values):
            if isinstance(cheie, ast.Constant) and cheie.value == "error_body":
                gasit = True
                assert isinstance(valoare, ast.Call), (
                    "error_body pus brut in INSERT — garda de succes si plafonul "
                    "sunt ocolite"
                )
                assert isinstance(valoare.func, ast.Name)
                assert valoare.func.id == "_error_body_de_scris"
    assert gasit, "cheia error_body nu apare in niciun dict din record_provider_call"


def test_migrarea_058_nu_creeaza_tabela_deci_nu_cade_la_garda_de_GRANT():
    """Contrapondere la `tests/test_migration_grants.py`: 058 e prima migrare
    peste pragul 058, dar e un `ALTER TABLE`, nu un `CREATE TABLE`. Tabela
    existenta isi pastreaza grant-urile."""
    cale = RADACINA / "database" / "migrations" / "058_provider_call_log_error_body.sql"
    sql = cale.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS error_body" in sql
    assert "CREATE TABLE" not in sql.upper()
