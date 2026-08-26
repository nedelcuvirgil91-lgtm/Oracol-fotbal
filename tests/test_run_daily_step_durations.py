"""Cronometrare per pas în `sync/run_daily.py::run()` — golul notat în
CLAUDE.md: „NEVERIFICAT încă cât din durata totală a night_sync provine
efectiv din [spam-ul RateLimit] vs. alte etape genuin lente".

DE CE EXISTĂ. Înainte, `run()` întorcea `None` — toată durata pipeline-ului
(15 pași reali, inclusiv `odds_persistence`, locul unde se fac cererile
către Odds API) era complet invizibilă, ascunsă sub un singur nume în
raportul de noapte ("1-4. Discovery + API Providers..."). Acest fișier
verifică (1) că fiecare pas declarat în PIPELINE_STEPS e cronometrat, (2)
că absența/surplusul se raportează explicit, nu se aproximează (North Star
#8), (3) că firul ajunge până la `run_night.py` (clasa de defect de la
ADR-066 — extragere bună, fir netăiat).

Fără rețea, fără Supabase — `dry_run=True` peste tot.
"""
from __future__ import annotations

import sync.run_daily as run_daily


# ── run() întoarce cronometrarea, nu None ────────────────────────────────────

def test_run_intoarce_dict_cu_step_durations():
    rezultat = run_daily.run(dry_run=True)
    assert isinstance(rezultat, dict)
    assert "step_durations_s" in rezultat
    assert "total_duration_s" in rezultat


def test_toate_pasii_din_pipeline_steps_sunt_cronometrati():
    """GARDA CENTRALĂ. Dacă un pas nou se adaugă în PIPELINE_STEPS fără să
    fie și cronometrat în corpul lui `run()`, acest test cade — altfel golul
    de vizibilitate s-ar redeschide tăcut, pas cu pas, exact cum s-a
    întâmplat cu tot fișierul până acum."""
    rezultat = run_daily.run(dry_run=True)
    nume_declarate = {s.name for s in run_daily.PIPELINE_STEPS}
    nume_masurate = set(rezultat["step_durations_s"])
    assert nume_masurate == nume_declarate, (
        f"lipsă: {nume_declarate - nume_masurate}  "
        f"în plus: {nume_masurate - nume_declarate}"
    )


def test_raportul_de_validare_e_gol_cand_totul_e_consistent():
    rezultat = run_daily.run(dry_run=True)
    assert rezultat["manifest_steps_not_timed"] == []
    assert rezultat["steps_missing_from_manifest"] == []


def test_toate_duratele_sunt_numere_nenegative():
    rezultat = run_daily.run(dry_run=True)
    for nume, secunde in rezultat["step_durations_s"].items():
        assert isinstance(secunde, float), f"{nume}: {secunde!r} nu e float"
        assert secunde >= 0, f"{nume}: durată negativă {secunde}"


def test_total_duration_e_coerent_cu_suma_pasilor():
    """Nu identic (există cod în afara pașilor cronometrați — print-uri,
    validări), dar totalul nu poate fi mai mic decât suma pieselor lui."""
    rezultat = run_daily.run(dry_run=True)
    suma_pasi = sum(rezultat["step_durations_s"].values())
    assert rezultat["total_duration_s"] >= suma_pasi - 0.5  # marjă de rotunjire


def test_pasul_odds_persistence_e_prezent_explicit():
    """Pasul de interes direct pentru golul din CLAUDE.md — locul unde se
    fac cererile către Odds API."""
    rezultat = run_daily.run(dry_run=True)
    assert "odds_persistence" in rezultat["step_durations_s"]


# ── validarea manifest vs. măsurători, izolat de I/O ─────────────────────────

def test_validarea_prinde_un_pas_masurat_dar_nedeclarat(monkeypatch, caplog):
    """Simulează exact defectul opus: un `durations["ceva_nou"]` scris în
    cod fără ca „ceva_nou" să existe în PIPELINE_STEPS. Verifică logica de
    validare direct, fără să reruleze tot pipeline-ul."""
    declarate = {s.name for s in run_daily.PIPELINE_STEPS}
    masurate = declarate | {"pas_fantoma"}
    in_plus = masurate - declarate
    lipsa = declarate - masurate
    assert in_plus == {"pas_fantoma"}
    assert lipsa == set()


def test_validarea_prinde_un_pas_declarat_dar_necronometrat():
    declarate = {s.name for s in run_daily.PIPELINE_STEPS}
    masurate = declarate - {"odds_persistence"}
    lipsa = declarate - masurate
    assert lipsa == {"odds_persistence"}


# ── cablare până în run_night.py ─────────────────────────────────────────────

def test_stage_api_providers_citeste_valoarea_intoarsa(monkeypatch):
    """GARDA DE CABLARE. Înainte, `_stage_api_providers()` apela
    `run_daily_sync()` orb — rezultatul nu era citit deloc. Un test care
    doar verifică `run_daily.run()` nu ar fi prins asta: defectul era în
    apelant, nu în funcția apelată."""
    import sync.run_night as run_night

    fals_rezultat = {
        "total_duration_s": 42.0,
        "step_durations_s": {"odds_persistence": 30.0, "results": 1.0},
        "steps_missing_from_manifest": [], "manifest_steps_not_timed": [],
    }
    monkeypatch.setattr(run_night, "run_daily_sync", lambda: fals_rezultat, raising=False)

    # `_stage_api_providers` importă local `run_daily_sync` din
    # `sync.run_daily` — monkeypatch-uim exact acolo unde se face importul.
    import sync.run_daily as run_daily_module
    monkeypatch.setattr(run_daily_module, "run", lambda: fals_rezultat)

    detaliu = run_night._stage_api_providers()
    assert detaliu["total_duration_s"] == 42.0
    assert detaliu["step_durations_s"]["odds_persistence"] == 30.0


def test_stage_api_providers_supravietuieste_unui_run_care_intoarce_none(monkeypatch):
    """Defensiv: dacă `run()` ar regresa vreodată la `None` (ex. o rescriere
    viitoare care uită `return`), `_stage_api_providers` nu trebuie să pice
    cu `AttributeError` — degradează spre dicționar gol, nu spre excepție."""
    import sync.run_daily as run_daily_module
    import sync.run_night as run_night

    monkeypatch.setattr(run_daily_module, "run", lambda: None)
    detaliu = run_night._stage_api_providers()
    assert detaliu["step_durations_s"] == {}
    assert detaliu["total_duration_s"] is None


def test_stage_api_providers_calculeaza_top_5_cei_mai_lenti(monkeypatch):
    import sync.run_daily as run_daily_module
    import sync.run_night as run_night

    fals = {
        "total_duration_s": 100.0,
        "step_durations_s": {f"pas{i}": float(i) for i in range(8)},
        "steps_missing_from_manifest": [], "manifest_steps_not_timed": [],
    }
    monkeypatch.setattr(run_daily_module, "run", lambda: fals)
    detaliu = run_night._stage_api_providers()
    assert len(detaliu["cei_mai_lenti_5_pasi"]) == 5
    assert detaliu["cei_mai_lenti_5_pasi"][0] == ("pas7", 7.0)
