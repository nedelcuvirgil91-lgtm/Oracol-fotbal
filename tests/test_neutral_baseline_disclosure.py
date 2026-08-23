"""Teste pentru divulgarea meciurilor cu baseline neutru (ADR-065).

CONTEXT MĂSURAT (2026-08-23): 43 din 235 de meciuri din populația de evaluare
Challenger au ambele echipe cu `data_quality = 'neutral'`. Pentru ele Oracle
emite o CONSTANTĂ (Champions League: 18 rânduri / o singură valoare; Europa
League: 26 / una), în timp ce experimentul poate avea ELO real. Comparația nu
e „ambii orbi".

Efectul măsurat pe Challenger-ul activ `xgboost_v1`: acuratețea își inversează
semnul — +1,7 pp cu meciurile neutrale, −2,1 pp fără ele. Tot avantajul venea
din meciurile cu baseline orb. (Campionul promovat `blend_v1` a trecut testul:
toate trei metricile rămân favorabile și fără ele.)

ADR-065 adaugă un DIAGNOSTIC, nu schimbă criteriul de promovare.

Fără rețea, fără Supabase.
"""
from __future__ import annotations

import ast
import inspect

import shadow_testing as st


# ── _baseline_is_neutral (funcție pură) ──────────────────────────────────────

def test_ambele_neutrale_inseamna_baseline_orb():
    assert st._baseline_is_neutral(
        {"home_data_quality": "neutral", "away_data_quality": "neutral"}) is True


def test_o_singura_parte_neutrala_ramane_in_subsetul_informat():
    """GARDA. Prag deliberat strict pe AMBELE: cu o singură echipă neutrală,
    baseline-ul tot are informație parțială. Un prag mai larg ar exclude mai
    mult decât justifică dovada măsurată."""
    assert st._baseline_is_neutral(
        {"home_data_quality": "neutral", "away_data_quality": "live"}) is False
    assert st._baseline_is_neutral(
        {"home_data_quality": "live", "away_data_quality": "neutral"}) is False


def test_calitatile_reale_nu_sunt_neutre():
    for q in ("live", "partial", "elo"):
        assert st._baseline_is_neutral({"home_data_quality": q, "away_data_quality": q}) is False


def test_camp_lipsa_nu_e_tratat_ca_neutru():
    """Absența etichetei NU e dovadă de baseline orb — a exclude un meci pe
    baza unui câmp lipsă ar fi o presupunere (Regula #8)."""
    assert st._baseline_is_neutral({}) is False
    assert st._baseline_is_neutral({"home_data_quality": None, "away_data_quality": None}) is False


# ── cablarea în evaluate_experiment ─────────────────────────────────────────

def _sursa_evaluate() -> str:
    return inspect.getsource(st.evaluate_experiment)


def test_evaluarea_citeste_data_quality_din_match_history():
    """Fără cele două coloane în SELECT, diagnosticul ar clasifica TOTUL ca
    informat și ar raporta tăcut aceleași cifre ca populația completă."""
    sursa = _sursa_evaluate()
    assert "home_data_quality" in sursa and "away_data_quality" in sursa


def test_registrul_primeste_doar_campurile_de_verdict():
    """GARDA CENTRALĂ, găsită în timpul implementării.

    `_update_registry(**result)` scrie în `experiment_registry`, care NU are
    coloanele de diagnostic. Dacă apelul ajunge DUPĂ îmbogățirea dict-ului,
    scrierea eșuează cu câmpuri necunoscute — iar evaluarea întreagă cade.
    Ordinea trebuie să rămână: verdict → registry → diagnostic."""
    sursa = _sursa_evaluate()
    # `rfind`, NU `find`: functia contine si apeluri _update_registry pe caile
    # de iesire timpurie (`insufficient_data`), care sunt mereu inaintea
    # diagnosticului. Prima versiune a acestui test folosea `find` si trecea
    # chiar si cu apelul final mutat DUPA imbogatire — defect gasit prin
    # testare de mutatie, nu prin citire.
    poz_registry = sursa.rfind("_update_registry(")
    poz_diagnostic = sursa.rfind('"n_matches_informed"')
    assert poz_registry != -1 and poz_diagnostic != -1
    assert poz_registry < poz_diagnostic, (
        "_update_registry() trebuie apelat INAINTE de adaugarea campurilor "
        "ADR-065 — altfel scrie in experiment_registry coloane inexistente"
    )


def test_criteriul_de_promovare_nu_foloseste_subsetul_informat():
    """ADR-065 e explicit: diagnosticul NU schimbă criteriul (North Star #2).
    Statusul se decide exclusiv pe populația completă."""
    arbore = ast.parse(_sursa_evaluate())
    for nod in ast.walk(arbore):
        if isinstance(nod, ast.Assign):
            tinte = [t.id for t in nod.targets if isinstance(t, ast.Name)]
            if "status" in tinte:
                folosite = {n.id for n in ast.walk(nod.value) if isinstance(n, ast.Name)}
                assert not any("informed" in f for f in folosite), (
                    f"statusul nu are voie sa depinda de subsetul informat: {folosite}"
                )


def test_scriitorul_persista_cele_patru_campuri():
    import supabase_client as sb

    sursa = inspect.getsource(sb.record_challenger_evaluation)
    for camp in ("n_matches_informed", "delta_brier_informed",
                 "delta_logloss_informed", "delta_accuracy_informed"):
        assert f'"{camp}"' in sursa, f"{camp} nu se persista"


def test_verdictele_istorice_raman_null_nu_zero():
    """Un verdict calculat înainte de ADR-065 nu are diagnosticul — asta e
    „necunoscut", nu „zero avantaj pe subsetul informat"."""
    import supabase_client as sb

    par = inspect.signature(sb.record_challenger_evaluation).parameters
    for camp in ("n_matches_informed", "delta_brier_informed",
                 "delta_logloss_informed", "delta_accuracy_informed"):
        assert par[camp].default is None, f"{camp} trebuie sa aiba default None"
