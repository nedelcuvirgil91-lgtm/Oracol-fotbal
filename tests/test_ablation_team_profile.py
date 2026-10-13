"""Gărzi pentru ablația Team Profile (`scripts/ablation_team_profile.py`).

Ce apără, în ordinea gravității:
  1. Read-only strict.
  2. ZERO scurgere temporală — meciul curent intră în istoric DUPĂ ce a fost
     evaluat, nu înainte. O inversare ar lăsa echipa să se „vadă" pe sine.
  3. Semnalul e calculat ca în producție: SUME ALINIATE, nu media rapoartelor.
  4. Garda de plauzibilitate a brațului de referință există — fără ea, o
     eroare de indexare a produs odată 0,3054 acuratețe și un tabel care
     arăta normal.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from scripts.ablation_team_profile import (
    FEREASTRA, _contracta, construieste_variante, eficienta_finalizare,
)

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "ablation_team_profile.py"


def _doar_cod(cale: pathlib.Path) -> str:
    """Elimină comentariile înainte de orice verificare pe text. Fără asta, o
    gardă își poate găsi propria explicație din comentariu și trece chiar după
    ce linia reală a fost ștearsă — eroare prinsă deja la garda `pipefail`."""
    linii = cale.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in linii if not l.strip().startswith("#"))


# ════════════════════════════════════════════════════════════════════════
# 1. Read-only
# ════════════════════════════════════════════════════════════════════════

def test_ablatia_nu_scrie_in_baza_de_date():
    """AST, nu text: o căutare după `.insert(` ar raporta `sys.path.insert`."""
    arbore = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    gasite = []
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Call) and isinstance(nod.func, ast.Attribute):
            if nod.func.attr in {"insert", "upsert", "update", "delete", "rpc", "execute"}:
                radacina = nod.func.value
                while isinstance(radacina, ast.Call) and isinstance(radacina.func, ast.Attribute):
                    if radacina.func.attr == "table":
                        gasite.append(nod.func.attr)
                        break
                    radacina = radacina.func.value
    assert gasite == []


def test_ablatia_nu_atinge_productia():
    sursa = _doar_cod(SCRIPT)
    for interzis in ("save_weights", "save_config", "write_text", "to_csv",
                     "promote_experiment", "log_shadow_prediction", "upsert_match"):
        assert interzis not in sursa, f"ablația nu are voie să cheme {interzis}"


# ════════════════════════════════════════════════════════════════════════
# 2. Zero scurgere temporală — garda structurală
# ════════════════════════════════════════════════════════════════════════

def test_meciul_curent_intra_in_istoric_DUPA_evaluare():
    """GARDA CENTRALĂ. Dacă adăugarea în istoric ar preceda evaluarea, fiecare
    echipă și-ar include propriul meci în fereastră — iar `goals_per_xg` ar
    conține rezultatul pe care tocmai încearcă să-l prezică. Ablația ar ieși
    spectaculos de bună și complet falsă.

    Se verifică ORDINEA în sursă, nu doar efectul: o rescriere care păstrează
    rezultatele dar mută adăugarea mai sus ar trece orice test de valori."""
    cod = _doar_cod(SCRIPT)
    poz_evaluare = cod.index("per_meci[nume].append(")
    poz_adaugare = cod.index('istoric[echipa].append(')
    assert poz_evaluare < poz_adaugare, \
        "meciul curent se adaugă în istoric ÎNAINTE de evaluare — scurgere"


def test_fereastra_e_cea_din_productie():
    from database.queries import TEAM_PROFILE_WINDOW
    assert FEREASTRA == TEAM_PROFILE_WINDOW == 5


def test_evaluarea_se_face_ZI_CU_ZI_nu_meci_cu_meci():
    """`count_matches_with_sufficient_history()` definește „anterior" STRICT pe
    zi calendaristică: meciurile din aceeași zi nu se numără unele pentru
    altele. Ablația trebuie să respecte aceeași semantică, altfel ar măsura
    altă populație decât cea pe care o raportează contorul din aplicație.

    ONESTITATE despre impact: în datele de azi fixul nu schimbă niciun rezultat
    — o echipă nu joacă de două ori în aceeași zi, deci scurgerea nu se poate
    manifesta. Garda apără o corectitudine de principiu și determinismul
    ordinii în interiorul unei zile, pe care `kickoff_date` singur nu o
    stabilește. Nu e un bug reparat; e o diferență de semantică închisă.

    Se verifică STRUCTURA — două bucle separate peste meciurile zilei — nu
    valorile, fiindcă valorile nu pot distinge cele două variante azi."""
    cod = _doar_cod(SCRIPT)
    assert "pe_zi" in cod, "lipsește gruparea pe zile"
    assert "for zi in sorted(pe_zi):" in cod
    corp = cod.split("for zi in sorted(pe_zi):")[1]
    poz_evaluare = corp.index("per_meci[nume].append(")
    poz_adaugare = corp.index("istoric[echipa].append(")
    assert poz_evaluare < poz_adaugare, \
        "istoricul zilei se actualizează înainte de a evalua toată ziua"
    assert corp.count("for r in meciurile_zilei:") == 2, \
        "evaluarea și actualizarea istoricului trebuie să fie bucle SEPARATE"


def test_contorul_aplicatiei_si_al_ablatiei_se_reconciliaza():
    """Ablația raportează mai puține meciuri decât bara din aplicație, și
    diferența trebuie să fie EXPLICITĂ, nu tăcută: aplicația numără doar
    „ambele echipe au ≥5 meciuri anterioare cu xG", ablația cere în plus
    ratinguri stocate și `data_quality != neutral`.

    Garda cere ca scriptul să tipărească ambele cifre și suma lor — altfel o
    diferență viitoare (301 vs 250, să zicem) ar trece drept normală."""
    cod = _doar_cod(SCRIPT)
    assert "pierdute_filtre" in cod
    assert "evaluabile + pierdute_filtre" in cod, \
        "scriptul trebuie să arate cifra pe care o raportează aplicația"


# ════════════════════════════════════════════════════════════════════════
# 3. Semnalul — sume aliniate, ca în producție
# ════════════════════════════════════════════════════════════════════════

def _m(g, xg, sot=3):
    return {"goluri": g, "xg": xg, "sot": sot}


def test_goals_per_xg_e_raport_de_SUME_nu_medie_de_rapoarte():
    """Diferența nu e cosmetică. Pe șirul de mai jos, raportul sumelor e
    6/6 = 1,0; media rapoartelor ar fi (3/1 + 1/2 + 1/1 + 0/1 + 1/1)/5 = 1,1 —
    trasă în sus de meciul cu xG mic. Producția folosește sumele."""
    ist = [_m(3, 1.0), _m(1, 2.0), _m(1, 1.0), _m(0, 1.0), _m(1, 1.0)]
    s = eficienta_finalizare(ist)
    assert s["goals_per_xg"] == pytest.approx(6.0 / 6.0)


def test_sub_fereastra_intoarce_None():
    """Regula #8: fără fereastră completă, starea e necunoscută — niciodată
    aproximată cu 1,0, care ar însemna «finalizare perfect medie»."""
    for n in range(FEREASTRA):
        assert eficienta_finalizare([_m(1, 1.0)] * n) is None


def test_foloseste_doar_ultimele_cinci():
    vechi = [_m(5, 1.0)] * 10          # eficiență absurdă, dar veche
    recent = [_m(1, 1.0)] * 5
    assert eficienta_finalizare(vechi + recent)["goals_per_xg"] == pytest.approx(1.0)


def test_perechea_se_ia_doar_cand_ambele_valori_exista():
    """Un meci cu goluri dar fără xG nu are voie să-și adauge golurile la
    numărător fără numitor — ar umfla artificial eficiența."""
    ist = [_m(2, None), _m(1, 1.0), _m(1, 1.0), _m(1, 1.0), _m(1, 1.0)]
    assert eficienta_finalizare(ist)["goals_per_xg"] == pytest.approx(4.0 / 4.0)


def test_xg_total_zero_da_None_nu_impartire_la_zero():
    ist = [_m(1, 0.0)] * 5
    assert eficienta_finalizare(ist)["goals_per_xg"] is None


# ════════════════════════════════════════════════════════════════════════
# 4. Multiplicatorul
# ════════════════════════════════════════════════════════════════════════

def test_k_zero_nu_schimba_nimic():
    for v in (0.5, 1.0, 1.5, 2.0):
        assert _contracta(v, 0.0, 0.7, 1.4) == pytest.approx(1.0)


def test_k_unu_e_semnalul_brut_in_interiorul_prinderii():
    assert _contracta(1.2, 1.0, 0.7, 1.4) == pytest.approx(1.2)
    assert _contracta(0.8, 1.0, 0.7, 1.4) == pytest.approx(0.8)


def test_contractia_trage_spre_unu_monoton():
    valori = [_contracta(1.6, k, 0.7, 1.4) for k in (1.0, 0.75, 0.5, 0.25, 0.0)]
    assert valori == sorted(valori, reverse=True)
    assert valori[-1] == pytest.approx(1.0)


def test_prinderea_opreste_valorile_absurde():
    """O echipă cu 2 goluri din 0,4 xG dă un multiplicator de 5 — ar strica
    predicția mai rău decât absența completă a semnalului."""
    assert _contracta(5.0, 1.0, 0.7, 1.4) == pytest.approx(1.4)
    assert _contracta(0.05, 1.0, 0.7, 1.4) == pytest.approx(0.7)


def test_semnal_absent_da_multiplicator_neutru():
    assert _contracta(None, 1.0, 0.7, 1.4) == pytest.approx(1.0)


# ════════════════════════════════════════════════════════════════════════
# 5. Setul de variante
# ════════════════════════════════════════════════════════════════════════

def test_referinta_nu_aplica_nicio_ajustare():
    """Brațul de referință TREBUIE să fie producția de azi — multiplicator 1,0
    indiferent de semnal. Dacă ar aplica ceva, toate deltele ar fi față de o
    formulă care nu rulează nicăieri."""
    ref = next(fn for n, fn in construieste_variante().items() if n.startswith("REFERINȚĂ"))
    for s in ({"goals_per_xg": 1.9}, {"goals_per_xg": 0.2}, {}, {"goals_per_xg": None}):
        assert ref(s) == 1.0


def test_setul_acopera_o_gama_de_contractii():
    """Cu o singură valoare de `k`, un rezultat negativ n-ar putea fi distins
    de o alegere proastă a mea."""
    nume = list(construieste_variante())
    k_uri = [n for n in nume if "goals_per_xg, k=" in n]
    assert len(k_uri) >= 4
    assert any("k=1.00" in n for n in k_uri), "lipsește aplicarea brută"
    assert any("k=0.15" in n for n in k_uri), "lipsește contracția puternică"


def test_toate_variantele_produc_multiplicatori_marginiti():
    """`poisson_model` primește xG × multiplicator; o valoare extremă ar da
    probabilități degenerate."""
    for nume, fn in construieste_variante().items():
        for s in ({"goals_per_xg": 9.0, "goals_per_sot": 9.0},
                  {"goals_per_xg": 0.0, "goals_per_sot": 0.0},
                  {"goals_per_xg": None, "goals_per_sot": None}):
            m = fn(s)
            assert 0.5 <= m <= 2.0, f"{nume} a produs {m}"


# ════════════════════════════════════════════════════════════════════════
# 6. Garda de plauzibilitate
# ════════════════════════════════════════════════════════════════════════

def test_exista_garda_pe_acuratetea_referintei():
    """Fără ea, o eroare de indexare cu UNU a produs 0,3054 acuratețe — sub
    ghicitul aleatoriu — fără nicio excepție și cu un tabel care arăta normal.
    Garda e singura care transformă acel simptom în oprire."""
    cod = _doar_cod(SCRIPT)
    assert "0.40 <= acc_ref <= 0.60" in cod
    assert "return 1" in cod.split("0.40 <= acc_ref <= 0.60")[1][:900], \
        "garda trebuie să OPREASCĂ rularea, nu doar să avertizeze"
