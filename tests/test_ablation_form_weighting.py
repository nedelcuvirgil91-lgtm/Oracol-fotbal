"""Gărzi pentru ablația de ponderare a formei (`scripts/ablation_form_weighting.py`).

Ce apără:
  1. Read-only strict — o ablație care scrie ar putea schimba ponderi sau
     predicții în timp ce pretinde că doar măsoară.
  2. Varianta de REFERINȚĂ reproduce EXACT `feature_engine.compute_form_score()`
     — dacă referința ar diverge, toate deltele ar fi față de o fantomă.
  3. Variantele chiar fac ce spune numele lor (fereastră, ponderare, penalizare
     de dispersie) — verificat pe cazuri construite, inclusiv exemplul concret
     dat de proprietarul produsului.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

# Toleranța 1e-4 din teste NU e neglijență: `compute_form_score()` rotunjește
# la 4 zecimale, iar variantele fac la fel, ca referința să reproducă exact
# producția. O toleranță mai strânsă ar testa aritmetica float, nu formula.
from feature_engine import compute_form_score
from scripts.ablation_form_weighting import (
    construieste_variante, consistenta, egal, exponential, liniar,
)

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ablation_form_weighting.py"


# ════════════════════════════════════════════════════════════════════════
# 1. Read-only
# ════════════════════════════════════════════════════════════════════════

_METODE_DE_SCRIERE = {"insert", "upsert", "update", "delete", "rpc"}


def test_ablatia_nu_scrie_in_baza_de_date():
    """AST, nu text: o căutare după `.insert(` ar raporta `sys.path.insert`."""
    arbore = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    gasite = []
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
    assert gasite == []


def test_ablatia_nu_scrie_ponderi_sau_config():
    sursa = SCRIPT.read_text(encoding="utf-8")
    for interzis in ("save_weights", "save_config", "write_text", "to_csv",
                     "save_ml_status", "log_shadow_prediction"):
        assert interzis not in sursa, f"ablația nu are voie să scrie prin {interzis}"


# ════════════════════════════════════════════════════════════════════════
# 2. Referința reproduce producția
# ════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("rezultate", [
    ["W"], ["L"], ["D"],
    ["W", "W", "W", "W", "W"],
    ["L", "L", "L", "L", "L"],
    ["L", "L", "L", "W"],
    ["W", "L", "D", "W", "L"],
    ["D", "D", "D"],
])
def test_referinta_e_identica_cu_compute_form_score(rezultate):
    """GARDA CENTRALĂ. Dacă referința ar diverge de funcția de producție, toate
    deltele raportate ar fi față de o formulă care nu rulează nicăieri."""
    assert exponential(rezultate, 5) == pytest.approx(compute_form_score(rezultate), abs=1e-9)


def test_referinta_pe_mai_mult_de_5_taie_la_ultimele_5():
    """Producția primește deja cel mult `last_n_fixtures`=5 rânduri; garda
    asigură că restrângerea se face pe capătul RECENT, nu pe cel vechi."""
    lung = ["L", "L", "L", "W", "W", "W", "W", "W"]
    assert exponential(lung, 5) == pytest.approx(compute_form_score(["W"] * 5), abs=1e-9)


# ════════════════════════════════════════════════════════════════════════
# 3. Exemplul concret al proprietarului produsului
# ════════════════════════════════════════════════════════════════════════

def test_cazul_victorie_norocoasa_dupa_trei_infrangeri():
    """„Poate o echipă câștigă un meci norocos și apoi pierde 3 meciuri
    consecutive." Aici victoria e cea mai RECENTĂ după 3 înfrângeri — cazul
    în care ponderarea exponențială e cel mai contestabilă."""
    r = ["L", "L", "L", "W"]

    actual = exponential(r, 5)
    assert actual == pytest.approx(8 / 15, abs=1e-4)
    assert actual > 0.5, "formula actuală pune peste medie o echipă cu 3 înfrângeri din 4"

    assert egal(r, 3) == pytest.approx(1 / 3, abs=1e-4)
    assert egal(r, 5) == pytest.approx(0.25, abs=1e-4)
    assert egal(r, 3) < actual, "media pe ultimele 3 trebuie să corecteze exact acest caz"


def test_ordinea_inversa_nu_e_confundata():
    """Contrapondere: aceleași rezultate, victoria cea mai VECHE. Formula
    actuală trebuie să dea acum un scor MIC — altfel n-ar fi sensibilă la
    recență deloc, iar testul de mai sus n-ar dovedi nimic."""
    assert exponential(["W", "L", "L", "L"], 5) < 0.1
    assert exponential(["L", "L", "L", "W"], 5) > 0.5


# ════════════════════════════════════════════════════════════════════════
# 4. Variantele fac ce spun
# ════════════════════════════════════════════════════════════════════════

def test_fereastra_de_3_ignora_meciurile_mai_vechi():
    assert egal(["W", "W", "L", "L", "L"], 3) == pytest.approx(0.0, abs=1e-4)
    assert egal(["L", "L", "W", "W", "W"], 3) == pytest.approx(1.0, abs=1e-4)


def test_liniar_e_intre_egal_si_exponential():
    """Recență mai blândă decât exponențialul, mai fermă decât media simplă."""
    r = ["L", "L", "L", "L", "W"]
    assert egal(r, 5) < liniar(r, 5) < exponential(r, 5)


def test_consistenta_penalizeaza_dispersia_la_medie_egala():
    """GARDA pentru «constanța ar trebui premiată»: două șiruri cu ACEEAȘI
    medie primesc scoruri diferite."""
    stabil = ["D", "D", "D"]           # medie 0,4 · dispersie 0
    oscilant = ["W", "L", "D"]         # medie 0,466… · dispersie mare
    assert consistenta(stabil, 3, 0.5) == pytest.approx(0.4, abs=1e-4)
    assert consistenta(oscilant, 3, 0.5) < consistenta(stabil, 3, 0.5) + 0.05
    assert consistenta(oscilant, 3, 0.5) < egal(oscilant, 3)


def test_consistenta_cu_k_zero_e_media_simpla():
    """Contrapondere: fără penalizare, varianta trebuie să degenereze exact în
    media simplă — altfel penalizarea ar fi amestecată cu altceva."""
    for r in (["W", "L", "D"], ["W", "W", "W"], ["L", "D", "L"]):
        assert consistenta(r, 3, 0.0) == pytest.approx(egal(r, 3), abs=1e-4)


def test_toate_variantele_raman_in_intervalul_asteptat():
    """`calibrate_xg()` presupune form_score ∈ [0, 1]; o variantă care iese din
    interval ar produce un multiplicator în afara intervalului 0,88-1,12."""
    cazuri = [["W"], ["L"], ["W", "L"], ["W", "L", "D", "W", "L"], ["L"] * 5, ["W"] * 5]
    for nume, fn in construieste_variante(0.5).items():
        for r in cazuri:
            v = fn(r)
            assert 0.0 <= v <= 1.0, f"{nume} a produs {v} pentru {r}"


def test_lista_goala_da_zero_ca_in_productie():
    """Aceeași convenție ca `compute_form_score([])` — 0.0, nu 0.5. Apelantul
    decide ce înseamnă «fără istoric», nu funcția (Regula #8)."""
    for nume, fn in construieste_variante(0.5).items():
        assert fn([]) == 0.0, nume


def test_exista_si_referinta_si_alternative_pe_3():
    """Contrapondere: un set de variante fără referință, sau fără fereastra de 3
    cerută explicit, n-ar putea răspunde la întrebarea pusă."""
    nume = list(construieste_variante(0.5))
    assert any(n.startswith("REFERINȚĂ") for n in nume)
    assert sum(1 for n in nume if ", 3" in n or "ultimele 3" in n) >= 3
