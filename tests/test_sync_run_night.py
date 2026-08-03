"""Teste pentru sync/run_night.py — orchestrare Night Sync (Faza 2 finalizare).

Verifică: cele 8 etape rulează, în ordinea corectă (Discovery+API+
Validation+Canonical -> Flashscore -> Team DNA -> Oracle Data Layer ->
Continuous Learning [extra, pre-existentă] -> Diagnostics -> Cleanup ->
Backup); o etapă eșuată NU oprește restul pipeline-ului (izolare per
etapă); raportul final conține un rând per etapă cu ok/detail sau
ok=False/error. Fără rețea — fiecare dependență externă e monkeypatch-uită."""
from __future__ import annotations

import sync.run_night as night


def _patch_all_stages_ok(monkeypatch, calls):
    monkeypatch.setattr(night, "_stage_api_providers", lambda: calls.append("api_providers") or "ok")
    monkeypatch.setattr(night, "_stage_flashscore", lambda: calls.append("flashscore") or "ok")
    monkeypatch.setattr(night, "_stage_team_dna", lambda: calls.append("team_dna") or "ok")
    monkeypatch.setattr(night, "_stage_oracle_data_layer", lambda: calls.append("oracle_data_layer") or "ok")
    monkeypatch.setattr(night, "_stage_ml_refresh_pre_existing", lambda: calls.append("ml_refresh") or "ok")
    monkeypatch.setattr(night, "_stage_diagnostics", lambda: calls.append("diagnostics") or {"matches_checked": 0})
    monkeypatch.setattr(night, "_stage_cleanup", lambda: calls.append("cleanup") or {"delete_executed": False})
    monkeypatch.setattr(night, "_stage_backup", lambda: calls.append("backup") or {"ok": True, "path": "x"})


def test_run_executes_all_stages_in_order(monkeypatch):
    calls: list[str] = []
    _patch_all_stages_ok(monkeypatch, calls)

    report = night.run()

    assert calls == [
        "api_providers", "flashscore", "team_dna", "oracle_data_layer",
        "ml_refresh", "diagnostics", "cleanup", "backup",
    ]
    assert len(report) == 8
    assert all(r["ok"] for r in report)


def test_run_isolates_a_failing_stage_and_continues(monkeypatch):
    calls: list[str] = []
    _patch_all_stages_ok(monkeypatch, calls)

    def _boom():
        calls.append("flashscore")
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(night, "_stage_flashscore", _boom)

    report = night.run()

    assert calls == [
        "api_providers", "flashscore", "team_dna", "oracle_data_layer",
        "ml_refresh", "diagnostics", "cleanup", "backup",
    ]  # toate etapele au rulat, in ciuda esecului celei de-a 2-a
    flashscore_report = next(r for r in report if "Flashscore" in r["stage"])
    assert flashscore_report["ok"] is False
    assert "simulated failure" in flashscore_report["error"]
    # Restul etapelor raman OK, neafectate.
    assert sum(1 for r in report if r["ok"]) == 7


def test_run_returns_report_with_duration_for_every_stage(monkeypatch):
    calls: list[str] = []
    _patch_all_stages_ok(monkeypatch, calls)
    report = night.run()
    for r in report:
        assert "duration_s" in r
        assert isinstance(r["duration_s"], float)


def test_backup_stage_calls_real_backup_module(monkeypatch):
    """Backup nu mai e placeholder — apelează providers.flashscore.backup.run_backup()."""
    calls = []
    monkeypatch.setattr(
        "providers.flashscore.backup.run_backup",
        lambda: calls.append("run_backup") or {"ok": True, "path": "backups/x.json", "row_counts": {}},
    )
    detail = night._stage_backup()
    assert calls == ["run_backup"]
    assert detail["ok"] is True
    assert detail["path"] == "backups/x.json"


def test_flashscore_stage_uses_configurable_limit_and_excludes_future_fixtures(monkeypatch):
    """[ADAUGAT Pasul 1 Master Repair Plan, ADR-045; rafinat dupa feedback]
    Plafonul vine din get_limit_per_league_automated() (configurabil prin
    Supabase model_config, nu hardcodat) si include_future_fixtures=False
    — solutia reala pentru cele 240 de fixture-uri viitoare persistate
    integral (audit 2026-08-03)."""
    monkeypatch.setattr("providers.flashscore.discovery.get_limit_per_league_automated", lambda: 27)
    calls = []
    monkeypatch.setattr(
        "providers.flashscore.run_foundation_data_layer.run",
        lambda leagues=None, limit_per_league=None, dry_run=False, include_future_fixtures=True:
            calls.append((leagues, limit_per_league, dry_run, include_future_fixtures)) or 0,
    )
    detail = night._stage_flashscore()
    assert calls == [(None, 27, False, False)]
    assert "exit_code=0" in detail


def test_team_dna_stage_documents_live_computation_not_batch():
    detail = night._stage_team_dna()
    assert "live" in detail.lower()


def test_oracle_data_layer_stage_documents_context_only_no_recalibration():
    detail = night._stage_oracle_data_layer()
    assert "live" in detail.lower() or "context" in detail.lower()


def test_diagnostics_stage_degrades_to_zero_when_no_matches(monkeypatch):
    monkeypatch.setattr("database.queries.get_recent_flashscore_matches", lambda limit=20: [])
    detail = night._stage_diagnostics()
    assert detail == {"matches_checked": 0, "avg_coverage_percent": None}


def test_diagnostics_stage_averages_real_coverage(monkeypatch):
    rows = [{"coverage_percent": 100.0}, {"coverage_percent": 50.0}]
    monkeypatch.setattr("database.queries.get_recent_flashscore_matches", lambda limit=20: rows)
    detail = night._stage_diagnostics()
    assert detail["matches_checked"] == 2
    assert detail["avg_coverage_percent"] == 75.0
    assert detail["min_coverage_percent"] == 50.0


def test_cleanup_stage_never_deletes(monkeypatch):
    monkeypatch.setattr(
        "providers.flashscore.season_cleanup.build_cleanup_dry_run_report",
        lambda: {"delete_executed": False, "cleanup_candidates": ["2019-2020"]},
    )
    detail = night._stage_cleanup()
    assert detail["delete_executed"] is False
    assert detail["cleanup_candidates"] == ["2019-2020"]


def test_ml_refresh_stage_is_gated_and_pre_existing(monkeypatch):
    """Continuous Learning (ADR-030) ramane pre-existenta, independenta de
    Flashscore - doar pastrata aici ca sa nu se piarda automatizarea dupa
    consolidarea schedulerului (cron-ul propriu a fost dezactivat)."""
    calls = []
    monkeypatch.setattr(
        "learning_core.run_continuous_learning.main",
        lambda: calls.append("main") or None,
    )
    detail = night._stage_ml_refresh_pre_existing()
    assert calls == ["main"]
    assert "pre-existent" in detail.lower()
