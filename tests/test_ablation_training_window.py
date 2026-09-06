"""Gărzi pentru ablația de fereastră de antrenare (`scripts/ablation_training_window.py`).

Ce apără, în ordinea importanței:
  1. Scriptul e STRICT read-only. O ablație care scrie ar putea crea un
     Challenger, atinge `ml_model_status` sau înregistra o antrenare — adică
     ar schimba producția în timp ce pretinde că doar măsoară.
  2. Hiperparametrii nu divergă de cei din `ml_predictor`. Dacă motorul se
     schimbă și ablația rămâne pe valorile vechi, rezultatul ei nu mai spune
     nimic despre modelul real.
  3. Fereastra de antrenare exclude prin construcție orice meci din blocul de
     test sau de după el (zero scurgere temporală, North Star #7).

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ablation_training_window.py"


def _arbore() -> ast.Module:
    return ast.parse(SCRIPT.read_text(encoding="utf-8"))


# ════════════════════════════════════════════════════════════════════════
# 1. Read-only
# ════════════════════════════════════════════════════════════════════════

_METODE_DE_SCRIERE = {"insert", "upsert", "update", "delete", "rpc", "execute_sql"}


def _scrieri_pe_baza_de_date(arbore: ast.Module) -> list[str]:
    """Caută metode de scriere pe un lanț înrădăcinat în `.table(...)`.

    Deliberat pe AST, nu pe text: o căutare după `.insert(` ar raporta
    `sys.path.insert(0, ...)` — fals pozitiv real, prins într-un audit
    anterior pe alt raport read-only."""
    gasite: list[str] = []
    for nod in ast.walk(arbore):
        if not (isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute)):
            continue
        if nod.func.attr not in _METODE_DE_SCRIERE:
            continue
        radacina = nod.func.value
        while isinstance(radacina, ast.Call) and isinstance(radacina.func, ast.Attribute):
            if radacina.func.attr == "table":
                gasite.append(nod.func.attr)
                break
            radacina = radacina.func.value
    return gasite


def test_ablatia_nu_scrie_in_baza_de_date():
    assert _scrieri_pe_baza_de_date(_arbore()) == []


def test_ablatia_nu_scrie_pe_disc():
    """Nici artefacte, nici rapoarte — rezultatul se citește din stdout."""
    interzise = {"open", "write_text", "to_csv", "to_json", "savefig", "dump", "mkdir"}
    for nod in ast.walk(_arbore()):
        if isinstance(nod, ast.Call):
            nume = getattr(nod.func, "attr", None) or getattr(nod.func, "id", None)
            assert nume not in interzise, f"apel de scriere pe disc: {nume}"


def test_ablatia_nu_atinge_infrastructura_de_antrenare():
    """Nu creează Challenger, nu persistă artefacte, nu scrie status ML,
    nu înregistrează rulări — nici măcar prin import."""
    sursa = SCRIPT.read_text(encoding="utf-8")
    for interzis in ("challenger_manager", "model_artifact_storage", "save_ml_status",
                     "calibration_artifact_storage", "training_runner", "automation_runs",
                     "promotion_service", "run_training", "_record_training_run"):
        assert interzis not in sursa, f"ablația nu are voie să atingă {interzis}"


def test_ablatia_nu_apeleaza_train_ul_de_productie():
    """`MLPredictorEngine.train()` are efect secundar Supabase
    (`sb.save_ml_status`) — ar corupe statusul modelului cu cifrele unei
    ablații. Se folosesc XGBClassifier direct + funcții pure de metrici."""
    sursa = SCRIPT.read_text(encoding="utf-8")
    assert ".train()" not in sursa


# ════════════════════════════════════════════════════════════════════════
# 2. Hiperparametrii nu divergă de producție
# ════════════════════════════════════════════════════════════════════════

def _hiperparametri_din_ablatie() -> dict:
    for nod in ast.walk(_arbore()):
        if (isinstance(nod, ast.Assign)
                and any(getattr(t, "id", None) == "HIPERPARAMETRI" for t in nod.targets)):
            return {kw.arg: ast.literal_eval(kw.value) for kw in nod.value.keywords}
    raise AssertionError("HIPERPARAMETRI nu a fost găsit în ablație")


def _hiperparametri_din_motor() -> list[dict]:
    """Toate construcțiile `XGBClassifier(...)` din `ml_predictor.py` — și
    antrenarea finală, și fold-ul walk-forward."""
    sursa = (pathlib.Path(__file__).resolve().parent.parent / "ml_predictor.py").read_text(encoding="utf-8")
    gasite = []
    for nod in ast.walk(ast.parse(sursa)):
        if isinstance(nod, ast.Call) and getattr(nod.func, "id", None) == "XGBClassifier":
            gasite.append({kw.arg: ast.literal_eval(kw.value) for kw in nod.keywords})
    return gasite


def test_hiperparametrii_ablatiei_sunt_cei_din_productie():
    """GARDA CENTRALĂ. Dacă motorul își schimbă hiperparametrii și ablația
    rămâne pe cei vechi, cifrele ei nu mai descriu modelul real — iar asta nu
    s-ar vedea nicăieri, ar arăta doar ca un rezultat ușor diferit."""
    din_motor = _hiperparametri_din_motor()
    assert din_motor, "nu s-a găsit niciun XGBClassifier în ml_predictor.py"
    ai_ablatiei = _hiperparametri_din_ablatie()

    for parametrii in din_motor:
        assert parametrii == ai_ablatiei, (
            f"hiperparametrii au divergit — producție: {parametrii}, ablație: {ai_ablatiei}"
        )


def test_pragul_minim_de_antrenare_oglindeste_motorul():
    from ml_predictor import MIN_SAMPLES_TO_TRAIN

    for nod in ast.walk(_arbore()):
        if (isinstance(nod, ast.Assign)
                and any(getattr(t, "id", None) == "MIN_ANTRENARE" for t in nod.targets)):
            assert ast.literal_eval(nod.value) == MIN_SAMPLES_TO_TRAIN
            return
    raise AssertionError("MIN_ANTRENARE nu a fost găsit")


# ════════════════════════════════════════════════════════════════════════
# 3. Definiția sezonului
# ════════════════════════════════════════════════════════════════════════

def test_sezonul_incepe_la_1_iulie():
    from scripts.ablation_training_window import inceput_sezon

    assert inceput_sezon(date(2026, 9, 6)) == date(2026, 7, 1)
    assert inceput_sezon(date(2026, 7, 1)) == date(2026, 7, 1)


def test_sezonul_unui_meci_din_primavara_e_cel_de_anul_trecut():
    """Un meci din martie 2026 aparține sezonului început în iulie 2025 —
    altfel „sezonul curent" ar fi o fereastră de câteva săptămâni în ianuarie
    și ablația ar măsura altceva decât întrebarea pusă."""
    from scripts.ablation_training_window import inceput_sezon

    assert inceput_sezon(date(2026, 3, 15)) == date(2025, 7, 1)
    assert inceput_sezon(date(2026, 6, 30)) == date(2025, 7, 1)
    assert inceput_sezon(date(2026, 1, 1)) == date(2025, 7, 1)


def test_ferestrele_acopera_si_scurt_si_lung():
    """Contrapondere: o listă care ar rămâne doar cu ferestre lungi n-ar putea
    nici măcar în principiu să confirme ipoteza proprietarului produsului."""
    from scripts.ablation_training_window import FERESTRE

    zile = [z for _, z in FERESTRE if z is not None]
    assert None in [z for _, z in FERESTRE], "lipsește referința «tot istoricul»"
    assert min(zile) <= 92, "lipsește o fereastră scurtă, comparabilă cu un sezon început"
    assert max(zile) >= 1000, "lipsește o fereastră lungă"


# ════════════════════════════════════════════════════════════════════════
# 4. Zero scurgere temporală
# ════════════════════════════════════════════════════════════════════════

def test_toate_mastile_de_antrenare_sunt_strict_inaintea_blocului():
    """Fiecare mască de antrenare trebuie să conțină `df.index < start`.
    Fără ea, o fereastră ar putea include meciuri din blocul de test —
    exact scurgerea temporală interzisă de North Star #7."""
    sursa = SCRIPT.read_text(encoding="utf-8")
    atribuiri_masca = [
        linie.strip() for linie in sursa.splitlines()
        if linie.strip().startswith("masca =")
    ]
    assert atribuiri_masca, "nu s-a găsit nicio mască de antrenare"
    for linie in atribuiri_masca:
        assert "df.index < start" in linie, (
            f"mască fără garda temporală: {linie}"
        )


def test_evaluarea_foloseste_cele_trei_metrici_simultan():
    """North Star #2 — niciodată o singură metrică."""
    from scripts.ablation_training_window import evalueaza
    import inspect

    sursa = inspect.getsource(evalueaza)
    for cheie in ("acuratete", "log_loss", "brier"):
        assert cheie in sursa
