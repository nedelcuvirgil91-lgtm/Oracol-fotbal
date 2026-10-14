"""Paginare în citirile de evaluare shadow — plafonul PostgREST de 1000 rânduri.

CONTEXT (măsurat live, 2026-09-06, nu presupus): `evaluate_experiment()` citea
rândurile shadow printr-un singur `select("*")` fără paginare. PostgREST taie
implicit orice astfel de cerere la 1000 de rânduri („Max Rows"). Pentru
Challenger-ul `xgboost_v1` (`e638c1dc…`) cererea aducea 1364 de rânduri
(control + treatment), deci era trunchiată, iar apelantul rămânea cu 403
meciuri eligibile în loc de 506 reale.

Mai grav decât pierderea: fără `ORDER BY`, Postgres putea întoarce ALTE 1000
de rânduri de la o zi la alta. `n_matches_evaluated` sărea 344 → 392 → 402 →
394 → 394 → 402 → 413 → 403, deși fereastra de evaluare doar creștea. Verdictul
de promovare se calcula pe un subeșantion arbitrar, nedeterminist.

Aceeași capcană fusese deja reparată o dată în proiect — vezi comentariul din
`supabase_client.get_training_data()`, unde modelul ML se antrena pe 1000 din
50.000+ meciuri.

Clientul Supabase e FALS și APLICĂ efectiv filtrele/ordonarea/limita — un fals
care ignoră `limit()` ar face testele să treacă fără să dovedească nimic.
Fără rețea, fără Supabase.
"""
from __future__ import annotations

import pytest

import shadow_testing as st


# ════════════════════════════════════════════════════════════════════════════
# Client fals care se comportă ca PostgREST: filtrează, ordonează, TAIE la limit
# ════════════════════════════════════════════════════════════════════════════

# Niciun test de-aici nu are nevoie de mai mult de 3-4 cereri pe tabelă.
_MAX_CERERI = 40

# „Max Rows" al PostgREST: plafonul pe care serverul îl aplică SINGUR, fără
# ca apelantul să ceară ceva. Legat de `_PAGE_SIZE` din cod, nu scris de mână
# — dacă unul se schimbă vreodată fără celălalt, testele trebuie să cadă, nu
# să continue pe o presupunere.
_PLAFON_IMPLICIT = st._PAGE_SIZE


class _FakeQuery:
    def __init__(self, rows: list[dict], jurnal: list[dict], esec_la: int | None,
                 numarator: list[int]):
        self._rows = rows
        self._jurnal = jurnal
        self._esec_la = esec_la
        self._numarator = numarator
        self._eq: list[tuple[str, object]] = []
        self._is: list[tuple[str, object]] = []
        self._gt: list[tuple[str, object]] = []
        self._in: tuple[str, list] | None = None
        self._order: str | None = None
        self._limit: int | None = None
        self._select: str = "*"

    def select(self, coloane="*", *_a, **_k):
        self._select = coloane
        return self

    def eq(self, col, val):
        self._eq.append((col, val))
        return self

    def is_(self, col, val):
        self._is.append((col, val))
        return self

    def gt(self, col, val):
        self._gt.append((col, val))
        return self

    def in_(self, col, valori):
        self._in = (col, list(valori))
        return self

    def order(self, col, *_a, **_k):
        self._order = col
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        self._numarator[0] += 1
        # Plasă contra paginării scăpate de sub control. Un cursor greșit (ex.
        # luat din PRIMUL rând al paginii, nu din ultimul) avansează cu un
        # rând per cerere: codul tot se termină, dar după mii de cereri — la
        # test asta arată ca un blocaj, nu ca un eșec. Pragul îl transformă
        # într-un eșec clar, cu nume.
        if self._numarator[0] > _MAX_CERERI:
            raise AssertionError(
                f"paginare scăpată de sub control: peste {_MAX_CERERI} cereri "
                "pentru un set care are nevoie de câteva — cursorul nu avansează corect"
            )
        if self._esec_la is not None and self._numarator[0] == self._esec_la:
            raise RuntimeError("rețea căzută la mijlocul paginării")

        randuri = list(self._rows)
        for col, val in self._eq:
            randuri = [r for r in randuri if r.get(col) == val]
        for col, val in self._is:
            if val == "null":
                randuri = [r for r in randuri if r.get(col) is None]
        for col, val in self._gt:
            randuri = [r for r in randuri if r.get(col) is not None and r[col] > val]
        if self._in is not None:
            col, valori = self._in
            permise = set(valori)
            randuri = [r for r in randuri if r.get(col) in permise]
        if self._order is not None:
            randuri.sort(key=lambda r: r[self._order])
        # PLAFONUL IMPLICIT, nu doar cel cerut. PostgREST taie la „Max Rows"
        # CHIAR DACĂ apelantul nu cere niciun `.limit()` — exact proprietatea
        # care defineste toata clasa asta de defect.
        #
        # [REPARAT 2026-10-14, prin mutatie] Varianta anterioara aplica
        # `limit` DOAR cand era cerut explicit. Consecinta, descoperita
        # reintroducand defectul original in `get_distinct_experiments()`:
        # codul rupt primea toate cele 2500 de randuri si garda centrala
        # TRECEA. Era prins doar colateral, de testele care numara cererile.
        # Docstring-ul fisierului promitea tocmai ca un fals permisiv ar face
        # testele sa nu dovedeasca nimic — si fix aici nu se tinea de cuvant.
        taiere = _PLAFON_IMPLICIT if self._limit is None else min(self._limit, _PLAFON_IMPLICIT)
        randuri = randuri[:taiere]

        self._jurnal.append({
            "select": self._select, "eq": list(self._eq), "is_": list(self._is),
            "gt": list(self._gt), "in_": self._in, "order": self._order,
            "limit": self._limit, "returnate": len(randuri),
        })
        return type("R", (), {"data": randuri})()


class _FakeClient:
    """Mai multe tabele, fiecare cu propriile rânduri și propriul jurnal."""

    def __init__(self, tabele: dict[str, list[dict]], esec_la: int | None = None):
        self._tabele = tabele
        self.jurnale: dict[str, list[dict]] = {n: [] for n in tabele}
        self._esec_la = esec_la
        self._numarator = [0]

    def table(self, nume):
        self._tabele.setdefault(nume, [])
        self.jurnale.setdefault(nume, [])
        return _FakeQuery(self._tabele[nume], self.jurnale[nume],
                          self._esec_la, self._numarator)


def _shadow(i: int, *, grup: str = "treatment", etapa: str = "final",
            invalidat=None, rezultat: str = "H") -> dict:
    return {
        "id": i, "fixture_id": f"fx_{i:05d}", "league": "Premier League",
        "experiment_name": "xgboost_v1", "experiment_version": "run-1",
        "experiment_group": grup, "processing_stage": etapa,
        "invalidated_at": invalidat, "kickoff_date": "2026-08-20",
        "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2,
        "predicted_outcome": rezultat,
    }


def _istoric(i: int, *, neutru: bool = False) -> dict:
    calitate = "neutral" if neutru else "live"
    return {
        "fixture_id": f"fx_{i:05d}", "actual_result": "H",
        "prob_home_pred": 0.45, "prob_draw_pred": 0.30, "prob_away_pred": 0.25,
        "home_data_quality": calitate, "away_data_quality": calitate,
    }


# ════════════════════════════════════════════════════════════════════════════
# get_shadow_predictions — paginare
# ════════════════════════════════════════════════════════════════════════════

def test_aduce_toate_randurile_peste_plafonul_de_1000(monkeypatch):
    """GARDA CENTRALĂ. Fără paginare, o cerere e tăiată la 1000 și evaluarea
    rulează pe un subeșantion, nu pe populația reală."""
    randuri = [_shadow(i) for i in range(1, 2501)]
    client = _FakeClient({"shadow_predictions": randuri})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    iesire = st.get_shadow_predictions("xgboost_v1", "run-1")

    assert len(iesire) == 2500, (
        f"s-au adus {len(iesire)} din 2500 — paginarea nu funcționează"
    )
    assert len(client.jurnale["shadow_predictions"]) == 3, "1000 + 1000 + 500"


def test_cursorul_nu_repeta_si_nu_sare_randuri(monkeypatch):
    randuri = [_shadow(i) for i in range(1, 2501)]
    client = _FakeClient({"shadow_predictions": randuri})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    iduri = [r["id"] for r in st.get_shadow_predictions("xgboost_v1", "run-1")]

    assert len(iduri) == len(set(iduri)), "cursorul a repetat rânduri"
    assert iduri == sorted(iduri) == list(range(1, 2501))


def test_numar_de_randuri_exact_pe_plafon_nu_pierde_nimic(monkeypatch):
    """Cazul de graniță: exact 1000. O pagină plină înseamnă „mai pot fi" —
    codul TREBUIE să ceară încă una, care vine goală."""
    randuri = [_shadow(i) for i in range(1, 1001)]
    client = _FakeClient({"shadow_predictions": randuri})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    iesire = st.get_shadow_predictions("xgboost_v1", "run-1")

    assert len(iesire) == 1000
    assert len(client.jurnale["shadow_predictions"]) == 2, "pagina plină + una goală"


def test_ordonarea_e_pe_id_explicit(monkeypatch):
    """Paginarea keyset e nesănătoasă fără ORDER BY: fără ordine garantată,
    `id > cursor` poate sări sau repeta rânduri. Ordinea NU e cosmetică."""
    client = _FakeClient({"shadow_predictions": [_shadow(1)]})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    st.get_shadow_predictions("xgboost_v1", "run-1")

    assert client.jurnale["shadow_predictions"][0]["order"] == "id"


def test_o_singura_pagina_nu_cere_a_doua_degeaba(monkeypatch):
    client = _FakeClient({"shadow_predictions": [_shadow(i) for i in range(1, 51)]})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    assert len(st.get_shadow_predictions("xgboost_v1", "run-1")) == 50
    assert len(client.jurnale["shadow_predictions"]) == 1


def test_esecul_unei_pagini_intoarce_lista_goala_nu_parti(monkeypatch):
    """Un set PARȚIAL e exact defectul reparat aici. Zero rânduri produce
    `insufficient_data` — adică NICIUN verdict, starea corectă când nu știm."""
    randuri = [_shadow(i) for i in range(1, 2501)]
    client = _FakeClient({"shadow_predictions": randuri}, esec_la=2)
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    assert st.get_shadow_predictions("xgboost_v1", "run-1") == []


def test_supabase_indisponibil_intoarce_lista_goala(monkeypatch):
    monkeypatch.setattr(st.sb, "get_client", lambda: None)
    assert st.get_shadow_predictions("xgboost_v1") == []


# ════════════════════════════════════════════════════════════════════════════
# get_shadow_predictions — filtrele merg în CERERE, nu în Python
# ════════════════════════════════════════════════════════════════════════════

def test_grupul_si_etapa_merg_in_cerere(monkeypatch):
    """Fără ele în cerere, jumătate din capacitatea fiecărei pagini se consumă
    pe rânduri `control` pe care apelantul le aruncă oricum."""
    client = _FakeClient({"shadow_predictions": [_shadow(1)]})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    st.get_shadow_predictions("xgboost_v1", "run-1", processing_stage="final",
                              experiment_group="treatment")

    eq = client.jurnale["shadow_predictions"][0]["eq"]
    assert ("processing_stage", "final") in eq
    assert ("experiment_group", "treatment") in eq


def test_filtrul_de_grup_chiar_exclude_randurile_control(monkeypatch):
    randuri = ([_shadow(i, grup="treatment") for i in range(1, 11)]
               + [_shadow(i, grup="control") for i in range(11, 21)])
    client = _FakeClient({"shadow_predictions": randuri})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    iesire = st.get_shadow_predictions("xgboost_v1", "run-1",
                                       experiment_group="treatment")

    assert len(iesire) == 10
    assert {r["experiment_group"] for r in iesire} == {"treatment"}


def test_fara_grup_cerut_se_aduc_ambele(monkeypatch):
    """Parametru NOU, aditiv: apelanții existenți (audit, inspecție) nu-și
    schimbă comportamentul."""
    randuri = ([_shadow(i, grup="treatment") for i in range(1, 6)]
               + [_shadow(i, grup="control") for i in range(6, 11)])
    client = _FakeClient({"shadow_predictions": randuri})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    assert len(st.get_shadow_predictions("xgboost_v1", "run-1")) == 10


def test_filtrul_de_invalidare_supravietuieste_paginarii(monkeypatch):
    """Regresie ADR-064: o predicție făcută sub identitate greșită nu trebuie
    să reintre în evaluare pe drumul spre paginare."""
    randuri = ([_shadow(i) for i in range(1, 6)]
               + [_shadow(i, invalidat="2026-08-23T18:46:48Z") for i in range(6, 11)])
    client = _FakeClient({"shadow_predictions": randuri})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    iesire = st.get_shadow_predictions("xgboost_v1", "run-1")

    assert len(iesire) == 5
    assert ("invalidated_at", "null") in client.jurnale["shadow_predictions"][0]["is_"]


# ════════════════════════════════════════════════════════════════════════════
# Citirea din match_history — al doilea plafon, pe bucăți + paginat
# ════════════════════════════════════════════════════════════════════════════

def test_match_history_se_citeste_pe_bucati_sub_prag(monkeypatch):
    """Două limite deodată: plafonul de 1000 de rânduri ȘI lungimea URI-ului
    produs de `.in_()` cu mii de id-uri."""
    client = _FakeClient({"match_history": [_istoric(i) for i in range(1, 1301)]})
    fixture_ids = [f"fx_{i:05d}" for i in range(1, 1301)]

    gasite = st._read_match_history_for_fixtures(client, fixture_ids)

    assert len(gasite) == 1300
    jurnal = client.jurnale["match_history"]
    assert all(len(cerere["in_"][1]) <= st._IN_CHUNK_SIZE for cerere in jurnal), (
        "o bucată a depășit dimensiunea maximă"
    )


def test_match_history_pagineaza_in_interiorul_unei_bucati(monkeypatch):
    """Bucata e mai mică decât plafonul azi, dar dacă cineva o mărește peste
    1000, paginarea din interior trebuie să țină."""
    monkeypatch.setattr(st, "_IN_CHUNK_SIZE", 1500)
    client = _FakeClient({"match_history": [_istoric(i) for i in range(1, 1501)]})
    fixture_ids = [f"fx_{i:05d}" for i in range(1, 1501)]

    gasite = st._read_match_history_for_fixtures(client, fixture_ids)

    assert len(gasite) == 1500
    assert len(client.jurnale["match_history"]) == 2, "1000 + 500, o singură bucată"


def test_match_history_sare_randurile_fara_rezultat_sau_fara_baseline():
    randuri = [_istoric(1), _istoric(2), _istoric(3)]
    randuri[1]["actual_result"] = None
    randuri[2]["prob_home_pred"] = None
    client = _FakeClient({"match_history": randuri})

    gasite = st._read_match_history_for_fixtures(client, ["fx_00001", "fx_00002", "fx_00003"])

    assert set(gasite) == {"fx_00001"}


def test_eroarea_de_la_match_history_se_propaga():
    """Apelantul o tratează ca „nu se evaluează", niciodată ca „set complet
    mai mic"."""
    client = _FakeClient({"match_history": [_istoric(1)]}, esec_la=1)

    with pytest.raises(RuntimeError):
        st._read_match_history_for_fixtures(client, ["fx_00001"])


# ════════════════════════════════════════════════════════════════════════════
# Cap la cap — evaluate_experiment vede populația reală
# ════════════════════════════════════════════════════════════════════════════

def _pregateste_evaluare(monkeypatch, n_treatment: int, n_control: int = 0):
    shadow = [_shadow(i) for i in range(1, n_treatment + 1)]
    shadow += [_shadow(10_000 + i, grup="control") for i in range(1, n_control + 1)]
    istoric = [_istoric(i) for i in range(1, n_treatment + 1)]
    istoric += [_istoric(10_000 + i) for i in range(1, n_control + 1)]
    client = _FakeClient({"shadow_predictions": shadow, "match_history": istoric})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)
    monkeypatch.setattr(st, "_update_registry", lambda *a, **k: True)
    return client


def test_evaluarea_numara_toate_meciurile_peste_plafon(monkeypatch):
    """Cap la cap, exact scenariul de producție: 1200 de meciuri eligibile.
    Înainte de fix, cererea unică ar fi întors cel mult 1000."""
    _pregateste_evaluare(monkeypatch, n_treatment=1200)

    rezultat = st.evaluate_experiment("xgboost_v1", "run-1", min_matches=200)

    assert rezultat is not None
    assert rezultat["n_matches_evaluated"] == 1200


def test_randurile_control_nu_intra_in_numaratoare(monkeypatch):
    """Contrapondere: dacă filtrul de grup s-ar pierde, numărul ar sări la
    dublu și verdictul ar compara experimentul cu el însuși."""
    _pregateste_evaluare(monkeypatch, n_treatment=600, n_control=600)

    rezultat = st.evaluate_experiment("xgboost_v1", "run-1", min_matches=200)

    assert rezultat["n_matches_evaluated"] == 600


def test_evaluarea_ramane_insufficient_data_daca_citirea_esueaza(monkeypatch):
    """Fail-safe: mai bine niciun verdict decât unul pe date parțiale."""
    shadow = [_shadow(i) for i in range(1, 2501)]
    client = _FakeClient({"shadow_predictions": shadow}, esec_la=2)
    monkeypatch.setattr(st.sb, "get_client", lambda: client)
    monkeypatch.setattr(st, "_update_registry", lambda *a, **k: True)

    rezultat = st.evaluate_experiment("xgboost_v1", "run-1", min_matches=200)

    assert rezultat == {"status": "insufficient_data", "n_matches_evaluated": 0}


# ════════════════════════════════════════════════════════════════════════════
# D-10 — a PATRA instanță a aceluiași plafon, în `get_distinct_experiments()`
#
# Prima care NU era benignă. Celelalte trei pierdeau RÂNDURI dintr-un calcul;
# aceasta pierdea EXPERIMENTE ÎNTREGI dintr-o reevaluare — cele invizibile nu
# mai erau atinse niciodată, iar verdictele lor rămâneau înghețate.
#
# Măsurat pe producție ÎNAINTE de reparație (2026-10-14): `shadow_predictions`
# avea 6679 de rânduri și 7 experimente, dintre care în primele 1000 erau
# vizibile 2. Trei rânduri din `experiment_registry` erau înghețate de 32-34
# de zile — printre ele `blend_v1/8ac89c70`, marcat `candidate_for_promotion`
# deși e campionul ACTIV din 23 august. Sistemul afirma simultan că campionul
# activ e un candidat de promovat.
# ════════════════════════════════════════════════════════════════════════════


def _pred(i: int, nume: str, versiune: str) -> dict:
    return {"id": i, "experiment_name": nume, "experiment_version": versiune}


def _set_mare() -> list[dict]:
    """2500 de rânduri, 4 experimente — al patrulea apare DUPĂ plafon.

    Distribuția reproduce tiparul real: experimentele vechi au cele mai mici
    `id`-uri, cele noi cele mai mari. Experimentul `tarziu` începe la rândul
    2200, deci e invizibil pentru orice citire de o singură pagină.
    """
    randuri = []
    for i in range(1, 2501):
        if i <= 900:
            nume, ver = "blend_v1", "vechi"
        elif i <= 1500:
            nume, ver = "xgboost_v1", "mijloc"
        elif i <= 2199:
            nume, ver = "flashscore_team_dna", "v1"
        else:
            nume, ver = "xgboost_v1", "tarziu"
        randuri.append(_pred(i, nume, ver))
    return randuri


def test_vede_toate_experimentele_peste_plafonul_de_1000(monkeypatch):
    """GARDA CENTRALĂ D-10. Fără paginare s-ar vedea doar primele două."""
    client = _FakeClient({"shadow_predictions": _set_mare()})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    assert st.get_distinct_experiments() == [
        ("blend_v1", "vechi"),
        ("flashscore_team_dna", "v1"),
        ("xgboost_v1", "mijloc"),
        ("xgboost_v1", "tarziu"),
    ]


def test_experimentul_de_dupa_plafon_chiar_lipsea_fara_paginare(monkeypatch):
    """CONTRAPONDERE — dovedește că setul de test EXPUNE defectul.

    Fără ea, garda de mai sus ar putea trece pe un set în care toate
    experimentele încap oricum în prima pagină, adică fără să testeze nimic.
    Se reproduce aici citirea de o singură pagină, exact varianta veche."""
    randuri = _set_mare()
    o_pagina = sorted(randuri, key=lambda r: r["id"])[:st._PAGE_SIZE]
    vizibile = {(r["experiment_name"], r["experiment_version"]) for r in o_pagina}

    assert ("xgboost_v1", "tarziu") not in vizibile, (
        "setul de test nu expune defectul — experimentul tardiv e deja vizibil "
        "în prima pagină, deci garda ar trece și cu codul vechi")
    assert ("flashscore_team_dna", "v1") not in vizibile
    assert len(vizibile) == 2, f"ar trebui 2 vizibile fără paginare, sunt {len(vizibile)}"


def test_ordonarea_e_pe_id_explicit_altfel_rezultatul_e_nedeterminist(monkeypatch):
    """AGRAVANTUL din D-10, separat de trunchiere: fără `ORDER BY`, Postgres
    putea întoarce ALTE 1000 de rânduri de la o zi la alta, deci ce
    experimente erau vizibile se schimba singur."""
    client = _FakeClient({"shadow_predictions": _set_mare()})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)
    st.get_distinct_experiments()

    jurnal = client.jurnale["shadow_predictions"]
    assert jurnal, "nicio cerere făcută"
    for cerere in jurnal:
        assert cerere["order"] == "id", f"cerere fără ordonare pe id: {cerere}"
        assert cerere["limit"] == st._PAGE_SIZE


def test_cursorul_avanseaza_si_nu_repeta(monkeypatch):
    client = _FakeClient({"shadow_predictions": _set_mare()})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)
    st.get_distinct_experiments()

    jurnal = client.jurnale["shadow_predictions"]
    assert len(jurnal) == 3, f"2500 randuri / 1000 => 3 cereri, nu {len(jurnal)}"
    assert jurnal[0]["gt"] == []
    assert jurnal[1]["gt"] == [("id", 1000)]
    assert jurnal[2]["gt"] == [("id", 2000)]


def test_experimente_o_singura_pagina_nu_cere_a_doua_degeaba(monkeypatch):
    client = _FakeClient({"shadow_predictions": [_pred(i, "a", "v1") for i in range(1, 51)]})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    assert st.get_distinct_experiments() == [("a", "v1")]
    assert len(client.jurnale["shadow_predictions"]) == 1


def test_numar_exact_pe_plafon_nu_pierde_experimentul_urmator(monkeypatch):
    """Graniță: exact `_PAGE_SIZE` rânduri pentru primul experiment, iar al
    doilea începe fix la rândul următor. O pagină plină înseamnă „mai sunt",
    deci se cere încă una."""
    randuri = ([_pred(i, "a", "v1") for i in range(1, st._PAGE_SIZE + 1)]
               + [_pred(st._PAGE_SIZE + 1, "b", "v1")])
    client = _FakeClient({"shadow_predictions": randuri})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    assert st.get_distinct_experiments() == [("a", "v1"), ("b", "v1")]


def test_esecul_intoarce_lista_goala_nu_experimentele_adunate_pana_atunci(monkeypatch):
    """Un set PARȚIAL ar arăta identic cu defectul tocmai reparat: câteva
    experimente evaluate, restul tăcut neatinse, fără niciun semnal."""
    client = _FakeClient({"shadow_predictions": _set_mare()}, esec_la=2)
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    assert st.get_distinct_experiments() == []


def test_experimente_supabase_indisponibil_intoarce_lista_goala(monkeypatch):
    monkeypatch.setattr(st.sb, "get_client", lambda: None)
    assert st.get_distinct_experiments() == []


def test_se_citesc_doar_coloanele_necesare_nu_tot_randul(monkeypatch):
    """`select("*")` ar aduce `feature_metadata` pentru fiecare rând — de la
    ADR-073 acela poate avea ~1 KB. Pe 6679 de rânduri, degeaba."""
    client = _FakeClient({"shadow_predictions": _set_mare()})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)
    st.get_distinct_experiments()

    for cerere in client.jurnale["shadow_predictions"]:
        assert cerere["select"] == "id,experiment_name,experiment_version", cerere
        assert "*" not in cerere["select"]


def test_evaluate_all_chiar_itereaza_peste_toate_experimentele_gasite(monkeypatch):
    """Legătura până la capăt: `evaluate_all_active_experiments()` trebuie să
    evalueze fiecare experiment descoperit, nu doar pe cele din prima pagină.
    Fără acest test, paginarea ar putea fi corectă iar apelantul tot rupt."""
    client = _FakeClient({"shadow_predictions": _set_mare()})
    monkeypatch.setattr(st.sb, "get_client", lambda: client)

    evaluate = []
    monkeypatch.setattr(st, "evaluate_experiment",
                        lambda n, v, **k: evaluate.append((n, v)) or {"status": "monitoring"})

    rezultate = st.evaluate_all_active_experiments()

    assert sorted(evaluate) == [
        ("blend_v1", "vechi"), ("flashscore_team_dna", "v1"),
        ("xgboost_v1", "mijloc"), ("xgboost_v1", "tarziu"),
    ]
    assert len(rezultate) == 4
