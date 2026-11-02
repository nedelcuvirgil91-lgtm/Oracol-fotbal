"""Apelul `btts` pe endpoint-ul bulk — eliminat, și gardat să nu revină.

DE CE. `oracle_api._fetch_odds` făcea un al TREILEA apel per ligă,
`_fetch_market(sport_key, "btts")`, către `/sports/{sport}/odds`. Documentația
oficială (the-odds-api.com/sports-odds-data/betting-markets.html) listează
`btts` la **Additional Markets** și spune explicit:

    „additional markets need to be accessed ONE EVENT AT A TIME using the
     `/events/{eventId}/odds` endpoint"

Deci apelul nu putea reuși pentru nicio ligă, în nicio zi. Măsurat pe singura
fereastră cu etichetă de endpoint corectă (1-2 nov): alternanță strictă
`200` (h2h,totals) → `422` (btts), **0 din 28 reușite**.

Costul: jumătate din bugetul `/odds`, pe o cotă LUNARĂ.

GARDA CENTRALĂ E AST, NU TEXT — obligatoriu aici, nu preferință: nota de
eliminare din `oracle_api.py` conține chiar șirul `_fetch_market(sport_key,
"btts")`, ca explicație. O verificare textuală ar găsi exact comentariul care
documentează eliminarea, iar „reparația" evidentă ar fi ștergerea explicației.
A opta instanță a clasei `pipefail`.
"""
from __future__ import annotations

import ast
import pathlib

import oracle_api

_RADACINA = pathlib.Path(__file__).resolve().parent.parent

# Fișierele de producție care pot atinge Odds API. Lista e îngustă deliberat:
# o gardă care scanează tot repo-ul ar fi lentă și ar prinde fixture-uri de
# test ca fals pozitiv.
_FISIERE_PRODUCTIE = ("oracle_api.py", "odds_api_fixture_adapter.py")


def _apeluri_fetch_market(sursa: str) -> list[list[str]]:
    """Argumentele literale ale fiecărui apel `_fetch_market(...)`, prin AST."""
    gasite: list[list[str]] = []
    for nod in ast.walk(ast.parse(sursa)):
        if (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)
                and nod.func.attr == "_fetch_market"):
            gasite.append([
                a.value for a in nod.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)
            ])
    return gasite


def test_niciun_apel_de_productie_nu_mai_cere_piata_btts():
    for nume in _FISIERE_PRODUCTIE:
        cale = _RADACINA / nume
        if not cale.exists():
            continue
        for argumente in _apeluri_fetch_market(cale.read_text(encoding="utf-8")):
            for arg in argumente:
                assert "btts" not in arg, (
                    f"{nume}: `_fetch_market(..., {arg!r})` — `btts` NU există pe "
                    f"endpoint-ul bulk `/sports/{{sport}}/odds`, e Additional "
                    f"Market și se cere doar prin `/events/{{eventId}}/odds`. "
                    f"Apelul ar fi 422 garantat, la fiecare ligă, la fiecare "
                    f"rulare."
                )


def test_CONTRAPONDERE_garda_chiar_vede_apelurile_ramase():
    """Fără asta, garda de mai sus ar trece și dacă AST-ul n-ar găsi NIMIC —
    de exemplu dacă `_fetch_market` ar fi redenumit. Un `0` nu se raportează
    fără martor pozitiv."""
    sursa = (_RADACINA / "oracle_api.py").read_text(encoding="utf-8")
    apeluri = _apeluri_fetch_market(sursa)
    piete = {arg for argumente in apeluri for arg in argumente}
    assert "h2h,totals" in piete, f"garda nu mai vede apelurile reale: {piete}"
    assert "h2h" in piete, f"garda nu mai vede fallback-ul: {piete}"


def test_garda_ar_prinde_reintroducerea():
    """Exercită garda pe o sursă sintetică, ca să nu treacă VID dacă fișierul
    real s-ar redenumi sau goli."""
    sintetic = 'x = self._fetch_market(sport_key, "btts")\n'
    piete = [arg for argumente in _apeluri_fetch_market(sintetic) for arg in argumente]
    assert piete == ["btts"], "garda nu ar prinde reintroducerea"


# ── Consecința de cotă, măsurată pe comportament ────────────────────────────

class _Resp:
    def __init__(self, payload, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload


class _Sesiune:
    def __init__(self, dupa_piata: dict):
        self._dupa_piata = dupa_piata
        self.piete_cerute: list[str] = []

    def get(self, url, headers=None, params=None, timeout=12):
        piata = (params or {}).get("markets", "")
        self.piete_cerute.append(piata)
        return self._dupa_piata.get(piata, _Resp(None, ok=False, status_code=422))


_EV = [{
    "id": "ev1", "home_team": "Arsenal", "away_team": "Chelsea",
    "bookmakers": [{"title": "Bet365", "markets": [
        {"key": "h2h", "outcomes": [
            {"name": "Arsenal", "price": 2.1}, {"name": "Draw", "price": 3.4},
            {"name": "Chelsea", "price": 3.8}]},
    ]}],
}]


def _api(sesiune):
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._s = sesiune
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._odds_keys_validated = True

    class _Km:
        def is_available(self, _p): return True
        def get_api_key_param(self, _p): return "cheie-falsa"

    api._key_manager = _Km()
    return api


def test_calea_de_succes_face_EXACT_un_apel_per_liga():
    """Înainte: 2 (`h2h,totals` + `btts`). Jumătate din bugetul de cote."""
    sesiune = _Sesiune({"h2h,totals": _Resp(_EV)})
    api = _api(sesiune)
    api._cget = lambda k: None   # type: ignore[assignment]
    api._cset = lambda k, v: None  # type: ignore[assignment]

    api._fetch_odds("soccer_epl")

    assert sesiune.piete_cerute == ["h2h,totals"], (
        f"{len(sesiune.piete_cerute)} apeluri în loc de 1: {sesiune.piete_cerute}")


def test_CONTRAPONDERE_fallbackul_pe_h2h_face_in_continuare_doua():
    """Eliminarea lui `btts` NU trebuie să atingă fallback-ul — acela e singura
    cale prin care o ligă fără `totals` mai primește cote."""
    sesiune = _Sesiune({"h2h": _Resp(_EV)})  # `h2h,totals` eșuează
    api = _api(sesiune)
    api._cget = lambda k: None   # type: ignore[assignment]
    api._cset = lambda k, v: None  # type: ignore[assignment]

    rezultat = api._fetch_odds("soccer_epl")

    assert sesiune.piete_cerute == ["h2h,totals", "h2h"]
    assert rezultat["ev1"]["home"] == 2.1, "fallback-ul nu mai produce cote"


def test_cheile_btts_raman_in_rezultat_la_zero():
    """Contractul din aval e NEATINS: `oracle_engine._special_value_bets`
    citește `btts_yes`/`btts_no` și le sare prin `if bk_odds <= 1.0`. Erau
    deja mereu 0.0 — eliminarea apelului e bit-identică, nu doar sigură."""
    sesiune = _Sesiune({"h2h,totals": _Resp(_EV)})
    api = _api(sesiune)
    api._cget = lambda k: None   # type: ignore[assignment]
    api._cset = lambda k, v: None  # type: ignore[assignment]

    intrare = api._fetch_odds("soccer_epl")["ev1"]

    assert intrare["btts_yes"] == 0.0
    assert intrare["btts_no"] == 0.0
