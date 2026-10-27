"""Paginare în fereastra Champion Guardian — a CINCEA instanță a plafonului
PostgREST de 1000, și prima cu direcția trunchierii ADVERSĂ.

CONTEXT (măsurat live pe producție, 2026-10-27, nu presupus):
`supabase_client.get_champion_served_outcomes()` — substratul evaluării de
sănătate a campionului (ADR-037/R2.4) — citea printr-un singur `.execute()`
fără paginare. PostgREST taie implicit la „Max Rows" = 1000.

Pe fereastra reală a campionului activ (`blend_v1/all`, promovat 23 august):
**1135 de rânduri eligibile**, deci 135 (11,9%) invizibile. Trecerea peste
plafon s-a produs pe 23 octombrie (cumulat 1006).

DE CE DIRECȚIA E CE CONTEAZĂ AICI, spre deosebire de celelalte patru instanțe
reparate în proiect: ordonarea era `kickoff_date, fixture_id` ASCENDENT, deci
trunchierea păstra cele mai VECHI 1000 de meciuri și arunca cele mai NOI 135.
Iar dimensiunea „trend" a gardianului împarte fereastra 50/50 și compară
jumătatea recentă cu cea anterioară — „recent" ar fi însemnat *meciuri de la
mijlocul lui octombrie*. Un monitor de sănătate care ignoră prin construcție
exact capătul care ar dezvălui o degradare.

Clientul Supabase e FALS și APLICĂ efectiv filtrele, ordonarea și — critic —
**plafonul IMPLICIT, chiar când apelantul nu cere niciun `.limit()`**. Aceea e
proprietatea care definește clasa de defect; un fals care taie doar la `limit`
explicit ar lăsa codul rupt să treacă (lecție plătită în ADR-080, M1).
`test_plafonul_implicit_al_falsului_prinde_defectul_original` o dovedește, în
loc s-o promită.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import pytest

import supabase_client as sb


# Niciun test de-aici nu are nevoie de mai mult de ~4 cereri.
_MAX_CERERI = 40

# Legat de constanta din cod, nu scris de mână: dacă unul se schimbă fără
# celălalt, testele trebuie să cadă, nu să continue pe o presupunere.
_PLAFON_IMPLICIT = sb._PAGE_SIZE


# ════════════════════════════════════════════════════════════════════════════
# Client fals care se comportă ca PostgREST: WHERE → ORDER → LIMIT (implicit)
# ════════════════════════════════════════════════════════════════════════════

def _colationare(v):
    """Emulează ordinea `en_US.UTF-8` a bazei de producție (verificat:
    `pg_database.datcollate`), în care greutatea literei primează asupra
    codului de octet — `flashscore_hGycdKve < flashscore_UHKVUvoK`, deși pe
    octeți `U`(0x55) < `h`(0x68).

    Fără emularea asta, falsul ar ordona pe octeți, adică exact cum ordonează
    Python — iar testul care fixează departajarea din interiorul unei zile ar
    trece indiferent de implementare. Aceeași clasă ca plafonul implicit:
    un fals care nu reproduce proprietatea serverului nu dovedește nimic.

    Se aplică identic la ordonare ȘI la comparațiile de cursor (`gt`/`gte`) —
    în baza reală ambele folosesc aceeași colaționare, iar un fals care le-ar
    amesteca ar sări sau dubla rânduri la granița de pagină, producând un eșec
    fals, al falsului, nu al codului."""
    if not isinstance(v, str):
        return v
    return (v.lower(), v)


class _Negat:
    """Suportă `q.not_.is_(col, "null")` — forma reală folosită de cod."""

    def __init__(self, q):
        self._q = q

    def is_(self, col, val):
        self._q._not_is.append((col, val))
        return self._q


class _FakeQuery:
    def __init__(self, rows, jurnal, esec_la, numarator):
        self._rows = rows
        self._jurnal = jurnal
        self._esec_la = esec_la
        self._numarator = numarator
        self._select = "*"
        self._eq: list[tuple[str, object]] = []
        self._not_is: list[tuple[str, object]] = []
        self._gte: list[tuple[str, object]] = []
        self._gt: list[tuple[str, object]] = []
        self._order: list[str] = []
        self._limit: int | None = None

    @property
    def not_(self):
        return _Negat(self)

    def select(self, coloane="*", *_a, **_k):
        self._select = coloane
        return self

    def eq(self, col, val):
        self._eq.append((col, val))
        return self

    def gte(self, col, val):
        self._gte.append((col, val))
        return self

    def gt(self, col, val):
        self._gt.append((col, val))
        return self

    def order(self, col, *_a, **_k):
        self._order.append(col)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        self._numarator[0] += 1
        # Un cursor luat din PRIMUL rând al paginii în loc de ultimul avansează
        # cu un rând per cerere: codul tot se termină, dar după mii de cereri —
        # la test asta arată ca un blocaj, nu ca un eșec cu nume.
        if self._numarator[0] > _MAX_CERERI:
            raise AssertionError(
                f"paginare scăpată de sub control: peste {_MAX_CERERI} cereri "
                "pentru un set care are nevoie de câteva — cursorul nu avansează"
            )
        if self._esec_la is not None and self._numarator[0] == self._esec_la:
            raise RuntimeError("rețea căzută la mijlocul paginării")

        randuri = list(self._rows)
        for col, val in self._eq:
            randuri = [r for r in randuri if r.get(col) == val]
        for col, val in self._not_is:
            if val == "null":
                randuri = [r for r in randuri if r.get(col) is not None]
        for col, val in self._gte:
            randuri = [r for r in randuri if r.get(col) is not None
                       and _colationare(r[col]) >= _colationare(val)]
        for col, val in self._gt:
            randuri = [r for r in randuri if r.get(col) is not None
                       and _colationare(r[col]) > _colationare(val)]
        for col in reversed(self._order):
            randuri.sort(key=lambda r: _colationare(r.get(col) or ""))
        # PLAFONUL IMPLICIT, nu doar cel cerut.
        taiere = _PLAFON_IMPLICIT if self._limit is None else min(self._limit, _PLAFON_IMPLICIT)
        randuri = randuri[:taiere]

        self._jurnal.append({
            "select": self._select, "eq": list(self._eq),
            "not_is": list(self._not_is), "gte": list(self._gte),
            "gt": list(self._gt), "order": list(self._order),
            "limit": self._limit, "returnate": len(randuri),
        })
        return type("R", (), {"data": randuri})()


class _FakeClient:
    def __init__(self, randuri, esec_la=None):
        self._randuri = randuri
        self.jurnal: list[dict] = []
        self._esec_la = esec_la
        self._numarator = [0]

    def table(self, _nume):
        return _FakeQuery(self._randuri, self.jurnal, self._esec_la, self._numarator)


def _meci(i: int, *, zi: str | None = None, liga: str = "Premier League",
          rezultat: str = "H", prob=0.45) -> dict:
    return {
        "fixture_id": f"fx_{i:05d}",
        "home_team": f"H{i}", "away_team": f"A{i}", "league": liga,
        "kickoff_date": zi if zi is not None else "2026-09-%02d" % ((i % 28) + 1),
        "prob_home_pred": prob, "prob_draw_pred": 0.30, "prob_away_pred": 0.25,
        "actual_result": rezultat,
    }


@pytest.fixture
def leaga(monkeypatch):
    """Înlocuiește clientul și întoarce fabrica de fals."""
    def _leaga(randuri, esec_la=None):
        fake = _FakeClient(randuri, esec_la=esec_la)
        monkeypatch.setattr(sb, "get_client", lambda: fake)
        return fake
    return _leaga


# ════════════════════════════════════════════════════════════════════════════
# Meta-test: falsul chiar poate prinde defectul original
# ════════════════════════════════════════════════════════════════════════════

def test_plafonul_implicit_al_falsului_prinde_defectul_original(leaga):
    """Docstring-ul fișierului promite că falsul taie și fără `.limit()`.
    Aici se dovedește, pe o citire făcută exact ca varianta ruptă — altfel
    toată suita ar sta pe o promisiune."""
    randuri = [_meci(i) for i in range(_PLAFON_IMPLICIT + 135)]
    fake = leaga(randuri)
    q = (fake.table("match_history").select("fixture_id")
         .not_.is_("prob_home_pred", "null"))
    primite = q.order("kickoff_date").order("fixture_id").execute().data
    assert len(primite) == _PLAFON_IMPLICIT, (
        "falsul nu aplică plafonul implicit — orice test de paginare de aici "
        "ar trece fără să dovedească nimic"
    )


# ════════════════════════════════════════════════════════════════════════════
# Completitudine
# ════════════════════════════════════════════════════════════════════════════

def test_set_sub_plafon_o_singura_cerere(leaga):
    fake = leaga([_meci(i) for i in range(250)])
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert len(out) == 250
    assert len(fake.jurnal) == 1, "o pagină incompletă nu justifică a doua cerere"


def test_set_peste_plafon_se_intoarce_INTREG(leaga):
    """Cazul real măsurat: 1135 eligibile, 1000 vizibile înainte de reparație."""
    n = _PLAFON_IMPLICIT + 135
    fake = leaga([_meci(i) for i in range(n)])
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert len(out) == n
    assert len(fake.jurnal) == 2
    assert {r["fixture_id"] for r in out} == {f"fx_{i:05d}" for i in range(n)}


def test_cele_mai_NOI_randuri_nu_se_pierd(leaga):
    """Direcția e miezul defectului: trunchierea arunca cele mai noi meciuri,
    iar dimensiunea «trend» a gardianului se calculează exact pe ele."""
    n = _PLAFON_IMPLICIT + 135
    randuri = [_meci(i, zi=f"2026-10-{(i % 30) + 1:02d}") for i in range(n - 5)]
    randuri += [_meci(9000 + k, zi="2026-12-31") for k in range(5)]
    leaga(randuri)
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert sum(1 for r in out if r["kickoff_date"] == "2026-12-31") == 5


def test_exact_pe_plafon_cere_a_doua_pagina_si_nu_dubleaza(leaga):
    fake = leaga([_meci(i) for i in range(_PLAFON_IMPLICIT)])
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert len(out) == _PLAFON_IMPLICIT
    assert len({r["fixture_id"] for r in out}) == _PLAFON_IMPLICIT
    assert len(fake.jurnal) == 2, "o pagină plină nu poate dovedi că nu mai urmează"


def test_trei_pagini(leaga):
    n = 2 * _PLAFON_IMPLICIT + 7
    fake = leaga([_meci(i) for i in range(n)])
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert len(out) == n
    assert len(fake.jurnal) == 3


# ════════════════════════════════════════════════════════════════════════════
# Cursorul
# ════════════════════════════════════════════════════════════════════════════

def test_cursorul_vine_din_ULTIMUL_rand_al_paginii(leaga):
    n = _PLAFON_IMPLICIT + 10
    fake = leaga([_meci(i) for i in range(n)])
    sb.get_champion_served_outcomes("blend_v1", "all", None)
    a_doua = fake.jurnal[1]
    assert a_doua["gt"] == [("fixture_id", f"fx_{_PLAFON_IMPLICIT - 1:05d}")]


def test_prima_cerere_nu_are_cursor(leaga):
    fake = leaga([_meci(i) for i in range(_PLAFON_IMPLICIT + 3)])
    sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert fake.jurnal[0]["gt"] == []


def test_fiecare_cerere_are_cel_mult_UN_cursor(leaga):
    """Constructorul se creează în buclă; reutilizat, `gt` s-ar acumula
    (vezi `tests/test_pagination_builder_reuse.py` pentru garda structurală)."""
    fake = leaga([_meci(i) for i in range(2 * _PLAFON_IMPLICIT + 1)])
    sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert all(len(c["gt"]) <= 1 for c in fake.jurnal)
    assert all(len(c["gte"]) <= 1 for c in fake.jurnal)


def test_fiecare_cerere_cere_EXPLICIT_limita(leaga):
    """Găsit prin mutație (M8): ștergerea lui `.limit(_PAGE_SIZE)` nu rupea
    nimic, fiindcă plafonul implicit al serverului e **întâmplător** egal cu
    `_PAGE_SIZE`. Coincidența asta nu e un contract: dacă `_PAGE_SIZE` ar
    crește vreodată la 2000, o pagină tăiată implicit la 1000 ar satisface
    `len(page) < _PAGE_SIZE` și bucla s-ar opri după prima pagină — exact
    trunchierea tocmai reparată, revenită pe altă cale. Limita cerută
    explicit face codul independent de valoarea plafonului serverului."""
    fake = leaga([_meci(i) for i in range(_PLAFON_IMPLICIT + 5)])
    sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert fake.jurnal, "nicio cerere făcută"
    assert all(c["limit"] == _PLAFON_IMPLICIT for c in fake.jurnal), (
        "paginarea nu are voie să se sprijine pe plafonul implicit al serverului"
    )


def test_cursorul_e_pe_cheia_de_ordonare_a_cererii(leaga):
    """Keyset valid doar dacă `gt` și `order` sunt pe ACEEAȘI coloană —
    altfel paginile se pot suprapune sau sări rânduri."""
    fake = leaga([_meci(i) for i in range(_PLAFON_IMPLICIT + 2)])
    sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert fake.jurnal[1]["order"][0] == fake.jurnal[1]["gt"][0][0] == "fixture_id"


# ════════════════════════════════════════════════════════════════════════════
# Ordinea contractuală a rezultatului
# ════════════════════════════════════════════════════════════════════════════

def test_rezultatul_e_ordonat_cronologic(leaga):
    randuri = [
        _meci(3, zi="2026-09-10"), _meci(1, zi="2026-09-12"),
        _meci(2, zi="2026-09-10"), _meci(4, zi="2026-08-30"),
    ]
    leaga(randuri)
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert [(r["kickoff_date"], r["fixture_id"]) for r in out] == [
        ("2026-08-30", "fx_00004"),
        ("2026-09-10", "fx_00002"),
        ("2026-09-10", "fx_00003"),
        ("2026-09-12", "fx_00001"),
    ]


def test_departajarea_din_aceeasi_zi_pastreaza_ordinea_BAZEI_nu_pe_octeti(leaga):
    """Proprietatea cea mai subtilă a reparației, găsită MĂSURÂND, nu deducând.

    Ordonarea veche era `ORDER BY kickoff_date, fixture_id` — ambele în
    colaționarea bazei (`en_US.UTF-8`). O sortare Python pe
    `(kickoff_date, fixture_id)` ar departaja pe OCTEȚI, deci ar permuta
    ordinea din interiorul unei zile. Măsurat pe fereastra reală de 1135 de
    rânduri: 295 de poziții diferite, din 256 de perechi din aceeași zi.

    Reparația păstrează ordinea veche sortând STABIL pe `kickoff_date` singur,
    lăsând ordinea de preluare (colaționarea bazei) să departajeze. Numele de
    mai jos sunt exact perechea reală găsită în producție.

    Cade dacă cineva „îmbunătățește" sortarea adăugând cheia secundară."""
    randuri = [
        _meci(1, zi="2026-09-20"), _meci(2, zi="2026-09-20"),
        _meci(3, zi="2026-09-20"),
    ]
    randuri[0]["fixture_id"] = "flashscore_UHKVUvoK"   # pe octeți ar fi PRIMUL
    randuri[1]["fixture_id"] = "flashscore_hGycdKve"   # în baza reală e primul
    randuri[2]["fixture_id"] = "flashscore_OrdYcWu9"
    leaga(randuri)
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert [r["fixture_id"] for r in out] == [
        "flashscore_hGycdKve", "flashscore_OrdYcWu9", "flashscore_UHKVUvoK",
    ], "departajarea s-a făcut pe octeți — ordinea diferă de cea veche din Postgres"


def test_departajarea_se_pastreaza_si_peste_granita_de_pagina(leaga):
    """Aceeași proprietate, dar pe un set care se pagineaza: dacă ordinea de
    preluare nu s-ar păstra la concatenare, departajarea s-ar rupe exact la
    granița dintre pagini."""
    n = _PLAFON_IMPLICIT + 40
    randuri = [_meci(i, zi="2026-09-20") for i in range(n)]
    # Toate în aceeași zi, cu nume în care litera mare apare la întâmplare.
    for i, r in enumerate(randuri):
        baza = f"fx{i:05d}"
        r["fixture_id"] = baza.upper() if i % 3 == 0 else baza
    leaga(randuri)
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert len(out) == n
    chei = [_colationare(r["fixture_id"]) for r in out]
    assert chei == sorted(chei), (
        "ordinea de preluare (colaționarea bazei) nu s-a păstrat în interiorul zilei"
    )


def test_ordinea_e_TOTALA_peste_granita_de_pagina(leaga):
    """Preluarea merge pe `fixture_id`, deci ordinea cronologică se obține
    abia la final. Dacă sortarea finală lipsește, un set care trece granița
    de pagină iese amestecat — exact ce ar strica împărțirea 50/50 a trendului."""
    n = _PLAFON_IMPLICIT + 50
    # Zile DESCRESCĂTOARE pe măsură ce fixture_id crește: ordinea de preluare
    # e inversul celei contractuale.
    randuri = [_meci(i, zi=f"2026-{((n - i) % 12) + 1:02d}-15") for i in range(n)]
    leaga(randuri)
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    zile = [r["kickoff_date"] for r in out]
    assert zile == sorted(zile)


def test_cele_doua_forme_de_kickoff_date_se_ordoneaza_ca_in_postgres(leaga):
    """`kickoff_date` e TEXT și ține două forme. Ordonarea trebuie să rămână
    lexicografică, identică celei vechi din Postgres — forma scurtă a unei
    zile precede formele cu oră ale aceleiași zile."""
    randuri = [
        _meci(2, zi="2026-08-23T18:00:00"),
        _meci(1, zi="2026-08-23"),
        _meci(3, zi="2026-08-23T00:30:00"),
    ]
    leaga(randuri)
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert [r["kickoff_date"] for r in out] == [
        "2026-08-23", "2026-08-23T00:30:00", "2026-08-23T18:00:00",
    ]


def test_kickoff_date_nul_nu_arunca(leaga):
    """Măsurat 0 rânduri cu `kickoff_date` NULL pe fereastra de azi, dar
    coloana e nullable în schemă — sortarea nu are voie să cadă pe ea."""
    leaga([_meci(1, zi=None), _meci(2, zi="2026-09-01")])
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert len(out) == 2


# ════════════════════════════════════════════════════════════════════════════
# Filtre — neschimbate de reparație, deci contraponderi
# ════════════════════════════════════════════════════════════════════════════

def test_league_scope_all_nu_filtreaza_liga(leaga):
    fake = leaga([_meci(1, liga="MLS"), _meci(2, liga="Premier League")])
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert len(out) == 2
    assert fake.jurnal[0]["eq"] == []


def test_league_scope_concret_filtreaza(leaga):
    leaga([_meci(1, liga="MLS"), _meci(2, liga="Premier League")])
    out = sb.get_champion_served_outcomes("blend_v1", "MLS", None)
    assert [r["league"] for r in out] == ["MLS"]


def test_since_date_se_aplica_pe_fiecare_pagina(leaga):
    n = _PLAFON_IMPLICIT + 5
    randuri = [_meci(i, zi="2026-07-01") for i in range(10)]
    randuri += [_meci(100 + i, zi="2026-09-01") for i in range(n)]
    fake = leaga(randuri)
    out = sb.get_champion_served_outcomes("blend_v1", "all", "2026-08-23")
    assert len(out) == n
    assert all(c["gte"] == [("kickoff_date", "2026-08-23")] for c in fake.jurnal)


def test_since_date_absent_nu_se_aplica(leaga):
    fake = leaga([_meci(1, zi="2026-01-01")])
    assert len(sb.get_champion_served_outcomes("blend_v1", "all", None)) == 1
    assert fake.jurnal[0]["gte"] == []


def test_exclude_randurile_fara_predictie_sau_fara_rezultat(leaga):
    randuri = [_meci(1), _meci(2), _meci(3)]
    randuri[1]["prob_home_pred"] = None
    randuri[2]["actual_result"] = None
    fake = leaga(randuri)
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert [r["fixture_id"] for r in out] == ["fx_00001"]
    assert ("prob_home_pred", "null") in fake.jurnal[0]["not_is"]
    assert ("actual_result", "null") in fake.jurnal[0]["not_is"]


def test_nu_se_citeste_steluta(leaga):
    fake = leaga([_meci(1)])
    sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert fake.jurnal[0]["select"] != "*"
    assert "fixture_id" in fake.jurnal[0]["select"]


# ════════════════════════════════════════════════════════════════════════════
# Degradare
# ════════════════════════════════════════════════════════════════════════════

def test_eroare_la_mijloc_intoarce_lista_GOALA_nu_parcursul_partial(leaga):
    """Deliberat diferit de `get_training_data()`, care întoarce parțialul.
    Acolo un parțial dă un model mai slab dar onest; aici ar da un verdict de
    sănătate FALS, pe o fereastră incompletă care arată ca una completă."""
    leaga([_meci(i) for i in range(_PLAFON_IMPLICIT + 20)], esec_la=2)
    out = sb.get_champion_served_outcomes("blend_v1", "all", None)
    assert out == []


def test_eroare_la_prima_cerere_intoarce_lista_goala(leaga):
    leaga([_meci(i) for i in range(10)], esec_la=1)
    assert sb.get_champion_served_outcomes("blend_v1", "all", None) == []


def test_client_absent_intoarce_lista_goala(monkeypatch):
    monkeypatch.setattr(sb, "get_client", lambda: None)
    assert sb.get_champion_served_outcomes("blend_v1", "all", None) == []


def test_zero_randuri_eligibile_e_stare_legitima(leaga):
    """ADR-037 Risk R-A: fereastră goală = stare validă, nu eroare."""
    fake = leaga([])
    assert sb.get_champion_served_outcomes("blend_v1", "all", None) == []
    assert len(fake.jurnal) == 1
