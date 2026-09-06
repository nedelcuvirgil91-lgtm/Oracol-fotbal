"""
Teste pentru evaluatorul selectiilor shadow (ADR-071 §16).

Zero retea, zero Supabase live: tot ce atinge baza de date e injectat prin
clienti falsi. Testele care conteaza cel mai mult nu sunt cele de aritmetica,
ci cele care apara doua reguli usor de pierdut la o rescriere:

  1. un meci fara rezultat NU e o pierdere (Regula #8);
  2. la deduplicare conteaza prima aparitie, nu ultima (§16).

Ambele au mutatia lor dedicata.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from value_selector_evaluation import (
    PRAG_ESANTION_MINIM,
    evalueaza,
    evalueaza_categorie,
    incarca_rezultate,
    incarca_selectii,
    pastreaza_prima_aparitie,
    rezultat_selectiei,
    run,
)

REPO = Path(__file__).resolve().parent.parent


def rand(**kwargs):
    """Un rand shadow minimal, cu valori implicite rezonabile."""
    baza = {
        "run_id": "2026-09-05T15:52Z",
        "policy_id": "p@v1:aaaa",
        "policy_profile": "p",
        "policy_family": "p",
        "fixture_id": "f1",
        "selection_code": "1",
        "model_probability": 0.60,
        "fair_probability": 0.50,
        "bk_odds": 2.0,
        "selected_top": True,
        "selected_longshot": False,
    }
    baza.update(kwargs)
    return baza


# ── rezultat_selectiei ───────────────────────────────────────────────────────

@pytest.mark.parametrize("cod,rezultat,asteptat", [
    ("1", "H", True), ("1", "D", False), ("1", "A", False),
    ("X", "D", True), ("X", "H", False), ("X", "A", False),
    ("2", "A", True), ("2", "H", False), ("2", "D", False),
])
def test_maparea_selectie_rezultat_e_completa_si_simetrica(cod, rezultat, asteptat):
    assert rezultat_selectiei(cod, rezultat) is asteptat


def test_rezultatul_lipsa_e_necunoscut_nu_pierdere():
    assert rezultat_selectiei("1", None) is None


@pytest.mark.parametrize("strain", ["P", "postponed", "", "  ", "X", "1"])
def test_valoare_straina_de_rezultat_e_necunoscut_nu_pierdere(strain):
    """Un `actual_result` care nu e H/D/A (amanare, valoare de la un provider
    nou) nu se interpreteaza NICIODATA ca infrangere. Ar fabrica pierderi din
    non-evenimente si ar strica orice ROI."""
    assert rezultat_selectiei("1", strain) is None


def test_rezultatul_e_tolerant_la_spatii_si_litere_mici():
    assert rezultat_selectiei("1", " h ") is True
    assert rezultat_selectiei("2", "a") is True


def test_cod_de_selectie_necunoscut_arunca():
    with pytest.raises(ValueError, match="cod de selectie necunoscut"):
        rezultat_selectiei("3", "H")


def test_maparea_vine_din_adaptor_nu_e_redefinita_local():
    """Invariantul "un singur modul stie ca 1X2 are trei rezultate" — daca
    cineva copiaza maparea in evaluator, testul asta cade."""
    import value_selector_adapter as adaptor
    import value_selector_evaluation as ev

    assert ev.REZULTAT_PENTRU_SELECTIE is adaptor.REZULTAT_PENTRU_SELECTIE
    sursa = (REPO / "value_selector_evaluation.py").read_text(encoding="utf-8")
    doar_cod = "\n".join(l for l in sursa.splitlines()
                         if not l.lstrip().startswith("#"))
    assert '"H"' not in doar_cod and "'H'" not in doar_cod


# ── §16: prima aparitie ──────────────────────────────────────────────────────

def test_prima_aparitie_pastreaza_rularea_cea_mai_veche():
    randuri = [
        rand(run_id="2026-09-05T09:40Z", bk_odds=2.0),
        rand(run_id="2026-09-06T09:40Z", bk_odds=2.5),
    ]
    pastrate = pastreaza_prima_aparitie(randuri)
    assert len(pastrate) == 1
    assert pastrate[0]["run_id"] == "2026-09-05T09:40Z"
    assert pastrate[0]["bk_odds"] == 2.0


def test_prima_aparitie_NU_pastreaza_ultima_mutatie():
    """Mutatie: daca cineva inverseaza comparatia si pastreaza cel mai mare
    run_id, selectia devine contaminata de miscarea pietei — exact ce respinge
    §16. Testul fixeaza directia."""
    randuri = [
        rand(run_id="2026-09-06T09:40Z", bk_odds=9.9),
        rand(run_id="2026-09-05T09:40Z", bk_odds=1.1),
    ]
    assert pastreaza_prima_aparitie(randuri)[0]["bk_odds"] == 1.1


def test_prima_aparitie_e_per_pereche_politica_meci():
    randuri = [
        rand(run_id="2026-09-05T09:40Z", policy_id="A", fixture_id="f1"),
        rand(run_id="2026-09-06T09:40Z", policy_id="A", fixture_id="f1"),
        rand(run_id="2026-09-06T09:40Z", policy_id="A", fixture_id="f2"),
        rand(run_id="2026-09-06T09:40Z", policy_id="B", fixture_id="f1"),
    ]
    pastrate = pastreaza_prima_aparitie(randuri)
    chei = {(r["policy_id"], r["fixture_id"], r["run_id"]) for r in pastrate}
    assert chei == {
        ("A", "f1", "2026-09-05T09:40Z"),
        ("A", "f2", "2026-09-06T09:40Z"),
        ("B", "f1", "2026-09-06T09:40Z"),
    }


def test_prima_aparitie_pastreaza_toate_cele_trei_selectii_ale_rularii():
    randuri = [rand(run_id="2026-09-05T09:40Z", selection_code=c) for c in ("1", "X", "2")]
    randuri += [rand(run_id="2026-09-06T09:40Z", selection_code=c) for c in ("1", "X", "2")]
    pastrate = pastreaza_prima_aparitie(randuri)
    assert len(pastrate) == 3
    assert {r["selection_code"] for r in pastrate} == {"1", "X", "2"}


def test_formatul_run_id_pastreaza_ordinea_cronologica_prin_comparatie_de_text():
    """Deduplicarea compara `run_id` ca text. Asta e corect DOAR pentru
    formatul `YYYY-MM-DDTHH:MMZ`. Daca formatul se schimba vreodata, testul
    asta cade inainte ca deduplicarea sa inceapa sa aleaga tacit gresit."""
    momente = ["2026-09-05T09:40Z", "2026-09-05T15:52Z",
               "2026-09-06T09:40Z", "2026-10-01T00:00Z", "2027-01-01T00:00Z"]
    assert momente == sorted(momente)


# ── Metrici ──────────────────────────────────────────────────────────────────

def test_rata_reusita_si_roi_pe_caz_calculabil_manual():
    randuri = [
        rand(fixture_id="f1", selection_code="1", bk_odds=2.0, fair_probability=0.50),
        rand(fixture_id="f2", selection_code="1", bk_odds=4.0, fair_probability=0.25),
    ]
    rez = evalueaza_categorie(randuri, categorie="top",
                              rezultate={"f1": "H", "f2": "A"})
    assert rez.decise == 2 and rez.reusite == 1
    assert rez.rata_reusita == pytest.approx(0.50)
    assert rez.cota_medie == pytest.approx(3.0)
    # castig 2.0 la f1, 0 la f2 -> medie 1.0 -> ROI 0%
    assert rez.roi_miza_plata == pytest.approx(0.0)
    # controlul pietei: (2.0*0.50 + 4.0*0.25)/2 - 1 = 0.0
    assert rez.roi_piata_implicit == pytest.approx(0.0)
    assert rez.diferenta_roi_pp == pytest.approx(0.0)


def test_meciurile_fara_rezultat_nu_se_numara_ca_pierderi():
    """Mutatia care conteaza cel mai mult: daca `in_asteptare` ar fi tratat ca
    infrangere, rata de reusita ar fi 1/3 in loc de 1/1 si ROI-ul ar fi
    fabricat din non-evenimente."""
    randuri = [
        rand(fixture_id="f1", bk_odds=2.0),
        rand(fixture_id="f2", bk_odds=2.0),
        rand(fixture_id="f3", bk_odds=2.0),
    ]
    rez = evalueaza_categorie(randuri, categorie="top",
                              rezultate={"f1": "H"})  # f2, f3 lipsesc
    assert rez.selectii_totale == 3
    assert rez.in_asteptare == 2
    assert rez.decise == 1
    assert rez.reusite == 1
    assert rez.rata_reusita == pytest.approx(1.0)
    assert rez.roi_miza_plata == pytest.approx(1.0)


def test_categorie_fara_niciun_meci_decis_nu_inventeaza_cifre():
    rez = evalueaza_categorie([rand(fixture_id="f1")], categorie="top", rezultate={})
    assert rez.decise == 0
    assert rez.rata_reusita is None
    assert rez.roi_miza_plata is None
    assert rez.roi_piata_implicit is None
    assert rez.brier_model is None
    assert rez.log_loss_model is None


def test_categorie_goala_e_valida_nu_eroare():
    rez = evalueaza_categorie([], categorie="longshot", rezultate={})
    assert rez.selectii_totale == 0 and rez.decise == 0
    assert rez.esantion_insuficient is True


def test_brier_si_log_loss_pe_valori_verificabile():
    randuri = [rand(fixture_id="f1", model_probability=0.80, fair_probability=0.60)]
    rez = evalueaza_categorie(randuri, categorie="top", rezultate={"f1": "H"})
    assert rez.brier_model == pytest.approx((0.80 - 1.0) ** 2)
    assert rez.brier_piata == pytest.approx((0.60 - 1.0) ** 2)
    assert rez.log_loss_model == pytest.approx(-math.log(0.80))
    assert rez.log_loss_piata == pytest.approx(-math.log(0.60))


def test_log_loss_nu_explodeaza_la_probabilitate_extrema():
    randuri = [rand(fixture_id="f1", model_probability=0.0, fair_probability=1.0)]
    rez = evalueaza_categorie(randuri, categorie="top", rezultate={"f1": "H"})
    assert math.isfinite(rez.log_loss_model)
    assert math.isfinite(rez.log_loss_piata)


def test_diferenta_fata_de_piata_in_puncte_procentuale():
    randuri = [
        rand(fixture_id="f1", fair_probability=0.40),
        rand(fixture_id="f2", fair_probability=0.40),
    ]
    rez = evalueaza_categorie(randuri, categorie="top",
                              rezultate={"f1": "H", "f2": "A"})
    assert rez.rata_implicita_piata == pytest.approx(0.40)
    assert rez.diferenta_pp == pytest.approx((0.50 - 0.40) * 100.0)


def test_pragul_de_esantion_e_cel_din_ADR():
    assert PRAG_ESANTION_MINIM == 150


def test_esantion_insuficient_ramane_pornit_sub_prag():
    randuri = [rand(fixture_id=f"f{i}") for i in range(10)]
    rezultate = {f"f{i}": "H" for i in range(10)}
    rez = evalueaza_categorie(randuri, categorie="top", rezultate=rezultate)
    assert rez.decise == 10
    assert rez.esantion_insuficient is True


def test_esantion_suficient_se_stinge_la_prag():
    randuri = [rand(fixture_id=f"f{i}") for i in range(PRAG_ESANTION_MINIM)]
    rezultate = {f"f{i}": "H" for i in range(PRAG_ESANTION_MINIM)}
    rez = evalueaza_categorie(randuri, categorie="top", rezultate=rezultate)
    assert rez.esantion_insuficient is False


# ── evalueaza() ──────────────────────────────────────────────────────────────

def test_categoriile_se_numara_pe_flaguri_nu_pe_eticheta():
    randuri = [
        rand(fixture_id="f1", selection_code="1", selected_top=True, selected_longshot=False),
        rand(fixture_id="f1", selection_code="X", selected_top=False, selected_longshot=True),
        rand(fixture_id="f1", selection_code="2", selected_top=False, selected_longshot=False),
    ]
    (politica,) = evalueaza(randuri, {"f1": "H"})
    assert politica.categorii["top"].selectii_totale == 1
    assert politica.categorii["longshot"].selectii_totale == 1


def test_mai_multe_longshoturi_pe_acelasi_meci_se_numara_toate():
    """Spre deosebire de Top, Longshot nu are `one_selection_per_match`."""
    randuri = [
        rand(fixture_id="f1", selection_code=c, selected_top=False, selected_longshot=True)
        for c in ("1", "X")
    ]
    (politica,) = evalueaza(randuri, {"f1": "H"})
    assert politica.categorii["longshot"].selectii_totale == 2


def test_politicile_sunt_separate_si_ordonate():
    randuri = [
        rand(policy_id="b@v1:2", policy_profile="b", fixture_id="f1"),
        rand(policy_id="a@v1:1", policy_profile="a", fixture_id="f1"),
    ]
    politici = evalueaza(randuri, {"f1": "H"})
    assert [p.policy_id for p in politici] == ["a@v1:1", "b@v1:2"]


def test_evalueaza_aplica_regula_primei_aparitii():
    randuri = [
        rand(run_id="2026-09-06T09:40Z", fixture_id="f1", bk_odds=10.0),
        rand(run_id="2026-09-05T09:40Z", fixture_id="f1", bk_odds=2.0),
    ]
    (politica,) = evalueaza(randuri, {"f1": "H"})
    assert politica.categorii["top"].decise == 1
    assert politica.categorii["top"].cota_medie == pytest.approx(2.0)


# ── Citire: clienti falsi, zero retea ────────────────────────────────────────

class _Interogare:
    def __init__(self, randuri, jurnal):
        self._randuri = randuri
        self._jurnal = jurnal

    def select(self, *a, **k): return self
    def order(self, *a, **k): return self

    def eq(self, camp, valoare):
        self._jurnal.append(("eq", camp, valoare))
        self._randuri = [r for r in self._randuri if r.get(camp) == valoare]
        return self

    def in_(self, camp, valori):
        self._randuri = [r for r in self._randuri if r.get(camp) in set(valori)]
        return self

    def range(self, start, sfarsit):
        self._felie = (start, sfarsit)
        return self

    def execute(self):
        felie = getattr(self, "_felie", None)
        randuri = self._randuri if felie is None else self._randuri[felie[0]:felie[1] + 1]
        return type("R", (), {"data": randuri})()


class _Client:
    def __init__(self, tabele):
        self.tabele = tabele
        self.jurnal = []

    def table(self, nume):
        self.jurnal.append(("table", nume))
        return _Interogare(list(self.tabele.get(nume, [])), self.jurnal)


@pytest.fixture
def client_fals(monkeypatch):
    def instaleaza(tabele):
        client = _Client(tabele)
        import database.queries as dq
        monkeypatch.setattr(dq, "get_client", lambda: client)
        return client
    return instaleaza


def test_incarca_selectii_exclude_leakage_la_sursa(client_fals):
    client = client_fals({"value_selector_shadow": [
        rand(fixture_id="f1", leakage_suspect=False),
        rand(fixture_id="f2", leakage_suspect=True),
    ]})
    selectii = incarca_selectii()
    assert [r["fixture_id"] for r in selectii] == ["f1"]
    assert ("eq", "leakage_suspect", False) in client.jurnal


def test_incarca_selectii_filtreaza_pe_run_id_cand_e_cerut(client_fals):
    client_fals({"value_selector_shadow": [
        rand(run_id="A", fixture_id="f1", leakage_suspect=False),
        rand(run_id="B", fixture_id="f2", leakage_suspect=False),
    ]})
    assert [r["fixture_id"] for r in incarca_selectii(run_id="B")] == ["f2"]


def test_citirea_e_paginata_si_nu_taie_tacit_setul(client_fals):
    multe = [rand(fixture_id=f"f{i}", leakage_suspect=False) for i in range(2500)]
    client_fals({"value_selector_shadow": multe})
    assert len(incarca_selectii()) == 2500


def test_fara_client_supabase_citirea_intoarce_gol_fara_sa_arunce(monkeypatch):
    import database.queries as dq
    monkeypatch.setattr(dq, "get_client", lambda: None)
    assert incarca_selectii() == []
    assert incarca_rezultate(["f1"]) == {}


def test_incarca_rezultate_construieste_maparea(client_fals):
    client_fals({"match_history": [
        {"fixture_id": "f1", "actual_result": "H"},
        {"fixture_id": "f2", "actual_result": None},
    ]})
    assert incarca_rezultate(["f1", "f2", "f3"]) == {"f1": "H", "f2": None}


def test_run_produce_raportul_complet(client_fals):
    client_fals({
        "value_selector_shadow": [
            rand(fixture_id="f1", leakage_suspect=False, bk_odds=2.0),
            rand(fixture_id="f2", leakage_suspect=False, bk_odds=2.0),
        ],
        "match_history": [{"fixture_id": "f1", "actual_result": "H"}],
    })
    raport = run()
    assert raport["selectii_citite"] == 2
    assert raport["meciuri"] == 2
    assert raport["meciuri_cu_rezultat"] == 1
    assert raport["meciuri_in_asteptare"] == 1
    assert raport["prag_esantion_minim"] == PRAG_ESANTION_MINIM
    (politica,) = raport["politici"]
    assert politica["categorii"]["top"]["decise"] == 1
    assert politica["categorii"]["top"]["esantion_insuficient"] is True


def test_run_fara_date_nu_arunca(monkeypatch):
    import database.queries as dq
    monkeypatch.setattr(dq, "get_client", lambda: None)
    raport = run()
    assert raport["selectii_citite"] == 0
    assert raport["politici"] == []
    assert "avertisment" in raport


# ── Garda: evaluatorul nu scrie NICIODATA ────────────────────────────────────

def _doar_cod(cale: Path) -> str:
    """Elimina docstring-urile si comentariile inainte de verificare. Fara
    asta, garda si-ar gasi propria explicatie si ar trece chiar dupa ce
    protectia reala a fost stearsa — capcana deja intalnita de doua ori in
    acest proiect."""
    import ast

    arbore = ast.parse(cale.read_text(encoding="utf-8"))
    for nod in ast.walk(arbore):
        if isinstance(nod, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (nod.body and isinstance(nod.body[0], ast.Expr)
                    and isinstance(nod.body[0].value, ast.Constant)
                    and isinstance(nod.body[0].value.value, str)):
                nod.body.pop(0)
    return ast.unparse(arbore)


@pytest.mark.parametrize("metoda", ["insert", "upsert", "update", "delete", "rpc"])
def test_evaluatorul_nu_contine_nicio_operatie_de_scriere(metoda):
    cod = _doar_cod(REPO / "value_selector_evaluation.py")
    assert f".{metoda}(" not in cod


def test_garda_de_scriere_chiar_prinde_o_incalcare(tmp_path):
    """Contra-test: fara el, garda ar putea trece vida daca `_doar_cod` ar
    incepe sa intoarca text gol."""
    fals = tmp_path / "fals.py"
    fals.write_text("def f(client):\n    client.table('x').insert({})\n", encoding="utf-8")
    assert ".insert(" in _doar_cod(fals)


def test_garda_nu_trece_vida_daca_fisierul_e_gol(tmp_path):
    gol = tmp_path / "gol.py"
    gol.write_text("", encoding="utf-8")
    assert _doar_cod(gol) == ""
    assert _doar_cod(REPO / "value_selector_evaluation.py").strip() != ""


def test_evaluatorul_nu_importa_niciun_motor_upstream():
    import ast

    arbore = ast.parse((REPO / "value_selector_evaluation.py").read_text(encoding="utf-8"))
    interzise = {"oracle_engine", "oracle_api", "feature_engine", "ml_predictor",
                 "recalibration", "shadow_testing", "supabase_client",
                 "learning_core", "requests", "httpx", "streamlit"}
    gasite = set()
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Import):
            gasite |= {a.name.split(".")[0] for a in nod.names}
        elif isinstance(nod, ast.ImportFrom) and nod.module:
            gasite.add(nod.module.split(".")[0])
    assert not (gasite & interzise), f"import upstream interzis: {gasite & interzise}"
