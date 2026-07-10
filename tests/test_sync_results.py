import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/claude/stubs")

import sync.sync_results as sr


def test_fetch_results_uses_sliding_window_by_default():
    """Regresie directa pe bug-ul real gasit: inainte se verifica STRICT
    'ieri' (o singura zi) - 16 meciuri World Cup 2026 au ramas blocate fara
    actual_result din exact acest motiv. Acum trebuie sa acopere o fereastra
    de cateva zile, nu o singura zi fixa."""
    captured_params = {}

    def fake_rate_limited_get(url, params=None):
        captured_params.update(params or {})
        return {"matches": []}

    original = sr._rate_limited_get
    sr._rate_limited_get = fake_rate_limited_get
    try:
        sr.fetch_yesterday_results()  # fara target_date explicit -> fereastra
        today = datetime.now(timezone.utc).date()
        expected_date_to = (today - timedelta(days=1)).isoformat()
        expected_date_from = (today - timedelta(days=7)).isoformat()
        assert captured_params.get("dateTo") == expected_date_to
        assert captured_params.get("dateFrom") == expected_date_from
        assert captured_params.get("dateFrom") != captured_params.get("dateTo"), (
            "dateFrom si dateTo sunt identice - inseamna ca fereastra NU s-a extins, "
            "e tot comportamentul vechi de o singura zi"
        )
    finally:
        sr._rate_limited_get = original


def test_fetch_results_explicit_single_date_still_works():
    """Comportamentul vechi (o singura zi explicita) trebuie pastrat pt
    teste/debugging punctual - target_date explicit ignora fereastra."""
    captured_params = {}

    def fake_rate_limited_get(url, params=None):
        captured_params.update(params or {})
        return {"matches": []}

    original = sr._rate_limited_get
    sr._rate_limited_get = fake_rate_limited_get
    try:
        sr.fetch_yesterday_results(target_date="2026-07-05")
        assert captured_params.get("dateFrom") == "2026-07-05"
        assert captured_params.get("dateTo") == "2026-07-05"
    finally:
        sr._rate_limited_get = original


def test_fetch_results_custom_days_back():
    """Confirma ca days_back e configurabil, nu fixat la 7."""
    captured_params = {}

    def fake_rate_limited_get(url, params=None):
        captured_params.update(params or {})
        return {"matches": []}

    original = sr._rate_limited_get
    sr._rate_limited_get = fake_rate_limited_get
    try:
        sr.fetch_yesterday_results(days_back=14)
        today = datetime.now(timezone.utc).date()
        expected_date_from = (today - timedelta(days=14)).isoformat()
        assert captured_params.get("dateFrom") == expected_date_from
    finally:
        sr._rate_limited_get = original
