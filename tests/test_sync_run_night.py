"""Teste pentru sync/run_night.py — orchestrare Night Sync (Faza 2, §7).

Verifică: toate cele 11 etape rulează, în ordine; o etapă eșuată NU
oprește restul pipeline-ului (izolare per etapă); raportul final conține
un rând per etapă cu ok/detail sau ok=False/error. Fără rețea — fiecare
dependență externă (`sync.run_daily.run`, `providers.flashscore.
run_foundation_data_layer.run`, `learning_core.run_continuous_learning.
main`, `database.queries.get_recent_flashscore_matches`,
`providers.flashscore.season_cleanup.build_cleanup_dry_run_report`) e
monkeypatch-uită."""
from __future__ import annotations

import sync.run_night as night


def _patch_all_stages_ok(monkeypatch, calls):
    monkeypatch.setattr(night, "_stage_api_providers", lambda: calls.append("api_providers") or "ok")
    monkeypatch.setattr(night, "_stage_flashscore", lambda: calls.append("flashscore") or "ok")
    monkeypatch.setattr(night, "_stage_team_dna_feature_engineering", lambda: calls.append("team_dna") or "ok")
    monkeypatch.setattr(night, "_stage_oracle_refresh", lambda: calls.append("oracle_refresh") or "ok")
    monkeypatch.setattr(night, "_stage_ml_refresh", lambda: calls.append("ml_refresh") or "ok")
    monkeypatch.setattr(night, "_stage_diagnostics", lambda: calls.append("diagnostics") or {"matches_checked": 0})
    monkeypatch.setattr(night, "_stage_cleanup", lambda: calls.append("cleanup") or {"delete_executed": False})
    monkeypatch.setattr(night, "_stage_backup", lambda: calls.append("backup") or "not implemented")


def test_run_executes_all_stages_in_order(monkeypatch):
    calls: list[str] = []
    _patch_all_stages_ok(monkeypatch, calls)

    report = night.run()

    assert calls == [
        "api_providers", "flashscore", "team_dna", "oracle_refresh",
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
        "api_providers", "flashscore", "team_dna", "oracle_refresh",
        "ml_refresh", "diagnostics", "cleanup", "backup",
    ]  # toate etapele au rulat, in ciuda esecului celei de-a 2-a
    by_stage = {r["stage"]: r for r in report}
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


def test_backup_stage_reports_not_implemented_explicitly():
    """ADR-044 Addendum A6 — Backup ramane neimplementat, decizie
    explicita, niciodata simulat ca reusit cu continut fictiv."""
    detail = night._stage_backup()
    assert "neimplementat" in detail.lower()


def test_team_dna_stage_documents_live_computation_not_batch():
    detail = night._stage_team_dna_feature_engineering()
    assert "live" in detail.lower()


def test_oracle_refresh_stage_documents_live_computation_not_batch():
    detail = night._stage_oracle_refresh()
    assert "live" in detail.lower()


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
