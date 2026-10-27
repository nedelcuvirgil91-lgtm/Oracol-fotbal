"""Cache NEGATIV — un eșec de provider nu se mai servește ca rezultat gol
„legitim" (punctul A din planul Odds API, `BACKLOG.md`).

DEFECTUL, confirmat în cod înainte de reparație:

    oracle_api.py   cached = self._cget(cache_key)
                    if cached is not None: return cached
                    ...
                    self._cset(cache_key, {}); return {}      # la eșec total

`{}` nu e `None`, deci `if cached is not None` era **True** și eșecul se
întorcea ca hit valid de cache. Durata otrăvirii = TTL-ul categoriei:
`CATEGORY_TTL["odds"] = 4.0` ore, iar mărirea aprobată la 24h ar fi
înmulțit paguba de 6×. Nu era ipotetic — un workflow fără `ODDS_API_KEY` a
scris 13 chei goale.

PROPRIETATEA APĂRATĂ, și e o distincție, nu o interdicție: un gol **legitim**
(providerul a răspuns cu o listă, zero evenimente parsate) TREBUIE să se
cache-uiască în continuare — altfel am înlocuit otrăvirea cu risipă de cotă.
Doar **eșecul** nu se persistă. De aceea fiecare test de „nu scrie" are
contraponderea lui „scrie".

Trei instanțe reparate: `_fetch_odds` (TTL 4h, cea gravă) și
`_fetch_events_odds_api` ×2 (TTL 0.5h, aceeași clasă).

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import oracle_api


# ── schelărie ─────────────────────────────────────────────────────────────

class _CacheSpion:
    """Ține minte CE s-a scris și CÂTE citiri s-au făcut. Deliberat NU e un
    `dict` simplu: `scrieri` păstrează ordinea și valorile, ca un test să
    poată distinge „n-a scris nimic" de „a scris altceva"."""

    def __init__(self):
        self.date: dict[str, object] = {}
        self.scrieri: list[tuple[str, object]] = []
        self.citiri: list[str] = []

    def get(self, key):
        self.citiri.append(key)
        return self.date.get(key)

    def set(self, key, val):
        self.date[key] = val
        self.scrieri.append((key, val))


def _api(raspunsuri: list[object]) -> tuple[object, _CacheSpion, list[str]]:
    """API fără `__init__` (deci fără I/O), cu `_get`/`_fetch_market` servind
    pe rând valorile din `raspunsuri`. `apeluri` numără cererile reale —
    semnalul prin care se vede dacă un hit de cache a sărit rețeaua."""
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._dead_keys = set()
    api._cache_mgr = None
    api._mem = {}
    api._ttl = 60

    spion = _CacheSpion()
    apeluri: list[str] = []
    coada = list(raspunsuri)

    api._cget = lambda k: spion.get(k)            # type: ignore[assignment]
    api._cset = lambda k, v: spion.set(k, v)      # type: ignore[assignment]
    api._ensure_odds_keys_validated = lambda: None  # type: ignore[assignment]

    class _FakeKM:
        def get_api_key_param(self, _p): return "cheie-falsa"

    api._key_manager = _FakeKM()

    def _fals(*a, **kw):
        apeluri.append("cerere")
        return coada.pop(0) if coada else None

    api._get = _fals                               # type: ignore[assignment]
    api._fetch_market = lambda sk, markets: _fals()  # type: ignore[assignment]
    return api, spion, apeluri


# ── _fetch_odds — instanța gravă (TTL 4h, și 24h după mărire) ─────────────

def test_esec_total_NU_scrie_nimic_in_cache():
    """Defectul original: scria `{}`. Niciun `_cset` nu trebuie să se producă."""
    api, spion, _ = _api([{"message": "plan fara acces"},
                          {"message": "plan fara acces"}])
    assert api._fetch_odds("soccer_epl") == {}
    assert spion.scrieri == [], (
        f"eșecul a fost persistat în cache: {spion.scrieri!r} — "
        "exact defectul reparat (`{}` servit ca hit valid)"
    )


def test_esec_apoi_reincercare_NU_serveste_un_hit_otravit():
    """Proprietatea care contează la nivel de comportament, nu de scriere:
    după un eșec, apelul următor trebuie să mai încerce. Cu defectul prezent,
    al doilea apel întorcea `{}` din cache fără nicio cerere."""
    api, _, apeluri = _api([
        {"eroare": 1}, {"eroare": 1},                      # primul apel, eșec
        [{"id": "ev1", "home_team": "A", "away_team": "B", "bookmakers": []}],
    ])
    assert api._fetch_odds("soccer_epl") == {}
    dupa_primul = len(apeluri)
    api._fetch_odds("soccer_epl")
    assert len(apeluri) > dupa_primul, (
        "al doilea apel n-a mai cerut nimic — cache-ul a servit eșecul"
    )


def test_data_None_adauga_in_dead_keys_dar_tot_nu_scrie_cache():
    """`_dead_keys` rămâne mecanismul de memorare, și e PER-PROCES — durata
    corectă pentru o eroare tranzitorie. Cache-ul persistent nu e."""
    api, spion, _ = _api([None, None])
    assert api._fetch_odds("soccer_epl") == {}
    assert "soccer_epl" in api._dead_keys
    assert spion.scrieri == []


def test_dead_key_scurtcircuiteaza_fara_nicio_cerere():
    api, _, apeluri = _api([])
    api._dead_keys.add("soccer_epl")
    assert api._fetch_odds("soccer_epl") == {}
    assert apeluri == []


# ── CONTRAPONDERI — golul legitim TREBUIE să se cache-uiască ──────────────

def test_lista_VIDA_de_la_provider_SE_cache_uieste():
    """Contrapondere esențială. Providerul a răspuns corect, doar n-are
    evenimente. Dacă nici asta nu s-ar cache-ui, am înlocuit otrăvirea cu
    risipă de cotă — iar cota Odds API e exact resursa de protejat."""
    api, spion, _ = _api([[]])
    assert api._fetch_odds("soccer_epl") == {}
    assert spion.scrieri == [("odds_soccer_epl", {})], (
        "golul legitim nu s-a cache-uit — reparația a mers prea departe"
    )


def test_hit_de_cache_legitim_nu_mai_cere_nimic():
    api, spion, apeluri = _api([])
    spion.date["odds_soccer_epl"] = {}
    assert api._fetch_odds("soccer_epl") == {}
    assert apeluri == []


def test_rezultat_real_se_cache_uieste():
    api, spion, _ = _api([
        [{"id": "ev1", "home_team": "Arsenal", "away_team": "Chelsea",
          "bookmakers": []}],
        None,  # btts, best-effort
    ])
    api._fetch_odds("soccer_epl")
    assert [k for k, _ in spion.scrieri] == ["odds_soccer_epl"]


# ── _fetch_events_odds_api — instanțele 2 și 3 (TTL 0.5h) ─────────────────

def test_events_data_None_nu_scrie_cache_dar_marcheaza_dead():
    api, spion, _ = _api([None])
    assert api._fetch_events_odds_api("soccer_epl") == []
    assert "soccer_epl" in api._dead_keys
    assert spion.scrieri == []


def test_events_raspuns_neasteptat_nu_scrie_cache():
    api, spion, _ = _api([{"message": "eroare"}])
    assert api._fetch_events_odds_api("soccer_epl") == []
    assert spion.scrieri == []
    assert "soccer_epl" not in api._dead_keys, (
        "un răspuns non-listă care nu e None nu trebuie să omoare cheia pe "
        "tot procesul — comportamentul de dinainte, păstrat deliberat"
    )


def test_events_lista_vida_legitima_SE_cache_uieste():
    api, spion, _ = _api([[]])
    assert api._fetch_events_odds_api("soccer_epl") == []
    assert len(spion.scrieri) == 1
    cheie, valoare = spion.scrieri[0]
    assert cheie.startswith("events_soccer_epl")
    assert valoare == []


def test_events_hit_legitim_nu_mai_cere():
    api, spion, apeluri = _api([])
    spion.date["events_soccer_epl_7"] = []
    assert api._fetch_events_odds_api("soccer_epl") == []
    assert apeluri == []


# ── gărzi structurale — ca reparația să nu fie anulată de o rescriere ─────

def _corp(nume: str) -> str:
    """Corpul unei metode din `oracle_api.py`, ca text, pentru gărzile de mai
    jos. Citește sursa de pe disc: o gardă care ar inspecta obiectul deja
    importat n-ar vedea textul, iar reintroducerea defectului trece exact prin
    text."""
    import ast
    import pathlib
    sursa = (pathlib.Path(oracle_api.__file__)).read_text(encoding="utf-8")
    arbore = ast.parse(sursa)
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.FunctionDef) and nod.name == nume:
            return ast.get_source_segment(sursa, nod) or ""
    raise AssertionError(f"metoda {nume!r} nu a fost găsită în oracle_api.py")


def _apeluri_cset_cu_literal_gol(nume: str) -> list[int]:
    """Numerele de linie ale apelurilor `_cset(..., <literal gol>)` din metodă.

    Folosește AST, nu text: un `grep` ar găsi șirul și în comentariul care
    explică reparația — a cincea instanță a clasei `pipefail`, deja plătită de
    patru ori în proiect. AST-ul ignoră comentariile prin construcție.
    """
    import ast
    arbore = ast.parse(_corp(nume))
    linii: list[int] = []
    for nod in ast.walk(arbore):
        if not isinstance(nod, ast.Call):
            continue
        f = nod.func
        nume_f = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if nume_f != "_cset" or len(nod.args) < 2:
            continue
        val = nod.args[1]
        gol = (
            (isinstance(val, ast.Dict) and not val.keys)
            or (isinstance(val, ast.List) and not val.elts)
        )
        if gol:
            linii.append(nod.lineno)
    return linii


def test_fetch_odds_nu_cache_uieste_niciun_literal_gol_direct():
    """Pe calea de succes, `{}` ajunge în cache doar ca VALOARE a lui
    `result` — niciodată ca literal scris direct, fiindcă singurul loc care
    făcea asta era ramura de eșec."""
    assert _apeluri_cset_cu_literal_gol("_fetch_odds") == []


def test_fetch_events_nu_cache_uieste_niciun_literal_gol_direct():
    assert _apeluri_cset_cu_literal_gol("_fetch_events_odds_api") == []


def test_garda_isi_vede_propriul_obiectiv_contrapondere():
    """Contrapondere pentru cele două gărzi de mai sus: dacă detectorul ar fi
    rupt (ex. n-ar recunoaște niciodată un literal gol), ele ar trece vid.
    Aici i se dă un caz care TREBUIE prins."""
    import ast
    cod = "def f(self):\n    self._cset('k', {})\n    self._cset('j', [])\n"
    arbore = ast.parse(cod)
    gasite = 0
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Call) and getattr(nod.func, "attr", "") == "_cset":
            val = nod.args[1]
            if (isinstance(val, ast.Dict) and not val.keys) or \
               (isinstance(val, ast.List) and not val.elts):
                gasite += 1
    assert gasite == 2, "detectorul de literal gol nu funcționează"


def test_cget_trateaza_dict_gol_ca_hit_proprietatea_care_cauza_defectul():
    """Documentează MECANISMUL, ca nimeni să nu „repare" în locul greșit.

    `_cget`/`if cached is not None` sunt CORECTE și rămân neatinse: un gol
    legitim trebuie servit din cache. Defectul era ce se SCRIA, nu ce se
    citea. Testul ăsta cade dacă cineva schimbă semantica citirii, crezând
    că acolo era problema."""
    api, spion, apeluri = _api([])
    spion.date["odds_x"] = {}
    assert api._cget("odds_x") == {}
    assert api._cget("odds_x") is not None, (
        "un dict gol trebuie să rămână un hit valid — altfel golurile "
        "legitime nu se mai cache-uiesc niciodată"
    )
