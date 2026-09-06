"""Ce înseamnă „meciuri noi de la ultimul Challenger" (Faza B, ADR-030).

DEFECTUL, măsurat live pe 2026-09-06, nu presupus: `_count_finished_matches()`
filtra pe **`created_at`** — ora la care RÂNDUL a fost scris prima dată, adică
momentul DESCOPERIRII meciului, nu al jucării lui.

Discovery găsește meciuri cu până la 7 zile înainte, iar
`flashscore_weekly_fixtures` descoperă etape întregi cu săptămâni înainte. Deci
un meci jucat pe 1 septembrie, descoperit pe 20 august, NU era „nou" pentru un
Challenger creat pe 24 august — deși rezultatul lui apăruse abia în septembrie.

Amploarea reală, pentru Challenger-ul `blend_v1` (creat 24 august):

    numărat de codul vechi (created_at) ....   5
    meciuri chiar jucate (kickoff_date) ..... 285

Cu pragul `MIN_SAMPLES_TO_TRAIN = 30`, Faza B ar fi REFUZAT să antreneze un
motor care avea 285 de meciuri noi de învățat — al doilea blocaj al antrenării,
complet independent de cel rezolvat prin ADR-057, latent doar fiindcă slotul lui
`blend_v1` e ocupat azi.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import learning_core.continuous_learning as cl


class _Interogare:
    """Client fals care CHIAR filtrează — unul care doar înregistrează apelurile
    ar lăsa să treacă o coloană greșită fără să spună nimic."""

    def __init__(self, randuri: list[dict], jurnal: dict):
        self._randuri = list(randuri)
        self._jurnal = jurnal

    def select(self, *a, **kw):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *a, **kw):
        return self

    def eq(self, col, val):
        self._jurnal.setdefault("eq", []).append((col, val))
        self._randuri = [r for r in self._randuri if r.get(col) == val]
        return self

    def gt(self, col, val):
        self._jurnal.setdefault("gt", []).append((col, val))
        self._randuri = [r for r in self._randuri if str(r.get(col, "")) > val]
        return self

    def execute(self):
        return type("R", (), {"data": list(self._randuri)})()


class _Client:
    def __init__(self, randuri: list[dict]):
        self._randuri = randuri
        self.jurnal: dict = {}

    def table(self, nume):
        assert nume == "match_history"
        return _Interogare(self._randuri, self.jurnal)


def _meci(id_: int, *, jucat: str, descoperit: str, liga: str = "Premier League") -> dict:
    return {"id": id_, "league": liga, "kickoff_date": jucat, "created_at": descoperit}


# ════════════════════════════════════════════════════════════════════════
# GARDA CENTRALĂ — scenariul real care a produs 5 în loc de 285
# ════════════════════════════════════════════════════════════════════════

def test_meciurile_descoperite_devreme_dar_jucate_tarziu_SUNT_numarate(monkeypatch):
    """Tiparul exact al defectului: toate meciurile au fost DESCOPERITE înainte
    de crearea Challenger-ului, dar JUCATE după. Codul vechi întorcea 0."""
    randuri = [
        _meci(i, jucat="2026-09-01", descoperit="2026-08-20")
        for i in range(1, 51)
    ]
    client = _Client(randuri)
    monkeypatch.setattr(cl, "get_client", lambda: client)

    n = cl._count_finished_matches("all", since="2026-08-24 05:56:40.28055+00")

    assert n == 50, (
        "meciuri jucate DUPĂ crearea Challenger-ului trebuie numărate, "
        "indiferent când au fost descoperite"
    )
    assert client.jurnal["gt"][0][0] == "kickoff_date", (
        "filtrul trebuie să fie pe momentul jucării, nu al descoperirii"
    )


def test_meciurile_jucate_inainte_nu_sunt_numarate(monkeypatch):
    """Contraponderea. Fără ea, un filtru care nu exclude nimic ar trece testul
    de mai sus fără să dovedească ceva."""
    randuri = [_meci(i, jucat="2026-08-10", descoperit="2026-08-01") for i in range(1, 21)]
    client = _Client(randuri)
    monkeypatch.setattr(cl, "get_client", lambda: client)

    assert cl._count_finished_matches("all", since="2026-08-24 05:56:40.28055+00") == 0


def test_amestecul_real_numara_doar_ce_s_a_jucat_dupa(monkeypatch):
    randuri = (
        [_meci(i, jucat="2026-08-10", descoperit="2026-08-25") for i in range(1, 6)]      # jucate înainte, descoperite după
        + [_meci(100 + i, jucat="2026-09-01", descoperit="2026-08-20") for i in range(1, 8)]  # jucate după, descoperite înainte
    )
    client = _Client(randuri)
    monkeypatch.setattr(cl, "get_client", lambda: client)

    assert cl._count_finished_matches("all", since="2026-08-24 05:56:40.28055+00") == 7


def test_fara_since_se_numara_tot(monkeypatch):
    client = _Client([_meci(i, jucat="2020-01-01", descoperit="2020-01-01") for i in range(1, 13)])
    monkeypatch.setattr(cl, "get_client", lambda: client)

    assert cl._count_finished_matches("all", since=None) == 12
    assert "gt" not in client.jurnal


def test_filtrul_de_liga_ramane_neatins(monkeypatch):
    randuri = [
        _meci(1, jucat="2026-09-01", descoperit="2026-08-01", liga="Premier League"),
        _meci(2, jucat="2026-09-01", descoperit="2026-08-01", liga="La Liga"),
    ]
    client = _Client(randuri)
    monkeypatch.setattr(cl, "get_client", lambda: client)

    assert cl._count_finished_matches("Premier League", since="2026-08-24 05:56:40+00") == 1
    assert ("league", "Premier League") in client.jurnal["eq"]


# ════════════════════════════════════════════════════════════════════════
# _prag_kickoff — normalizarea, funcție pură
# ════════════════════════════════════════════════════════════════════════

def test_pragul_transforma_spatiul_postgres_in_T():
    """Postgres întoarce `2026-08-24 05:56:40.28055+00` (SPAȚIU), iar
    `kickoff_date` folosește `T`. Spațiul (0x20) se ordonează înaintea lui `T`
    (0x54), deci comparația pe șirul brut ar fi ieșit corect din întâmplare —
    exact ce se strică tăcut la o schimbare de bibliotecă."""
    assert cl._prag_kickoff("2026-08-24 05:56:40.28055+00") == "2026-08-24T05:56:40"


def test_pragul_taie_fractiunile_si_fusul_orar():
    assert cl._prag_kickoff("2026-08-24T05:56:40.123456+00:00") == "2026-08-24T05:56:40"
    assert cl._prag_kickoff("2026-08-24T05:56:40Z") == "2026-08-24T05:56:40"


def test_pragul_suporta_intrari_degenerate_fara_sa_arunce():
    assert cl._prag_kickoff("") == ""
    assert cl._prag_kickoff(None) == ""  # type: ignore[arg-type]
    assert cl._prag_kickoff("2026") == "2026"


def test_meciul_din_ACEEASI_ZI_dar_mai_devreme_NU_e_numarat(monkeypatch):
    """GARDA care justifică normalizarea — singurul caz în care pragul brut dă
    alt rezultat decât cel normalizat.

    Fără normalizare, `2026-08-24T03:00:00` > `2026-08-24 05:56:40+00` (pentru
    că `T` = 0x54 se ordonează după spațiul = 0x20), deci un meci jucat cu trei
    ore ÎNAINTE de crearea Challenger-ului ar fi numărat drept „nou".

    Prima versiune a acestei suite folosea doar zile diferite — iar mutația
    „prag nenormalizat" trecea nedetectată. Găsit prin testare de mutație, nu
    prin citire."""
    randuri = [
        _meci(1, jucat="2026-08-24T03:00:00", descoperit="2026-08-01"),   # înainte
        _meci(2, jucat="2026-08-24T13:00:00", descoperit="2026-08-01"),   # după
    ]
    client = _Client(randuri)
    monkeypatch.setattr(cl, "get_client", lambda: client)

    n = cl._count_finished_matches("all", since="2026-08-24 05:56:40.28055+00")

    assert n == 1, "doar meciul jucat DUPĂ ora creării Challenger-ului se numără"
    assert client.jurnal["gt"] == [("kickoff_date", "2026-08-24T05:56:40")]


def test_ordonarea_lexicografica_e_corecta_pe_ambele_formate_reale():
    """Coloana are exact două formate (verificat live: 57.323 doar cu data, 822
    cu oră, zero alt format). Comparația pe text trebuie să le ordoneze corect
    între ele — altfel paginile de mai sus nu dovedesc nimic."""
    prag = cl._prag_kickoff("2026-09-06 12:00:00+00")
    assert "2026-09-06" < prag < "2026-09-06T14:00:00"
    assert "2026-09-05" < prag
    assert "2026-09-07" > prag
