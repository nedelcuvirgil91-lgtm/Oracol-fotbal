"""[ADR-072] Gărzi pentru sursa baseline-ului din poarta de promovare.

Ce apără, în ordinea gravității:
  1. Cu flagul OPRIT, comportamentul e IDENTIC cu cel de azi — nu „aproape".
     Fără asta, un deployment înaintea migrării ar putea rupe scrierea în
     `experiment_registry` sau `challenger_evaluations`, tăcut.
  2. Sursa nu se amestecă NICIODATĂ: acoperire completă sau deloc (D2).
     Un verdict pe baseline-uri mixte nu e nici cel vechi, nici cel nou.
  3. Când sursa e `shadow_control`, probabilitățile chiar vin din rândul
     `control`, nu din coloanele înghețate — altfel ADR-ul ar fi doar o
     etichetă pusă peste vechiul comportament.
  4. `baseline_source` ajunge efectiv până în rândul persistat (D3).

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import pytest

import shadow_testing as st


# ════════════════════════════════════════════════════════════════════════
# 1. Rezolvarea sursei — funcție pură (D2)
# ════════════════════════════════════════════════════════════════════════

def test_acoperire_completa_da_shadow_control():
    ids = ["a", "b", "c"]
    control = {"a": {}, "b": {}, "c": {}}
    assert st.rezolva_sursa_baseline(ids, control) == st.BASELINE_SHADOW_CONTROL


def test_un_singur_meci_lipsa_cade_pe_baseline_inghetat():
    """GARDA CENTRALĂ D2. Un singur gol trebuie să răstoarne decizia pentru
    TOATE meciurile — altfel s-ar amesteca surse fără niciun semnal."""
    ids = ["a", "b", "c"]
    assert st.rezolva_sursa_baseline(ids, {"a": {}, "b": {}}) == st.BASELINE_MATCH_HISTORY


def test_zero_randuri_control_cade_pe_inghetat():
    """Cazul real `flashscore_team_dna/v1`: 711 treatment, 0 control."""
    assert st.rezolva_sursa_baseline(["x"] * 5, {}) == st.BASELINE_MATCH_HISTORY


def test_lista_goala_nu_pretinde_acoperire():
    """Contrapondere: `all([])` e True în Python, deci o implementare naivă ar
    raporta `shadow_control` pentru zero meciuri — o sursă „proaspătă" fără
    nicio dovadă că rândurile există."""
    assert st.rezolva_sursa_baseline([], {}) == st.BASELINE_MATCH_HISTORY
    assert st.rezolva_sursa_baseline([], {"a": {}}) == st.BASELINE_MATCH_HISTORY


def test_control_in_plus_nu_strica_acoperirea():
    """Rânduri control pentru meciuri neeligibile (fără rezultat încă) sunt
    normale — nu trebuie să conteze."""
    assert st.rezolva_sursa_baseline(
        ["a"], {"a": {}, "b": {}, "c": {}}) == st.BASELINE_SHADOW_CONTROL


def test_cele_doua_surse_au_valori_distincte_si_stabile():
    """Sunt scrise în baza de date; o redenumire ar face rândurile vechi
    necomparabile cu cele noi."""
    assert st.BASELINE_SHADOW_CONTROL == "shadow_control"
    assert st.BASELINE_MATCH_HISTORY == "match_history_frozen"


# ════════════════════════════════════════════════════════════════════════
# 2. Flagul — implicit OPRIT (D4, North Star #3)
# ════════════════════════════════════════════════════════════════════════

def test_flagul_e_oprit_cand_lipseste_din_config(monkeypatch):
    monkeypatch.setattr(st.sb, "load_config", lambda default: {})
    assert st.is_baseline_from_control_enabled() is False


def test_flagul_e_oprit_explicit_pe_false(monkeypatch):
    monkeypatch.setattr(
        st.sb, "load_config",
        lambda default: {"challenger_baseline_from_control_enabled": False})
    assert st.is_baseline_from_control_enabled() is False


def test_flagul_se_aprinde_doar_pe_true(monkeypatch):
    monkeypatch.setattr(
        st.sb, "load_config",
        lambda default: {"challenger_baseline_from_control_enabled": True})
    assert st.is_baseline_from_control_enabled() is True


def test_eroarea_de_citire_a_config_ului_lasa_flagul_OPRIT(monkeypatch):
    """Fail-safe către comportamentul de AZI. Un fail-open aici ar comuta
    baseline-ul din cauza unei erori de rețea — exact invers decât trebuie."""
    def explodeaza(default):
        raise RuntimeError("config indisponibil")
    monkeypatch.setattr(st.sb, "load_config", explodeaza)
    assert st.is_baseline_from_control_enabled() is False


# ════════════════════════════════════════════════════════════════════════
# 3. Citirea rândurilor control — paginare și filtre (D1)
# ════════════════════════════════════════════════════════════════════════

class _FalsQuery:
    """Client fals care CHIAR aplică filtrele, ordinea și limita.

    Unul care le-ar ignora ar face testele să treacă fără să dovedească
    nimic — exact eroarea prinsă în `test_shadow_prediction_invalidation.py`
    la paginarea din 6 septembrie."""

    def __init__(self, randuri, jurnal, max_cereri=40):
        self._toate = randuri
        self._jurnal = jurnal
        self._filtre: dict = {}
        self._in: list | None = None
        self._gt: str | None = None
        self._limit: int | None = None
        self._max = max_cereri

    def select(self, _coloane):
        self._jurnal.setdefault("coloane", _coloane)
        return self

    def in_(self, camp, valori):
        self._in = list(valori)
        self._jurnal.setdefault("in_camp", camp)
        return self

    def eq(self, camp, valoare):
        self._filtre[camp] = valoare
        return self

    def is_(self, camp, valoare):
        self._filtre[f"is:{camp}"] = valoare
        return self

    def gt(self, camp, valoare):
        assert camp == "fixture_id"
        self._gt = valoare
        return self

    def order(self, camp):
        assert camp == "fixture_id", "paginarea keyset cere ordonare pe cheie"
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        self._jurnal["cereri"] = self._jurnal.get("cereri", 0) + 1
        if self._jurnal["cereri"] > self._max:
            raise AssertionError("paginare care nu avansează — cursor greșit")
        self._jurnal["filtre"] = dict(self._filtre)
        r = [x for x in self._toate
             if all(x.get(k) == v for k, v in self._filtre.items() if not k.startswith("is:"))]
        if self._in is not None:
            r = [x for x in r if x["fixture_id"] in self._in]
        if self._gt is not None:
            r = [x for x in r if x["fixture_id"] > self._gt]
        r = sorted(r, key=lambda x: x["fixture_id"])
        if self._limit is not None:
            r = r[:self._limit]
        return type("Res", (), {"data": r})()


class _FalsClient:
    def __init__(self, randuri, jurnal):
        self._randuri = randuri
        self._jurnal = jurnal

    def table(self, nume):
        self._jurnal["tabela"] = nume
        return _FalsQuery(self._randuri, self._jurnal)


def _rand(fid, grup="control", stage="final", nume="exp", ver="v1", probs=(0.5, 0.3, 0.2)):
    return {"fixture_id": fid, "experiment_group": grup, "processing_stage": stage,
            "experiment_name": nume, "experiment_version": ver,
            "prob_home": probs[0], "prob_draw": probs[1], "prob_away": probs[2]}


def test_citirea_filtreaza_pe_control_si_pe_versiune():
    """Fără filtrul de versiune, baseline-ul unui Challenger ar putea fi luat
    din rândurile ALTUI Challenger pentru același meci."""
    randuri = [
        _rand("f1"),
        _rand("f2", grup="treatment"),                # alt grup
        _rand("f3", ver="v2"),                        # altă versiune
        _rand("f4", stage="intermediate"),            # altă etapă
        _rand("f5", nume="alt_experiment"),           # alt experiment
    ]
    jurnal: dict = {}
    gasite = st._read_control_baselines(
        _FalsClient(randuri, jurnal), ["f1", "f2", "f3", "f4", "f5"], "exp", "v1")
    assert set(gasite) == {"f1"}
    f = jurnal["filtre"]
    assert f["experiment_group"] == "control"
    assert f["experiment_version"] == "v1"
    assert f["experiment_name"] == "exp"
    assert f["processing_stage"] == "final"
    assert f["is:invalidated_at"] == "null"


def test_citirea_imparte_in_bucati_peste_limita_de_in():
    """Bucățile peste `.in_()` — mecanism DISTINCT de paginare."""
    randuri = [_rand(f"f{i:05d}") for i in range(2500)]
    jurnal: dict = {}
    gasite = st._read_control_baselines(
        _FalsClient(randuri, jurnal), [r["fixture_id"] for r in randuri], "exp", "v1")
    assert len(gasite) == 2500
    assert jurnal["cereri"] >= 5, "2500 de id-uri în bucăți de 500 = minim 5 cereri"


def test_citirea_pagineaza_cand_o_bucata_depaseste_o_pagina(monkeypatch):
    """A patra instanță a plafonului PostgREST din proiect (după
    `get_training_data`, `get_shadow_predictions` și
    `_read_match_history_for_fixtures`). Fără paginare, baseline-ul ar fi
    trunchiat tăcut, iar verdictul ar fi calculat pe un subset ales de bază.

    `_PAGE_SIZE` e micșorat DELIBERAT aici. Cu valorile de producție
    (`_IN_CHUNK_SIZE`=500 < `_PAGE_SIZE`=1000) o bucată încape mereu într-o
    pagină, deci paginarea nu se declanșează niciodată — o primă versiune a
    acestui test „trecea" numărând cererile de bucăți, nu de pagini, și lăsa
    ștergerea paginării complet nedetectată (prins prin mutație). Codul rămâne
    fiindcă protejează la o creștere viitoare a lui `_IN_CHUNK_SIZE`; testul
    trebuie să-l exercite în condiția în care chiar contează."""
    monkeypatch.setattr(st, "_PAGE_SIZE", 10)
    randuri = [_rand(f"f{i:05d}") for i in range(120)]
    jurnal: dict = {}
    gasite = st._read_control_baselines(
        _FalsClient(randuri, jurnal), [r["fixture_id"] for r in randuri], "exp", "v1")
    assert len(gasite) == 120, "citire trunchiată la o singură pagină"
    assert jurnal["cereri"] >= 12


def test_citirea_sare_randurile_cu_probabilitati_lipsa():
    """Regula #8: un rând incomplet e „necunoscut", nu zero — altfel ar intra
    în baseline ca o predicție de 0,0."""
    randuri = [_rand("f1"), {**_rand("f2"), "prob_draw": None}]
    gasite = st._read_control_baselines(_FalsClient(randuri, {}), ["f1", "f2"], "exp", "v1")
    assert set(gasite) == {"f1"}


# ════════════════════════════════════════════════════════════════════════
# 4. Contractul de deployment (D3/D4) — verificat pe SURSĂ, nu pe efect
# ════════════════════════════════════════════════════════════════════════

def _sursa(cale: str) -> str:
    """Doar liniile de cod: o gardă care caută text ar putea găsi propriul
    comentariu explicativ și ar trece chiar după ștergerea liniei reale —
    eroarea prinsă la garda `pipefail` din august."""
    import pathlib
    linii = pathlib.Path(cale).read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in linii if not l.strip().startswith("#"))


def test_baseline_source_intra_in_rezultat_doar_cu_flagul_pornit():
    """`_update_registry()` primește `**result` și ar EȘUA pe o coloană
    inexistentă. Cheia trebuie condiționată de flag, ca deployment-ul să fie
    sigur înaintea migrării."""
    cod = _sursa("shadow_testing.py")
    assert 'if baseline_din_control_pornit:\n        result["baseline_source"]' in cod


def test_scrierea_verdictului_omite_cheia_cand_e_necunoscuta():
    """Un `None` trimis explicit ar fi respins de PostgREST cât timp coloana
    lipsește, iar eșecul ar doborî TOT insert-ul, tăcut."""
    cod = _sursa("supabase_client.py")
    assert 'if baseline_source is not None:\n            payload["baseline_source"]' in cod


def test_verdictul_propaga_sursa_pana_la_persistare():
    cod = _sursa("learning_core/challenger_evaluation.py")
    assert 'baseline_source=result.get("baseline_source")' in cod


# ════════════════════════════════════════════════════════════════════════
# 5. End-to-end: baseline-ul CHIAR se schimbă (D1)
# ════════════════════════════════════════════════════════════════════════

_FIXTURI = ["m1", "m2", "m3"]


def _pregateste(monkeypatch, flag: bool, control_lipsa: int = 0):
    """Trei meciuri câștigate de gazdă. Baseline-ul înghețat prezice `A` la
    toate (acuratețe 0,0); cel proaspăt prezice `H` la toate (acuratețe 1,0).
    Contrastul e maxim tocmai ca schimbarea să nu poată trece neobservată.

    Challenger-ul nimerește 2 din 3 — DELIBERAT, nu 3 din 3: aterizează între
    cele două baseline-uri, deci verdictul lui își poate inversa semnul odată
    cu sursa. Cu 3 din 3 ar fi ieșit cel mai bun contra oricărei surse, iar
    testul n-ar fi putut arăta tocmai fenomenul din cauza căruia există ADR-ul."""
    tratament = [{"fixture_id": f, "prob_home": 0.5, "prob_draw": 0.3,
                  "prob_away": 0.2, "predicted_outcome": "H",
                  "kickoff_date": "2026-09-01", "processing_stage": "final",
                  "experiment_group": "treatment"} for f in _FIXTURI]
    tratament[-1].update(prob_home=0.2, prob_draw=0.6, prob_away=0.2,
                         predicted_outcome="D")
    istoric = {f: {"fixture_id": f, "actual_result": "H",
                   "prob_home_pred": 0.2, "prob_draw_pred": 0.3, "prob_away_pred": 0.5,
                   "home_data_quality": "live", "away_data_quality": "live"}
               for f in _FIXTURI}
    control = {f: {"fixture_id": f, "prob_home": 0.9, "prob_draw": 0.05, "prob_away": 0.05}
               for f in _FIXTURI[:len(_FIXTURI) - control_lipsa]}

    scris: dict = {}
    monkeypatch.setattr(st.sb, "get_client", lambda: object())
    monkeypatch.setattr(
        st.sb, "load_config",
        lambda default: {"challenger_baseline_from_control_enabled": flag})
    monkeypatch.setattr(st, "get_shadow_predictions", lambda *a, **k: tratament)
    monkeypatch.setattr(st, "_read_match_history_for_fixtures", lambda c, ids: istoric)
    monkeypatch.setattr(st, "_read_control_baselines", lambda c, ids, n, v: control)
    monkeypatch.setattr(st, "_update_registry",
                        lambda *a, **kw: scris.update(kw) or True)
    return scris


def test_cu_flagul_OPRIT_rezultatul_e_identic_cu_azi(monkeypatch):
    """GARDA #1: cerința 3 de activare din ADR — o rulare cu flagul oprit
    trebuie să se comporte exact ca înainte."""
    _pregateste(monkeypatch, flag=False)
    r = st.evaluate_experiment("exp", "v1", min_matches=1)
    assert r["accuracy_baseline"] == pytest.approx(0.0)
    assert "baseline_source" not in r, \
        "cu flagul oprit, cheia nu are voie să ajungă în `_update_registry`"


def test_cu_flagul_PORNIT_baseline_ul_vine_din_randul_control(monkeypatch):
    """GARDA CENTRALĂ D1. Fără ea, ADR-ul ar fi doar o etichetă nouă pusă
    peste exact același comportament."""
    _pregateste(monkeypatch, flag=True)
    r = st.evaluate_experiment("exp", "v1", min_matches=1)
    assert r["accuracy_baseline"] == pytest.approx(1.0)
    assert r["baseline_source"] == st.BASELINE_SHADOW_CONTROL


def test_acoperire_incompleta_pastreaza_baseline_ul_inghetat(monkeypatch):
    """D2 end-to-end: un singur meci fără `control` întoarce TOATE meciurile
    pe sursa veche — și o spune în rezultat, nu tăcut."""
    _pregateste(monkeypatch, flag=True, control_lipsa=1)
    r = st.evaluate_experiment("exp", "v1", min_matches=1)
    assert r["accuracy_baseline"] == pytest.approx(0.0)
    assert r["baseline_source"] == st.BASELINE_MATCH_HISTORY


def test_esecul_citirii_randurilor_control_cade_pe_comportamentul_de_azi(monkeypatch):
    """Fail-safe: o eroare de rețea nu are voie să producă un baseline parțial
    — ar da un verdict FALS, nu unul incomplet."""
    _pregateste(monkeypatch, flag=True)

    def explodeaza(*a, **k):
        raise RuntimeError("rețea picată")
    monkeypatch.setattr(st, "_read_control_baselines", explodeaza)
    r = st.evaluate_experiment("exp", "v1", min_matches=1)
    assert r["accuracy_baseline"] == pytest.approx(0.0)
    assert r["baseline_source"] == st.BASELINE_MATCH_HISTORY


def test_verdictul_se_poate_schimba_intre_surse(monkeypatch):
    """Motivul pentru care ADR-ul există: pe aceleași meciuri, deltele diferă.
    Aici, challenger-ul trece din «mult mai bun» în «mult mai slab»."""
    _pregateste(monkeypatch, flag=False)
    inghetat = st.evaluate_experiment("exp", "v1", min_matches=1)
    _pregateste(monkeypatch, flag=True)
    proaspat = st.evaluate_experiment("exp", "v1", min_matches=1)
    assert inghetat["delta_accuracy"] > 0 > proaspat["delta_accuracy"]
    assert inghetat["brier_baseline"] > proaspat["brier_baseline"]


def test_bucla_de_evaluare_alege_sursa_o_singura_data():
    """Decizia trebuie luată ÎNAINTE de buclă. Dacă s-ar recalcula per meci,
    D2 ar fi încălcat exact în modul pe care îl interzice."""
    cod = _sursa("shadow_testing.py")
    poz_rezolvare = cod.index("baseline_source = rezolva_sursa_baseline(")
    poz_bucla = cod.index("for shadow, mh in eligible:")
    assert poz_rezolvare < poz_bucla
    assert cod.count("rezolva_sursa_baseline(") == 2  # definiția + un singur apel
