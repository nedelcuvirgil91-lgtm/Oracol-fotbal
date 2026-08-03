"""Teste pentru sync/run_live.py — Live Sync (Faza 2; redefinit Pasul 2,
Master Repair Plan), nivelul UȘOR de sincronizare, DOAR Flashscore.

[ACTUALIZAT Pasul 2 Master Repair Plan] `sync.run_daily.run()` (providerii
API) a fost eliminat din run_live.py — rulează exclusiv în Night Sync, o
dată pe zi (Single Owner, ADR-045). Testele vechi care verificau apelul
`sync.run_daily.run(skip_features=True, skip_ml=True)` au fost eliminate;
rămân doar cele pentru Flashscore FDL, cu Delta Sync, degradare fără
excepție, --dry-run sare peste fetch. Fără rețea."""
from __future__ import annotations

import sync.run_live as live


def test_run_calls_flashscore_foundation_data_layer(monkeypatch):
    """[ACTUALIZAT Pasul 1+2 Master Repair Plan, ADR-045] `limit_per_league`
    vine din `get_limit_per_league_automated()` (configurabil prin Supabase
    `model_config`, nu hardcodat) și `include_future_fixtures=False` —
    soluția reală pentru cele 240 de fixture-uri viitoare persistate
    integral (audit 2026-08-03): rulările automate nu mai încearcă deloc
    hub-ul `/fixtures/`. `run_live.py` nu mai atinge deloc providerii API
    (Pasul 2)."""
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
    assert "api_providers" not in result


def test_run_dry_run_skips_flashscore_fetch(monkeypatch):
    fs_calls = []
    monkeypatch.setattr(
        "providers.flashscore.run_foundation_data_layer.run",
        lambda **kw: fs_calls.append(kw) or 0,
    )
    result = live.run(dry_run=True)
    assert fs_calls == []
    assert result["flashscore"]["ok"] is True


def test_run_degrades_gracefully_when_flashscore_raises(monkeypatch):
    monkeypatch.setattr("providers.flashscore.discovery.get_limit_per_league_automated", lambda: 20)

    def _boom(**kw):
        raise RuntimeError("playwright crashed")
    monkeypatch.setattr("providers.flashscore.run_foundation_data_layer.run", _boom)

    result = live.run(dry_run=False)
    assert result["flashscore"]["ok"] is False
    assert "playwright crashed" in result["flashscore"]["error"]


def test_run_reports_nonzero_exit_code_as_not_ok(monkeypatch):
    monkeypatch.setattr("providers.flashscore.discovery.get_limit_per_league_automated", lambda: 20)
    monkeypatch.setattr(
        "providers.flashscore.run_foundation_data_layer.run",
        lambda **kw: 1,
    )
    result = live.run(dry_run=False)
    assert result["flashscore"]["ok"] is False
    assert result["flashscore"]["exit_code"] == 1
