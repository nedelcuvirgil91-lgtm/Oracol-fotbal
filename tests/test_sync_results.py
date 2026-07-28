import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/claude/stubs")

import supabase_client as sb
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


def _fake_match_row_and_result():
    match_row = {"home_xg_pred": 1.5, "away_xg_pred": 1.0, "fixture_id": "test-fixture"}
    r = {
        "league": "Premier League", "home_team": "A", "away_team": "B",
        "home_goals": 2, "away_goals": 1, "kickoff_date": "2026-01-01",
    }
    return match_row, r


def test_recalibrate_for_result_respects_disabled_flag(monkeypatch):
    """[ADR-004] Cand auto_recalibration_enabled=False (setat explicit in
    model_config), recalibrarea nu se mai executa - save_weights nu se apeleaza."""
    calls = {"save_weights": 0}

    monkeypatch.setattr(sb, "load_config", lambda default: {**default, "auto_recalibration_enabled": False})
    monkeypatch.setattr(sb, "load_weights", lambda default: dict(default))
    monkeypatch.setattr(sb, "save_weights", lambda data: calls.__setitem__("save_weights", calls["save_weights"] + 1) or True)
    monkeypatch.setattr(sb, "append_recalibration_log", lambda row: True)

    match_row, r = _fake_match_row_and_result()
    sr._recalibrate_for_result(match_row, r)

    assert calls["save_weights"] == 0


def test_recalibrate_for_result_default_disabled_after_adr028(monkeypatch):
    """[ADR-028] Comportament implicit SCHIMBAT intentionat: fara
    auto_recalibration_enabled setat explicit in model_config, calea legacy
    NU mai ruleaza (implicit False - vezi CLAUDE.md North Star #3). Sursa
    canonica de invatare devine league_weights_adaptive (Model Registry)."""
    calls = {"save_weights": 0}

    # simuleaza model_config fara cheia noua inca scrisa - exact cazul real de azi
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))
    monkeypatch.setattr(sb, "load_weights", lambda default: dict(default))
    monkeypatch.setattr(sb, "save_weights", lambda data: calls.__setitem__("save_weights", calls["save_weights"] + 1) or True)
    monkeypatch.setattr(sb, "append_recalibration_log", lambda row: True)

    match_row, r = _fake_match_row_and_result()
    sr._recalibrate_for_result(match_row, r)

    assert calls["save_weights"] == 0


def test_recalibrate_for_result_explicit_enabled_still_works(monkeypatch):
    """[ADR-028] Calea legacy nu a fost stearsa - activata explicit
    (auto_recalibration_enabled=True in model_config), tot functioneaza
    identic ca inainte."""
    calls = {"save_weights": 0}

    monkeypatch.setattr(sb, "load_config", lambda default: {**default, "auto_recalibration_enabled": True})
    monkeypatch.setattr(sb, "load_weights", lambda default: dict(default))
    monkeypatch.setattr(sb, "save_weights", lambda data: calls.__setitem__("save_weights", calls["save_weights"] + 1) or True)
    monkeypatch.setattr(sb, "append_recalibration_log", lambda row: True)

    match_row, r = _fake_match_row_and_result()
    sr._recalibrate_for_result(match_row, r)

    assert calls["save_weights"] == 1


def test_recalibrate_for_result_skips_when_no_predicted_xg():
    """Comportament deja existent, neschimbat - fara xG predictat, iese
    devreme, inainte de a atinge flag-ul sau Supabase."""
    r = {"league": "Premier League", "home_team": "A", "away_team": "B",
         "home_goals": 1, "away_goals": 0, "kickoff_date": "2026-01-01"}
    # nu ar trebui sa arunce nicio exceptie (nu atinge deloc supabase_client)
    sr._recalibrate_for_result({"fixture_id": "no-xg"}, r)


# ── fetch_results_from_odds_api_recent (Sprint 0 — Stabilizare, Etapa 2) ──

def test_fetch_results_from_odds_api_recent_transforms_rows(monkeypatch):
    import database.queries as q

    rows = [
        {"home_team_canonical": "Portland Timbers", "away_team_canonical": "Real Salt Lake",
         "kickoff_date": "2026-07-26", "league": "MLS", "home_score": 2, "away_score": 1},
        {"home_team_canonical": "San Jose Earthquakes", "away_team_canonical": "LA Galaxy",
         "kickoff_date": "2026-07-26", "league": "MLS", "home_score": 1, "away_score": 1},
    ]
    monkeypatch.setattr(q, "get_recent_odds_results", lambda days_back=14: rows)

    results = sr.fetch_results_from_odds_api_recent()

    assert len(results) == 2
    assert results[0]["home_team"] == "Portland Timbers"
    assert results[0]["away_team"] == "Real Salt Lake"
    assert results[0]["league"] == "MLS"
    assert results[0]["kickoff_date"] == "2026-07-26"
    assert results[0]["home_goals"] == 2
    assert results[0]["away_goals"] == 1
    assert results[0]["actual_result"] == "H"
    assert results[0]["fd_id"] is None
    assert results[1]["actual_result"] == "D"


def test_fetch_results_from_odds_api_recent_skips_incomplete_scores(monkeypatch):
    import database.queries as q

    rows = [{"home_team_canonical": "A", "away_team_canonical": "B",
             "kickoff_date": "2026-07-26", "league": "MLS", "home_score": None, "away_score": 1}]
    monkeypatch.setattr(q, "get_recent_odds_results", lambda days_back=14: rows)

    assert sr.fetch_results_from_odds_api_recent() == []


def test_fetch_results_from_odds_api_recent_returns_empty_on_exception(monkeypatch):
    import database.queries as q

    def _boom(days_back=14):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(q, "get_recent_odds_results", _boom)
    assert sr.fetch_results_from_odds_api_recent() == []


def test_sync_yesterday_results_combines_both_sources(monkeypatch):
    """[Sprint 0 — Stabilizare, Etapa 2] football-data.org SI
    odds_api_recent_results trebuie combinate INTR-O SINGURA cale de
    scriere (update_results_in_supabase) — nu doua cai separate."""
    fd_results = [{"fd_id": 1, "home_team": "A", "away_team": "B", "league": "Premier League",
                   "kickoff_date": "2026-07-26", "home_goals": 1, "away_goals": 0, "actual_result": "H"}]
    odds_results = [{"fd_id": None, "home_team": "C", "away_team": "D", "league": "MLS",
                      "kickoff_date": "2026-07-26", "home_goals": 2, "away_goals": 2, "actual_result": "D"}]

    monkeypatch.setattr(sr, "fetch_yesterday_results", lambda: fd_results)
    monkeypatch.setattr(sr, "fetch_results_from_odds_api_recent", lambda: odds_results)

    captured = {}

    def fake_update(results):
        captured["results"] = results
        return len(results), 0

    monkeypatch.setattr(sr, "update_results_in_supabase", fake_update)

    result = sr.sync_yesterday_results()

    assert captured["results"] == fd_results + odds_results
    assert result["updated"] == 2


def test_sync_yesterday_results_survives_odds_bridge_failure(monkeypatch):
    """Un esec al bridge-ului Odds API nu trebuie sa opreasca fluxul
    principal (football-data.org) — degradare gratioasa, ca restul
    modulului."""
    fd_results = [{"fd_id": 1, "home_team": "A", "away_team": "B", "league": "Premier League",
                   "kickoff_date": "2026-07-26", "home_goals": 1, "away_goals": 0, "actual_result": "H"}]

    monkeypatch.setattr(sr, "fetch_yesterday_results", lambda: fd_results)

    def _boom():
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(sr, "fetch_results_from_odds_api_recent", _boom)

    captured = {}

    def fake_update(results):
        captured["results"] = results
        return len(results), 0

    monkeypatch.setattr(sr, "update_results_in_supabase", fake_update)

    result = sr.sync_yesterday_results()

    assert captured["results"] == fd_results
    assert result["updated"] == 1
