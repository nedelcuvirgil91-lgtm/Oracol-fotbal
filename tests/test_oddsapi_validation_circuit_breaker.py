"""Validarea cheii Odds API (`/sports`) — eșecul se MEMOREAZĂ între instanțe.

DEFECTUL, măsurat înainte de reparație: `_odds_keys_validated` e PER-INSTANȚĂ,
iar o rulare de noapte creează mai multe `FootballOracleAPI()`
(odds_persistence, weather_forecast, team_health, Challenger Shadow Batch),
fiecare cu propria cerere `/sports`. Când cheia e invalidă, nimeni nu ținea
minte eșecul: **418 apeluri HTTP 401 în 8 zile**, 30-113 pe zi.
`/sports` e gratuit, deci costul nu era în credite — era în 418 eșecuri pe
care nu le-a observat nimeni.

DISTINCȚIA FAȚĂ DE DEFECTUL REPARAT ÎN `_fetch_odds`, și e motivul pentru care
acest fișier există separat: acolo un eșec era scris în cache și **servit ca
date** (`{}`, indistingibil de un gol legitim). Aici marcajul **nu e întors
niciodată ca rezultat** — decide exclusiv DACĂ se mai încearcă cererea.
Un întrerupător care ține minte că a sărit siguranța nu e o minciună despre
tensiune. Testul `test_marcajul_nu_e_niciodata_servit_ca_rezultat` apără
exact asta.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import cache_manager
import oracle_api


def _api(raspuns_sports, marcaj_initial=None, cache=None, cheie_disponibila=True):
    """API fără `__init__`, cu `/sports` servind `raspuns_sports`.
    `apeluri` numără cererile reale — semnalul prin care se vede dacă
    întrerupătorul a suprimat tentativa.

    `cache` poate fi PARTAJAT între două instanțe, ca să se poată exercita
    firul real (instanța 1 scrie → instanța 2 citește), nu doar cele două
    capete separat."""
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._dead_keys = set()
    api._active_sport_keys = set()
    api._odds_keys_validated = False

    if cache is None:
        cache = {}
    if marcaj_initial is not None:
        cache[oracle_api.FootballOracleAPI._VALIDATION_MARKER_KEY] = marcaj_initial
    scrieri: list[tuple[str, object]] = []
    apeluri: list[str] = []

    api._cget = lambda k: cache.get(k)                          # type: ignore[assignment]

    def _set(k, v):
        cache[k] = v
        scrieri.append((k, v))

    api._cset = _set                                            # type: ignore[assignment]

    class _FakeKM:
        def get_api_key_param(self, _p):
            # Oglindeste comportamentul real: `None` cand nu e cheie
            # utilizabila (key_manager.py:241-243). Un fals care ar intoarce
            # mereu un sir ar ascunde exact defectul auditat.
            return "cheie-falsa" if cheie_disponibila else None

        def is_available(self, _p): return cheie_disponibila

    api._key_manager = _FakeKM()

    def _get(_url, params=None):
        apeluri.append("sports")
        return raspuns_sports

    api._get = _get                                             # type: ignore[assignment]
    return api, cache, scrieri, apeluri


_SPORTS_OK = [
    {"key": "soccer_epl", "has_outrights": False},
    {"key": "soccer_spain_la_liga", "has_outrights": False},
]


# ── eșecul se memorează ───────────────────────────────────────────────────

def test_esec_scrie_marcaj_ok_false():
    api, _, scrieri, _ = _api(raspuns_sports=None)   # 401 → `_get` dă None
    api._ensure_odds_keys_validated()
    assert len(scrieri) == 1
    cheie, val = scrieri[0]
    assert cheie == api._VALIDATION_MARKER_KEY
    assert val["ok"] is False
    assert "at" in val, "marcajul trebuie să fie datat, altfel nu se poate audita"


def test_marcaj_proaspat_de_esec_SUPRIMA_cererea_pe_instanta_noua():
    """Proprietatea pentru care există reparația: a doua instanță nu mai cere."""
    api, _, _, apeluri = _api(raspuns_sports=None,
                              marcaj_initial={"ok": False, "at": "2026-10-27T09:18:00+00:00"})
    api._ensure_odds_keys_validated()
    assert apeluri == [], (
        "instanța a mai cerut `/sports` deși ultima validare eșuase — "
        "exact cele 418 apeluri măsurate"
    )


def test_marcaj_de_esec_nu_impiedica_restul_sa_functioneze():
    """Suprimarea nu trebuie să arunce și nu trebuie să marcheze chei moarte
    pe baza unei informații pe care nu o avem."""
    api, _, _, _ = _api(raspuns_sports=None, marcaj_initial={"ok": False, "at": "x"})
    api._ensure_odds_keys_validated()
    assert api._dead_keys == set(), (
        "fără un răspuns valid nu se știe care chei sunt moarte — "
        "a le marca ar fi fabricație (North Star #8)"
    )


# ── garda de precondiție: nu trimite o cerere care nu POATE reuși ─────────

def test_fara_cheie_utilizabila_NU_se_trimite_nicio_cerere():
    """Cauza rădăcină a celor 418 × HTTP 401, găsită de auditul `ODDS_API_KEY`.

    `get_api_key_param()` întoarce `None` fie când variabila lipsește din
    mediu (`keys: []`), fie când contorul lunar partajat a atins limita.
    `requests` OMITE un parametru `None`, deci cererea pleca spre `/sports`
    **fără `apiKey`** și primea 401 garantat. `is_available()` răspundea deja
    la întrebare și acoperă ambele cauze — nimeni nu o întreba aici.
    """
    api, _, _, apeluri = _api(raspuns_sports=_SPORTS_OK, cheie_disponibila=False)
    api._ensure_odds_keys_validated()
    assert apeluri == [], (
        "s-a trimis o cerere fără apiKey — 401 garantat, exact cele 418 "
        "apeluri măsurate"
    )


def test_fara_cheie_utilizabila_NU_scrie_marcaj_de_esec():
    """Separare deliberată: absența unei chei nu e un „eșec de validare" de
    ținut minte, e o PRECONDIȚIE neîndeplinită. Dacă ar scrie marcajul, o
    cheie adăugată între timp ar rămâne neîncercată 30 de minute degeaba."""
    api, _, scrieri, _ = _api(raspuns_sports=_SPORTS_OK, cheie_disponibila=False)
    api._ensure_odds_keys_validated()
    assert scrieri == []


def test_cu_cheie_disponibila_cererea_se_trimite_contrapondere():
    """Contrapondere: garda nu trebuie să blocheze cazul sănătos."""
    api, _, _, apeluri = _api(raspuns_sports=_SPORTS_OK, cheie_disponibila=True)
    api._ensure_odds_keys_validated()
    assert apeluri == ["sports"]


# ── FIRUL întreg, nu cele două capete ─────────────────────────────────────

def test_END_TO_END_instanta_1_esueaza_instanta_2_nu_mai_cere():
    """Testele de mai sus verifică SCRIEREA și CITIREA separat — una scrie
    marcajul, alta îl primește gata pus. Între ele e un fir pe care niciuna
    nu-l atinge, iar o mutație care șterge scrierea trecea prin a doua.

    Aici cele două instanțe împart cache-ul, exact ca două etape ale aceleiași
    rulări de noapte: prima eșuează, a doua trebuie să tacă. E proprietatea
    care a fost măsurată ca încălcată (418 apeluri), nu una dedusă.
    """
    cache_partajat: dict[str, object] = {}
    api1, _, _, apeluri1 = _api(raspuns_sports=None, cache=cache_partajat)
    api1._ensure_odds_keys_validated()
    assert apeluri1 == ["sports"], "prima instanță trebuie să încerce"

    api2, _, _, apeluri2 = _api(raspuns_sports=None, cache=cache_partajat)
    api2._ensure_odds_keys_validated()
    assert apeluri2 == [], (
        "a doua instanță a cerut din nou — eșecul nu s-a propagat prin cache"
    )


def test_END_TO_END_recuperare_instanta_1_reuseste_instanta_2_valideaza():
    """Simetricul: după un succes, următoarea instanță TREBUIE să valideze în
    continuare (altfel `_dead_keys` nu se mai populează niciodată)."""
    cache_partajat: dict[str, object] = {}
    api1, _, _, _ = _api(raspuns_sports=_SPORTS_OK, cache=cache_partajat)
    api1._ensure_odds_keys_validated()

    api2, _, _, apeluri2 = _api(raspuns_sports=_SPORTS_OK, cache=cache_partajat)
    api2._ensure_odds_keys_validated()
    assert apeluri2 == ["sports"]


# ── CONTRAPONDERI — succesul nu trebuie suprimat ──────────────────────────

def test_succes_scrie_marcaj_ok_true():
    api, _, scrieri, _ = _api(raspuns_sports=_SPORTS_OK)
    api._ensure_odds_keys_validated()
    marcaje = [v for k, v in scrieri if k == api._VALIDATION_MARKER_KEY]
    assert marcaje and marcaje[-1]["ok"] is True


def test_marcaj_ok_TRUE_NU_suprima_validarea():
    """Contrapondere esențială. Dacă un marcaj de succes ar suprima validarea,
    `_dead_keys` n-ar mai fi populat la instanța următoare, iar cheile moarte
    ar fi cerute degeaba — am repara un risipitor creând altul."""
    api, _, _, apeluri = _api(raspuns_sports=_SPORTS_OK,
                              marcaj_initial={"ok": True, "at": "x"})
    api._ensure_odds_keys_validated()
    assert apeluri == ["sports"], (
        "un marcaj de SUCCES a suprimat validarea — doar eșecul trebuie să o facă"
    )


def test_fara_marcaj_valideaza():
    api, _, _, apeluri = _api(raspuns_sports=_SPORTS_OK)
    api._ensure_odds_keys_validated()
    assert apeluri == ["sports"]


def test_succes_dupa_esec_suprascrie_marcajul_deci_recuperare_imediata():
    """O cheie reparată nu trebuie să aștepte expirarea TTL-ului."""
    api, cache, _, _ = _api(raspuns_sports=_SPORTS_OK)
    api._ensure_odds_keys_validated()
    assert cache[api._VALIDATION_MARKER_KEY]["ok"] is True


def test_dead_keys_se_populeaza_in_continuare_la_succes():
    """Comportamentul original, neatins: cheile absente din răspuns sunt moarte."""
    api, _, _, _ = _api(raspuns_sports=_SPORTS_OK)
    api._ensure_odds_keys_validated()
    assert api._dead_keys, "nicio cheie moartă marcată — validarea nu mai are efect"
    assert "soccer_epl" not in api._dead_keys


def test_flagul_per_instanta_opreste_a_doua_cerere_in_aceeasi_instanta():
    """Comportamentul de dinainte, păstrat — reparația e în plus, nu în loc."""
    api, _, _, apeluri = _api(raspuns_sports=_SPORTS_OK)
    api._ensure_odds_keys_validated()
    api._ensure_odds_keys_validated()
    assert apeluri == ["sports"]


# ── marcajul nu e date ────────────────────────────────────────────────────

def test_marcajul_nu_e_niciodata_servit_ca_rezultat():
    """Distincția față de defectul `_fetch_odds`. `_ensure_odds_keys_validated`
    nu întoarce nimic — deci marcajul nu poate ajunge la un apelant ca și cum
    ar fi un răspuns de provider, oricât de vechi ar fi."""
    api, _, _, _ = _api(raspuns_sports=None, marcaj_initial={"ok": False, "at": "x"})
    assert api._ensure_odds_keys_validated() is None


# ── rutarea cheii — coliziunea care ar goli marcajul cu cache-ul de cote ──

def test_cheia_marcajului_cade_pe_categoria_proprie_cu_TTL_scurt():
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    cat = api._category_for_key(api._VALIDATION_MARKER_KEY)
    assert cat == "oddsapi_validation"
    assert cache_manager.CATEGORY_TTL[cat] == 0.5, (
        "TTL-ul marcajului nu mai e 30 min — prea scurt reintroduce furtuna, "
        "prea lung ține o cheie reparată blocată"
    )


def test_cheia_marcajului_NU_cade_pe_categoria_odds():
    """Garda împotriva unei redenumiri aparent inofensive. Dacă cheia ar începe
    cu `odds_`, ar ajunge în categoria `odds` — deci ar fi golită împreună cu
    cache-ul de cote și ar moșteni TTL-ul lui (4h, iar după mărirea aprobată
    24h), transformând întrerupătorul într-un blocaj de o zi."""
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    assert not api._VALIDATION_MARKER_KEY.startswith("odds_")
    assert api._category_for_key(api._VALIDATION_MARKER_KEY) != "odds"


def test_cheile_de_cote_NU_au_fost_mutate_din_categoria_odds():
    """Contrapondere la garda de mai sus: prefixul nou nu trebuie să fure
    rutarea celor existente. `_category_for_key` ia PRIMA potrivire."""
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    assert api._category_for_key("odds_soccer_epl") == "odds"
    assert api._category_for_key("events_soccer_epl_7") == "odds"


def test_providerul_marcajului_e_oddsapi():
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    assert api._provider_for_key(api._VALIDATION_MARKER_KEY) == "oddsapi"
