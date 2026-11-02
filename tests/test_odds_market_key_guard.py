"""Garda `is_available` pe `_fetch_market` — a doua instanță a defectului A2.

Fără rețea, fără Supabase: `self._s` e o dublură care numără cererile, iar
instanța se construiește cu `__new__` (fără `__init__`, deci fără client HTTP
real), exact tiparul deja folosit în `test_oracle_api_odds.py`.

DE CE EXISTĂ. `requests` omite un parametru `None`, deci când
`get_api_key_param()` întoarce `None` cererea pleacă spre `/odds` **fără
`apiKey`** și primește garantat 401. Măsurat pe producție: **34 de 401-uri în
26 de secunde**, 2026-11-02 08:55:35 → 08:56:01, adică 17 ligi × 2 apeluri.

Defectul era o copie a celui reparat la A2 pe calea `/sports` (27 oct), rămasă
nereparată fiindcă `provider_call_log.endpoint` lua primul segment de cale și
scria toate cele patru endpoint-uri Odds API ca `sports` — deci cele „418 × 401
în 8 zile" au fost atribuite integral căii de validare.

CONTRAPONDERE OBLIGATORIE: o gardă care sare mereu ar trece orice test care
verifică doar „nu s-a trimis nimic". De aceea fiecare test de sărire are un
gemene care cere ca cererea SĂ plece când cheia e utilizabilă.
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import oracle_api


class _Km:
    """Dublură de key manager. Oglindește contractul real: `None` de la
    `get_api_key_param` exact când `is_available` e False (`key_manager.py`
    liniile 241-243 și 253-254). O dublură care ar întoarce mereu un șir ar
    ascunde exact defectul auditat."""

    def __init__(self, disponibila: bool) -> None:
        self._disponibila = disponibila
        self.intrebari: list[str] = []

    def is_available(self, provider: str) -> bool:
        self.intrebari.append(provider)
        return self._disponibila

    def get_api_key_param(self, _provider: str):
        return "cheie-falsa" if self._disponibila else None


class _Resp:
    def __init__(self, payload, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload


class _Sesiune:
    """Numără cererile efectiv plecate și întoarce ce i se spune."""

    def __init__(self, raspuns=None) -> None:
        self.cereri: list[dict] = []
        self._raspuns = raspuns if raspuns is not None else _Resp([])

    def get(self, url, headers=None, params=None, timeout=12):
        self.cereri.append({"url": url, "params": params or {}})
        return self._raspuns


def _api(disponibila: bool, raspuns=None):
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = _Sesiune(raspuns)
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._odds_keys_validated = True
    api._key_manager = _Km(disponibila)
    return api


# ── Comportamentul gărzii ───────────────────────────────────────────────────

def test_cheie_indisponibila_NU_trimite_nicio_cerere():
    api = _api(disponibila=False)
    rezultat = api._fetch_market("soccer_epl", "h2h,totals")
    assert rezultat is None
    assert api._s.cereri == [], (
        f"garda a lăsat să plece {len(api._s.cereri)} cereri care ar fi primit "
        f"401 garantat"
    )


def test_CONTRAPONDERE_cheie_disponibila_TRIMITE_cererea():
    """Fără ăsta, o gardă care sare necondiționat ar trece testul de mai sus."""
    api = _api(disponibila=True, raspuns=_Resp([{"id": "ev1"}]))
    rezultat = api._fetch_market("soccer_epl", "h2h,totals")
    assert rezultat == [{"id": "ev1"}]
    assert len(api._s.cereri) == 1
    assert api._s.cereri[0]["url"].endswith("/sports/soccer_epl/odds")
    assert api._s.cereri[0]["params"]["apiKey"] == "cheie-falsa"


def test_garda_intreaba_despre_oddsapi_nu_despre_altcineva():
    api = _api(disponibila=False)
    api._fetch_market("soccer_epl", "h2h")
    assert api._key_manager.intrebari == ["oddsapi"]


def test_ECHIVALENTA_IN_DATE_None_identic_cu_ce_producea_un_401():
    """Miezul argumentului că schimbarea e neutră: `_get` întoarce `None` pe
    orice răspuns non-ok, deci apelantul primea `None` și înainte. Garda nu
    introduce o valoare nouă în contract."""
    api_401 = _api(disponibila=True, raspuns=_Resp(None, ok=False, status_code=401))
    prin_401 = api_401._fetch_market("soccer_epl", "h2h")

    api_sarit = _api(disponibila=False)
    prin_garda = api_sarit._fetch_market("soccer_epl", "h2h")

    assert prin_401 is None
    assert prin_garda is None
    assert prin_401 is prin_garda is None
    # …dar una a costat o cerere HTTP, cealaltă nu. Asta e tot câștigul.
    assert len(api_401._s.cereri) == 1
    assert len(api_sarit._s.cereri) == 0


# ── Efectul în `_fetch_odds`, apelantul real ────────────────────────────────

def test_fetch_odds_cu_cheie_indisponibila_face_ZERO_cereri():
    """Azi, pe producție, aceeași situație costă 2 cereri per ligă — măsurat
    34 pentru 17 ligi."""
    api = _api(disponibila=False)
    api._ensure_odds_keys_validated = lambda: None  # type: ignore[assignment]
    scrieri: list[tuple] = []
    api._cget = lambda k: None                      # type: ignore[assignment]
    api._cset = lambda k, v: scrieri.append((k, v))  # type: ignore[assignment]

    rezultat = api._fetch_odds("soccer_epl")

    assert rezultat == {}
    assert api._s.cereri == []
    assert scrieri == [], (
        "reparația cache-ului negativ trebuie să rămână în efect: un eșec NU "
        "se scrie în cache"
    )


def test_fetch_odds_pastreaza_dead_keys_exact_ca_inainte():
    """Comportament PĂSTRAT, nu îmbunătățit: `data is None` adaugă cheia în
    `_dead_keys`. Garda întoarce `None`, deci efectul e identic — iar asta e
    deliberat, ca schimbarea să fie echivalentă, nu subtil diferită."""
    api = _api(disponibila=False)
    api._ensure_odds_keys_validated = lambda: None  # type: ignore[assignment]
    api._cget = lambda k: None                      # type: ignore[assignment]
    api._cset = lambda k, v: None                   # type: ignore[assignment]

    api._fetch_odds("soccer_epl")

    assert "soccer_epl" in api._dead_keys


def test_CONTRAPONDERE_fetch_odds_cu_cheie_disponibila_chiar_cere():
    api = _api(disponibila=True, raspuns=_Resp([]))
    api._ensure_odds_keys_validated = lambda: None  # type: ignore[assignment]
    api._cget = lambda k: None                      # type: ignore[assignment]
    api._cset = lambda k, v: None                   # type: ignore[assignment]

    api._fetch_odds("soccer_epl")

    assert len(api._s.cereri) >= 1, "cu cheie utilizabilă cererea trebuie să plece"


# ── Gărzi structurale — AST, niciodată text ─────────────────────────────────
#
# Comentariul de deasupra gărzii, în `oracle_api.py`, conține de mai multe ori
# chiar șirul `is_available`, plus `_get`. O verificare textuală ar trece pe
# propria explicație, iar „reparația" evidentă ar fi ștergerea explicației —
# a șaptea instanță a clasei `pipefail`. AST-ul ignoră comentariile PRIN
# CONSTRUCȚIE; nu e o reparație, e o imposibilitate.

def _corp_fetch_market() -> list[ast.stmt]:
    sursa = textwrap.dedent(inspect.getsource(oracle_api.FootballOracleAPI._fetch_market))
    fn = ast.parse(sursa).body[0]
    assert isinstance(fn, ast.FunctionDef)
    return fn.body


def _indice_garda(corp: list[ast.stmt]) -> int:
    for i, stmt in enumerate(corp):
        if not isinstance(stmt, ast.If):
            continue
        for sub in ast.walk(stmt.test):
            if isinstance(sub, ast.Attribute) and sub.attr == "is_available":
                return i
    return -1


def _indice_cerere(corp: list[ast.stmt]) -> int:
    for i, stmt in enumerate(corp):
        for sub in ast.walk(stmt):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "_get"):
                return i
    return -1


def test_garda_exista_in_cod():
    assert _indice_garda(_corp_fetch_market()) >= 0, (
        "`_fetch_market` nu mai conține o verificare `is_available` — cererile "
        "fără apiKey pot pleca din nou"
    )


def test_garda_e_INAINTEA_cererii_nu_doar_prezenta():
    """Lecția „verifici cele două capete și nu firul dintre ele": o gardă
    plasată DUPĂ `_get` ar exista în cod, ar fi găsită de testul de mai sus, și
    n-ar împiedica nicio cerere."""
    corp = _corp_fetch_market()
    i_garda = _indice_garda(corp)
    i_cerere = _indice_cerere(corp)
    assert i_garda >= 0 and i_cerere >= 0
    assert i_garda < i_cerere, (
        f"garda e la poziția {i_garda}, cererea la {i_cerere} — o gardă după "
        f"cerere nu păzește nimic"
    )


def test_garda_iese_din_functie_nu_doar_logheaza():
    """Un `logger.warning` fără `return` ar lăsa cererea să plece oricum."""
    corp = _corp_fetch_market()
    stmt = corp[_indice_garda(corp)]
    assert isinstance(stmt, ast.If)
    assert any(isinstance(s, ast.Return) for s in stmt.body), (
        "ramura gărzii nu conține `return` — logează și continuă"
    )
