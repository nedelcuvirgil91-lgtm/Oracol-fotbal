"""Teste de integrare pentru Dashboard-ul Provider Health din app.py
(ADR-041 Faza 2, Sprint 1.1 #5) — streamlit.testing.v1.AppTest, tiparul din
test_app_value_bets_view.py. Fără Supabase live (degradare grațioasă —
provider_call_log_source/registry citesc local, fără rețea, în acest
mediu) — verifică WIRING-ul (nu aruncă, secțiunea apare, tabelul are
coloanele așteptate), nu valorile exacte (acelea sunt acoperite de testele
pure din test_provider_health_score.py/test_provider_cost_estimator.py)."""
from __future__ import annotations

import pathlib

from streamlit.testing.v1 import AppTest


# [REPARAT 2026-08-21] `AppTest.from_file(_APP)` era rezolvat relativ la
# fisierul de test (`tests/app.py`), nu la radacina repo-ului — FileNotFoundError
# la fiecare rulare. Calea se calculeaza acum explicit din locatia acestui
# fisier, deci nu mai depinde nici de directorul de lucru, nici de felul in care
# Streamlit alege sa rezolve caile relative.
_APP = str(pathlib.Path(__file__).resolve().parent.parent / "app.py")

def test_provider_health_dashboard_button_renders_report_without_crashing():
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["nav"] = "settings"
    at.run()
    assert not at.exception

    buttons = [b for b in at.button if "Calculează Health Score" in (b.label or "")]
    assert len(buttons) == 1, "Butonul 'Calculează Health Score' nu a fost găsit în tab-ul Diagnostics"

    buttons[0].click().run()
    assert not at.exception

    report = at.session_state["provider_health_score_report"]
    assert report is not None
    assert len(report) > 0  # cel puțin providerii înregistrați (Provider Registry, static)

    expected_cols = {
        "Provider", "Apeluri 24h", "Succes 24h", "Apeluri 7z", "Succes 7z",
        "429", "403", "Timeout", "5xx", "Altele",
        "Cotă folosită", "Epuizare estimată", "Cost estimat",
    }
    assert expected_cols <= set(report[0].keys())


def test_provider_health_dashboard_caption_shown_before_button_click():
    at = AppTest.from_file(_APP, default_timeout=30)
    at.session_state["nav"] = "settings"
    at.run()
    assert not at.exception
    captions = " ".join(c.value for c in at.caption)
    assert "Fără raport încă" in captions
