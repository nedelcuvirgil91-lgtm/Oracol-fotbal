"""
Teste pentru ADR-086 — guvernarea artefactului ML servit.

Două decizii, testate separat fiindcă au naturi diferite:

  A. ETICHETA — `_record_training_run()` scrie familia care a CERUT
     antrenarea, nu o constantă. Închide un defect MĂSURAT: 37,4 din 89,9
     zile (41,6%) artefactul evaluat în shadow pe calea `xgboost_v1` nu era
     artefactul care servea ieșirea ML, fiindcă rulările cerute de `blend_v1`
     erau etichetate `xgboost_v1` și intrau în selecția cache-ului.

  B. GARDA FSM — un artefact cu Challenger `REJECTED` nu mai servește, gatat
     de `local_cache_fsm_guard_enabled`, implicit oprit.

Fără rețea: `supabase_client` e izolat prin monkeypatch în FIECARE test care
atinge calea, inclusiv citirea flagului. O citire de configurație nepatch-uită
ar trece într-un container fără credențiale și ar atinge rețeaua pe o mașină
care le are — vezi fixtura `_garda_fsm_oprita` din tests/test_local_model_cache.py.
"""
import ast
import inspect
from pathlib import Path

import numpy as np
import pytest

import ml_predictor
from learning_core import local_model_cache as lmc
from learning_core.algorithms.blend_v1 import BlendV1Algorithm
from learning_core.algorithms.xgboost_v1 import XGBoostV1Algorithm

RADACINA = Path(__file__).resolve().parent.parent


# ════════════════════════════════════════════════════════════════════════════
# A — eticheta familiei solicitante
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def inregistrare_capturata(monkeypatch):
    """Captează `algorithm_name` pasat lui `storage.save_training_run()` și
    `algorithm_family` pasat lui `compare_to_champion()`, fără nicio scriere
    reală (nici locală, nici remote)."""
    capturat: dict = {"storage": [], "comparatie": []}

    def fake_save(result, *, algorithm_name, algorithm_version, league_scope):
        capturat["storage"].append(algorithm_name)
        return Path("/dev/null")

    class _Comparatie:
        message = "fără campion activ"

    def fake_compare(*, algorithm_family, algorithm_version, league_scope,
                     new_training_run_id, new_metrics):
        capturat["comparatie"].append(algorithm_family)
        return _Comparatie()

    monkeypatch.setattr("learning_core.storage.save_training_run", fake_save)
    monkeypatch.setattr("learning_core.champion_comparison.compare_to_champion", fake_compare)
    return capturat


def test_implicitul_rămâne_xgboost_v1(inregistrare_capturata):
    """MARTOR POZITIV al neschimbării. `oracle_engine.retrain_ml_model()`
    apelează `_record_training_run` indirect, fără context de familie — nu
    trebuie să-și schimbe comportamentul cu nimic."""
    ml_predictor._record_training_run("trained", 100, {"accuracy": 0.5}, "mesaj")
    assert inregistrare_capturata["storage"] == ["xgboost_v1"]
    assert inregistrare_capturata["comparatie"] == ["xgboost_v1"]


def test_familia_solicitanta_ajunge_in_rand(inregistrare_capturata):
    ml_predictor._record_training_run("trained", 100, {"accuracy": 0.5}, "mesaj",
                                       algorithm_family="blend_v1")
    assert inregistrare_capturata["storage"] == ["blend_v1"]


def test_familia_solicitanta_ajunge_si_la_comparatia_cu_campionul(inregistrare_capturata):
    """ADR-086 §2.1 — o antrenare cerută de blend era comparată informativ cu
    campionul `xgboost_v1`, care nu a existat niciodată."""
    ml_predictor._record_training_run("trained", 100, {"accuracy": 0.5}, "mesaj",
                                       algorithm_family="blend_v1")
    assert inregistrare_capturata["comparatie"] == ["blend_v1"]


def test_fara_metrici_nu_se_compara_dar_eticheta_tot_se_scrie(inregistrare_capturata):
    ml_predictor._record_training_run("insufficient_data", 3, {}, "prea puține",
                                       algorithm_family="blend_v1")
    assert inregistrare_capturata["storage"] == ["blend_v1"]
    assert inregistrare_capturata["comparatie"] == []


def test_train_fara_requested_by_eticheteaza_xgboost(monkeypatch, inregistrare_capturata):
    """Calea `unavailable` — cea mai scurtă prin `train()`, suficientă ca să
    dovedească propagarea implicitului."""
    monkeypatch.setattr("supabase_client.is_available", lambda: False)
    rezultat = ml_predictor.MLPredictorEngine().train()
    assert rezultat.status == "unavailable"
    assert inregistrare_capturata["storage"] == ["xgboost_v1"]


def test_train_cu_requested_by_propaga_pe_calea_unavailable(monkeypatch, inregistrare_capturata):
    monkeypatch.setattr("supabase_client.is_available", lambda: False)
    ml_predictor.MLPredictorEngine().train(requested_by="blend_v1")
    assert inregistrare_capturata["storage"] == ["blend_v1"]


def test_train_cu_requested_by_propaga_pe_calea_insufficient_data(monkeypatch, inregistrare_capturata):
    monkeypatch.setattr("supabase_client.is_available", lambda: True)
    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "_fetch_training_dataframe", lambda self: None)
    rezultat = ml_predictor.MLPredictorEngine().train(requested_by="blend_v1")
    assert rezultat.status == "insufficient_data"
    assert inregistrare_capturata["storage"] == ["blend_v1"]


def test_train_cu_requested_by_propaga_pe_calea_error(monkeypatch, inregistrare_capturata):
    """Ramura `except` — a patra dintre cele patru puncte de apel. Dacă ar fi
    rămas nepropagată, o antrenare blend EȘUATĂ ar fi lăsat în urmă un rând
    etichetat greșit, adică exact urma de care ai nevoie la diagnoză."""
    monkeypatch.setattr("supabase_client.is_available", lambda: True)

    class _SetDeDateCareExplodeaza:
        """Trece de porțile `df is None` și `len(df) < MIN_SAMPLES_TO_TRAIN`,
        apoi explodează la primul acces din INTERIORUL blocului `try` — altfel
        excepția ar fi ridicată de `_fetch_training_dataframe()`, care e în
        AFARA lui, și n-ar atinge deloc ramura testată aici."""

        def __len__(self):
            return 40

        @property
        def columns(self):
            raise RuntimeError("bum")

    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "_fetch_training_dataframe",
                         lambda self: _SetDeDateCareExplodeaza())
    rezultat = ml_predictor.MLPredictorEngine().train(requested_by="blend_v1")
    assert rezultat.status == "error"
    assert inregistrare_capturata["storage"] == ["blend_v1"]


def test_toate_cele_patru_apeluri_din_train_paseaza_familia():
    """Gardă AST, nu textuală. Cele patru apeluri `_record_training_run` din
    `train()` trebuie să pasele TOATE `algorithm_family` — altfel un status
    rar (`unavailable`, `error`) ar scrie în continuare eticheta greșită, iar
    testele de ramură de mai sus acoperă doar ce exercită.

    AST fiindcă docstring-urile din `ml_predictor.py` conțin acum chiar
    șirurile căutate (`_record_training_run`, `algorithm_family`) — a noua
    instanță a clasei `pipefail`, unde o gardă textuală își găsește propria
    explicație."""
    sursa = (RADACINA / "ml_predictor.py").read_text(encoding="utf-8")
    arbore = ast.parse(sursa)

    train = next(
        n for n in ast.walk(arbore)
        if isinstance(n, ast.FunctionDef) and n.name == "train"
    )
    apeluri = [
        n for n in ast.walk(train)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_record_training_run"
    ]
    assert len(apeluri) == 4, f"așteptate 4 apeluri în train(), găsite {len(apeluri)}"
    for apel in apeluri:
        chei = {kw.arg for kw in apel.keywords}
        assert "algorithm_family" in chei, (
            f"apel `_record_training_run` la linia {apel.lineno} fără `algorithm_family`"
        )


@pytest.mark.parametrize("modul,clasa", [
    ("learning_core/algorithms/blend_v1.py", BlendV1Algorithm),
    ("learning_core/algorithms/xgboost_v1.py", XGBoostV1Algorithm),
])
def test_ambii_adaptori_paseaza_requested_by(modul, clasa):
    """Gardă AST pe AMBII adaptori, inclusiv pe `xgboost_v1` unde valoarea
    coincide cu implicitul. Deliberat fără excepție: o gardă cu o excepție
    pentru un adaptor ar lăsa următoarea familie adăugată să moștenească tăcut
    eticheta greșită."""
    arbore = ast.parse((RADACINA / modul).read_text(encoding="utf-8"))
    fit = next(
        n for n in ast.walk(arbore)
        if isinstance(n, ast.FunctionDef) and n.name == "fit"
    )
    apeluri_train = [
        n for n in ast.walk(fit)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "train"
    ]
    assert len(apeluri_train) == 1, f"{modul}: așteptat exact un apel .train() în fit()"
    chei = {kw.arg for kw in apeluri_train[0].keywords}
    assert "requested_by" in chei, f"{modul}: fit() nu pasează `requested_by`"
    assert clasa.name in ("xgboost_v1", "blend_v1")


def test_un_singur_rand_per_tentativa_de_antrenare(monkeypatch, inregistrare_capturata):
    """CONTRAPONDEREA din ADR-086 §6. Varianta respinsă pentru A („fiecare
    adaptor scrie propriul rând") ar fi produs DOUĂ rânduri pentru o singură
    tentativă reală — exact defectul reparat la auditul ADR-051/052. Dacă
    numărul devine 2, reparația se retrage."""
    monkeypatch.setattr("supabase_client.is_available", lambda: False)
    BlendV1Algorithm().fit()
    assert len(inregistrare_capturata["storage"]) == 1, (
        "o tentativă de antrenare a produs mai mult de un rând `training_runs`"
    )


def test_blend_fit_eticheteaza_blend_cap_coada(monkeypatch, inregistrare_capturata):
    """Testul care leagă cele două capete: adaptorul blend → rândul scris.
    Testele de cablare care verifică doar capetele, nu firul dintre ele, au
    lăsat deja o mutație să treacă (M5, garda etapelor critice `night_sync`)."""
    monkeypatch.setattr("supabase_client.is_available", lambda: False)
    BlendV1Algorithm().fit()
    assert inregistrare_capturata["storage"] == ["blend_v1"]


def test_xgboost_fit_eticheteaza_xgboost_cap_coada(monkeypatch, inregistrare_capturata):
    monkeypatch.setattr("supabase_client.is_available", lambda: False)
    XGBoostV1Algorithm().fit()
    assert inregistrare_capturata["storage"] == ["xgboost_v1"]


# ════════════════════════════════════════════════════════════════════════════
# B — garda de stare FSM pe Local Model Cache
# ════════════════════════════════════════════════════════════════════════════

def _rulare(training_run_id="run-1"):
    return {
        "training_run_id": training_run_id, "status": "trained",
        "algorithm_version": "1", "samples_used": 5000,
        "walk_forward_metrics": {"accuracy": 0.51, "log_loss": 1.01, "brier_score": 0.61},
        "created_at": "2026-08-01T12:00:00Z",
    }


class _ModelFals:
    def predict_proba(self, X):
        return np.array([[0.4, 0.3, 0.3]])


@pytest.fixture
def cache_cu_un_candidat(monkeypatch):
    """Un singur candidat valid, plus contoare pe cele două apeluri care
    costă: citirea flagului și descărcarea artefactului."""
    contoare = {"flag": 0, "descarcari": [], "interogari_fsm": []}

    def fake_load_config(default):
        contoare["flag"] += 1
        return dict(default)

    def fake_load_artifact(tid):
        contoare["descarcari"].append(tid)
        return _ModelFals()

    monkeypatch.setattr("supabase_client.list_recent_training_runs",
                         lambda family, scope, limit=10: [_rulare()])
    monkeypatch.setattr("supabase_client.load_config", fake_load_config)
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", fake_load_artifact)
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact",
                         lambda tid: None)
    monkeypatch.setattr("supabase_client.get_challenger",
                         lambda tid: contoare["interogari_fsm"].append(tid) or None)
    return contoare


def _activeaza_garda(monkeypatch):
    monkeypatch.setattr("supabase_client.load_config",
                         lambda default: {lmc._FLAG_GARDA_FSM: True})


def test_implicit_garda_oprita_si_nu_se_interogheaza_fsm(cache_cu_un_candidat):
    """North Star #3 — flagul absent din config înseamnă oprit, iar oprit
    înseamnă ZERO interogări `challengers`, nu „interoghează și ignoră"."""
    rezultat = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert rezultat is not None
    assert cache_cu_un_candidat["interogari_fsm"] == []


def test_flagul_se_citeste_o_singura_data_per_apel(monkeypatch):
    """Zece candidați, o singură citire de configurație."""
    contoare = {"flag": 0}

    def fake_load_config(default):
        contoare["flag"] += 1
        return dict(default)

    monkeypatch.setattr("supabase_client.list_recent_training_runs",
                         lambda family, scope, limit=10: [_rulare(f"run-{i}") for i in range(10)])
    monkeypatch.setattr("supabase_client.load_config", fake_load_config)
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact", lambda tid: None)
    lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert contoare["flag"] == 1


def test_artefact_respins_nu_serveste(monkeypatch, cache_cu_un_candidat):
    _activeaza_garda(monkeypatch)
    monkeypatch.setattr("supabase_client.get_challenger",
                         lambda tid: {"state": "REJECTED", "rejection_reason": "expired"})
    assert lmc.load_latest_trained_model_or_none("xgboost_v1", "all") is None


def test_artefactul_respins_NU_e_descarcat(monkeypatch, cache_cu_un_candidat):
    """Ordinea, măsurată prin efect: garda vine înaintea descărcării, deci
    artefactul respins nu e adus din Storage ca să fie apoi aruncat."""
    _activeaza_garda(monkeypatch)
    monkeypatch.setattr("supabase_client.get_challenger", lambda tid: {"state": "REJECTED"})
    lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert cache_cu_un_candidat["descarcari"] == []


def test_garda_fsm_precede_descarcarea_IN_COD(monkeypatch):
    """Gardă structurală pe ORDINEA din sursă, nu doar pe efect. Lecția de la
    `live_sync`: un test care verifică doar numărătoarea trece și după ce
    ordinea a fost inversată, iar tocmai ordinea e proprietatea care contează.
    AST, nu text."""
    sursa = inspect.getsource(lmc.load_latest_trained_model_or_none)
    arbore = ast.parse(sursa.lstrip())
    poz_garda = poz_descarcare = None
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Call) and isinstance(nod.func, ast.Name) \
                and nod.func.id == "_artefact_descalificat_de_fsm":
            poz_garda = nod.lineno
        if isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute) \
                and nod.func.attr == "load_model_artifact":
            poz_descarcare = nod.lineno
    assert poz_garda is not None, "garda FSM lipsește din funcție"
    assert poz_descarcare is not None, "apelul de descărcare lipsește din funcție"
    assert poz_garda < poz_descarcare, (
        "garda FSM trebuie să precedă `load_model_artifact` — altfel se descarcă "
        "un artefact respins doar ca să fie aruncat"
    )


def test_campionul_PROMOTED_SERVESTE(monkeypatch, cache_cu_un_candidat):
    """🔴 Testul cel mai important al lui B, și dovada capcanei din ADR-086
    §4.0. `challenger_manager.TERMINAL_STATES` e `{"PROMOTED", "REJECTED"}`.
    Dacă garda ar fi fost scrisă pe constanta aceea, ar fi OPRIT de la servire
    exact campionul — inversul scopului."""
    _activeaza_garda(monkeypatch)
    monkeypatch.setattr("supabase_client.get_challenger", lambda tid: {"state": "PROMOTED"})
    rezultat = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert rezultat is not None, "un artefact PROMOTED (campionul) trebuie să servească"


def test_TERMINAL_STATES_nu_apare_in_modul():
    """Gardă permanentă contra reintroducerii constantei greșite. Un AST pe
    numele folosite, nu `grep` — comentariul din modul explică chiar de ce NU
    se folosește `TERMINAL_STATES`, deci ar conține șirul căutat."""
    arbore = ast.parse((RADACINA / "learning_core/local_model_cache.py").read_text(encoding="utf-8"))
    nume = {n.id for n in ast.walk(arbore) if isinstance(n, ast.Name)}
    nume |= {n.attr for n in ast.walk(arbore) if isinstance(n, ast.Attribute)}
    assert "TERMINAL_STATES" not in nume, (
        "`TERMINAL_STATES` include PROMOTED — folosirea lui aici ar opri campionul "
        "de la servire (ADR-086 §4.0)"
    )


@pytest.mark.parametrize("stare", ["CREATED", "WAITING", "EVALUATING", "SUCCEEDED", "PROMOTED"])
def test_nicio_stare_neterminala_nu_descalifica(monkeypatch, cache_cu_un_candidat, stare):
    _activeaza_garda(monkeypatch)
    monkeypatch.setattr("supabase_client.get_challenger", lambda tid: {"state": stare})
    assert lmc.load_latest_trained_model_or_none("xgboost_v1", "all") is not None


def test_absenta_challengerului_NU_descalifica(monkeypatch, cache_cu_un_candidat):
    """ADR-086 §5.1 — regula e negativă („un respins nu servește"), niciodată
    pozitivă („doar un Challenger servește"). Un prag pozitiv ar opri ML-ul
    azi și ar contrazice ADR-051."""
    _activeaza_garda(monkeypatch)
    monkeypatch.setattr("supabase_client.get_challenger", lambda tid: None)
    assert lmc.load_latest_trained_model_or_none("xgboost_v1", "all") is not None


def test_eroare_la_citirea_starii_NU_descalifica(monkeypatch, cache_cu_un_candidat):
    """Regula #8 — o stare necunoscută rămâne necunoscută, nu se aproximează
    la „respins"."""
    _activeaza_garda(monkeypatch)

    def _explodeaza(tid):
        raise RuntimeError("Supabase picat")

    monkeypatch.setattr("supabase_client.get_challenger", _explodeaza)
    assert lmc.load_latest_trained_model_or_none("xgboost_v1", "all") is not None


def test_eroare_la_citirea_flagului_lasa_garda_OPRITA(monkeypatch):
    """Fail-OPEN, și direcția e argumentată în docstring-ul funcției: un
    fail-closed ar face ca un hopa de configurație să oprească ML-ul complet."""
    def _explodeaza(default):
        raise RuntimeError("config indisponibil")

    monkeypatch.setattr("supabase_client.load_config", _explodeaza)
    assert lmc.is_fsm_guard_enabled() is False


def test_cade_pe_urmatorul_candidat_cand_primul_e_respins(monkeypatch):
    """Comportamentul compus: garda nu declară cache-ul indisponibil, ci trece
    la candidatul următor — exact tiparul deja existent pentru artefactele
    lipsă."""
    stari = {"run-nou": {"state": "REJECTED"}, "run-vechi": {"state": "SUCCEEDED"}}
    monkeypatch.setattr("supabase_client.list_recent_training_runs",
                         lambda family, scope, limit=10: [_rulare("run-nou"), _rulare("run-vechi")])
    monkeypatch.setattr("supabase_client.load_config", lambda default: {lmc._FLAG_GARDA_FSM: True})
    monkeypatch.setattr("supabase_client.get_challenger", lambda tid: stari.get(tid))
    monkeypatch.setattr("learning_core.model_artifact_storage.load_model_artifact",
                         lambda tid: _ModelFals())
    monkeypatch.setattr("learning_core.calibration_artifact_storage.load_calibration_artifact",
                         lambda tid: None)
    rezultat = lmc.load_latest_trained_model_or_none("xgboost_v1", "all")
    assert rezultat is not None
    assert rezultat.training_run_id == "run-vechi"


def test_flagul_nu_e_pornit_implicit_in_cod():
    """North Star #3, verificat pe sursă: implicitul pasat lui `load_config`
    trebuie să fie `False`."""
    sursa = inspect.getsource(lmc.is_fsm_guard_enabled)
    arbore = ast.parse(sursa.lstrip())
    constante = [n.value for n in ast.walk(arbore) if isinstance(n, ast.Constant)
                 and isinstance(n.value, bool)]
    assert constante, "niciun implicit boolean găsit în is_fsm_guard_enabled()"
    assert all(c is False for c in constante), (
        "is_fsm_guard_enabled() nu are voie să folosească `True` ca implicit"
    )
