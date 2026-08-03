"""Teste pentru sync/run_live.py — Live Sync (Faza 2), nivelul UȘOR de
sincronizare, ziua. Verifică: apelează sync.run_daily.run() cu
skip_features=True/skip_ml=True (exclude explicit Feature Engineering/ML
Refresh), apelează Flashscore FDL cu Delta Sync, degradează fără excepție
la eșecul oricărei bucăți, --dry-run sare peste fetch-ul Flashscore. Fără
rețea."""
from __future__ import annotations

import sync.run_live as live


def test_run_calls_daily_sync_with_features_and_ml_skipped(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "sync.run_daily.run",
        lambda skip_features=False, skip_ml=False, dry_run=False: calls.append(
            {"skip_features": skip_features, "skip_ml": skip_ml, "dry_run": dry_run}
        ),
    )
    monkeypatch.setattr("providers.flashscore.discovery.get_limit_per_league_automated", lambda: 20)
    monkeypatch.setattr(
        "providers.flashscore.run_foundation_data_layer.run",
        lambda leagues=None, limit_per_league=None, dry_run=False, include_future_fixtures=True: 0,
    )
    live.run(dry_run=False)
    assert calls == [{"skip_features": True, "skip_ml": True, "dry_run": False}]


def test_run_calls_flashscore_foundation_data_layer(monkeypatch):
    """[ACTUALIZAT Pasul 1 Master Repair Plan, ADR-045; rafinat dupa
    feedback] `limit_per_league` vine acum din
    `get_limit_per_league_automated()` (configurabil prin Supabase
    `model_config`, nu hardcodat) și `include_future_fixtures=False` —
    soluția reală pentru cele 240 de fixture-uri viitoare persistate
    integral (audit 2026-08-03): rulările automate nu mai încearcă deloc
    hub-ul `/fixtures/`."""
    monkeypatch.setattr("sync.run_daily.run", lambda **kw: None)
    monkeypatch.setattr("providers.flashscore.discovery.get_limit_per_league_automated", lambda: 33)
    fs_calls = []
    monkeypatch.setattr(
        "providers.flashscore.run_foundation_data_layer.run",
        lambda leagues=None, limit_per_league=None, dry_run=False, include_future_fixtures=True: fs_calls.append(
            (leagues, limit_per_league, dry_run, include_future_fixtures)
        ) or 0,
    )
    result = live.run(dry_run=False)
    assert fs_calls == [(None, 33, False, False)]
    assert result["flashscore"]["ok"] is True


def test_run_dry_run_skips_flashscore_fetch(monkeypatch):
    monkeypatch.setattr("sync.run_daily.run", lambda **kw: None)
    fs_calls = []
    monkeypatch.setattr(
        "providers.flashscore.run_foundation_data_layer.run",
        lambda **kw: fs_calls.append(kw) or 0,
    )
    result = live.run(dry_run=True)
    assert fs_calls == []
    assert result["flashscore"]["ok"] is True


def test_run_degrades_gracefully_when_daily_sync_raises(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("network down")
    monkeypatch.setattr("sync.run_daily.run", _boom)
    monkeypatch.setattr("providers.flashscore.discovery.get_limit_per_league_automated", lambda: 20)
    monkeypatch.setattr(
        "providers.flashscore.run_foundation_data_layer.run",
        lambda **kw: 0,
    )
    result = live.run(dry_run=False)
    assert result["api_providers"]["ok"] is False
    assert "network down" in result["api_providers"]["error"]
    # Flashscore tot ruleaza, independent de esecul provider-ilor API.
    assert result["flashscore"]["ok"] is True


def test_run_degrades_gracefully_when_flashscore_raises(monkeypatch):
    monkeypatch.setattr("sync.run_daily.run", lambda **kw: None)
    monkeypatch.setattr("providers.flashscore.discovery.get_limit_per_league_automated", lambda: 20)

    def _boom(**kw):
        raise RuntimeError("playwright crashed")
    monkeypatch.setattr("providers.flashscore.run_foundation_data_layer.run", _boom)

    result = live.run(dry_run=False)
    assert result["api_providers"]["ok"] is True
    assert result["flashscore"]["ok"] is False
    assert "playwright crashed" in result["flashscore"]["error"]


def test_run_reports_nonzero_exit_code_as_not_ok(monkeypatch):
    monkeypatch.setattr("sync.run_daily.run", lambda **kw: None)
    monkeypatch.setattr("providers.flashscore.discovery.get_limit_per_league_automated", lambda: 20)
    monkeypatch.setattr(
        "providers.flashscore.run_foundation_data_layer.run",
        lambda **kw: 1,
    )
    result = live.run(dry_run=False)
    assert result["flashscore"]["ok"] is False
    assert result["flashscore"]["exit_code"] == 1
