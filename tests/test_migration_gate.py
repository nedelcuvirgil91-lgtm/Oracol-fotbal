"""Teste pentru migration_gate.py (ADR-040, G3) — status/explain/attest/verify.
Logica pură (compute_verdict/dominant_root_cause/build_attestation_payload)
testată fără I/O; orchestrarea (get_status/explain/attest/verify) testată
cu Supabase/filesystem mockuite."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import migration_gate as mod


def _view_row(**overrides) -> dict:
    base = dict(
        gate_key="R-Sync-7b", entity="scheduled_fixtures",
        total_matched_eligible=600, eligible_row_count=10,
        latest_eligible_at="2026-07-27T00:00:00+00:00",
        min_provider_matched=60, current_health="green", current_health_at="2026-07-27T00:00:00+00:00",
    )
    base.update(overrides)
    return base


_THRESHOLDS = {"min_matched_total": 500, "min_matched_per_provider": 50}


# ── compute_verdict (pur) ────────────────────────────────────────────────────

def test_compute_verdict_gray_when_no_row():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", None, _THRESHOLDS)
    assert v.verdict == "GRAY"
    assert v.current_health is None
    assert v.historical_confidence == 0.0


def test_compute_verdict_gray_when_current_health_none():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(current_health=None), _THRESHOLDS)
    assert v.verdict == "GRAY"


def test_compute_verdict_fail_when_current_health_red_regardless_of_volume():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures",
                             _view_row(current_health="red", total_matched_eligible=10000), _THRESHOLDS)
    assert v.verdict == "FAIL"
    assert "RED" in v.reasons[0]


def test_compute_verdict_fail_when_current_health_broken():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(current_health="broken"), _THRESHOLDS)
    assert v.verdict == "FAIL"


def test_compute_verdict_pass_when_confidence_full_and_healthy():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(), _THRESHOLDS)
    assert v.verdict == "PASS"
    assert v.historical_confidence == 1.0


def test_compute_verdict_pass_with_yellow_health():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(current_health="yellow"), _THRESHOLDS)
    assert v.verdict == "PASS"


def test_compute_verdict_gray_when_healthy_but_insufficient_total_volume():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures",
                             _view_row(total_matched_eligible=100), _THRESHOLDS)
    assert v.verdict == "GRAY"
    assert v.historical_confidence < 1.0


def test_compute_verdict_gray_when_healthy_but_weakest_provider_insufficient():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures",
                             _view_row(min_provider_matched=10), _THRESHOLDS)
    assert v.verdict == "GRAY"
    assert v.historical_confidence == 10 / 50


def test_compute_verdict_min_not_average_between_volume_and_provider():
    """Un singur provider structural minoritar nu se ascunde -- MIN, nu medie."""
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures",
                             _view_row(total_matched_eligible=10000, min_provider_matched=5), _THRESHOLDS)
    assert v.historical_confidence == 5 / 50
    assert v.verdict == "GRAY"


def test_compute_verdict_no_provider_data_at_all_is_zero_confidence_not_assumed_full():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures",
                             _view_row(min_provider_matched=None), _THRESHOLDS)
    assert v.historical_confidence == 0.0
    assert v.verdict == "GRAY"


# ── load_thresholds ──────────────────────────────────────────────────────────

def test_load_thresholds_defaults_when_no_override(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    t = mod.load_thresholds("R-Sync-7b")
    assert t == {"min_matched_total": 500, "min_matched_per_provider": 50}


def test_load_thresholds_uses_per_gate_override(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: {
        "migration_gate_thresholds": {"R-Sync-7b": {"min_matched_total": 1000, "min_matched_per_provider": 100}},
    })

    t = mod.load_thresholds("R-Sync-7b")
    assert t == {"min_matched_total": 1000, "min_matched_per_provider": 100}


def test_load_thresholds_ignores_other_gate_overrides(monkeypatch):
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: {
        "migration_gate_thresholds": {"R-Sync-8": {"min_matched_total": 1}},
    })

    t = mod.load_thresholds("R-Sync-7b")
    assert t["min_matched_total"] == 500


# ── get_status (orchestrare) ─────────────────────────────────────────────────

def test_get_status_reads_view_row_and_thresholds(monkeypatch):
    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row())

    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    v = mod.get_status("R-Sync-7b", "scheduled_fixtures")
    assert v.verdict == "PASS"


# ── dominant_root_cause (pur) ─────────────────────────────────────────────────

def test_dominant_root_cause_empty_when_no_rows():
    assert mod.dominant_root_cause([]) is None


def test_dominant_root_cause_empty_when_no_diffs():
    assert mod.dominant_root_cause([{"root_cause_summary": {}}]) is None


def test_dominant_root_cause_picks_highest_total():
    rows = [
        {"root_cause_summary": {"VENUE_PRIORITY": 3, "UNKNOWN": 1}},
        {"root_cause_summary": {"UNKNOWN": 5}},
    ]
    assert mod.dominant_root_cause(rows) == "UNKNOWN"


# ── recommended_action (pur) ──────────────────────────────────────────────────

def test_recommended_action_none_category():
    assert "nimic de investigat" in mod.recommended_action(None)


def test_recommended_action_known_category():
    import equivalence_root_cause as root_cause
    action = mod.recommended_action(root_cause.MISSING_PROVIDER_ID)
    assert "sync_scheduled_fixtures" in action


def test_recommended_action_unrecognized_category_falls_back():
    action = mod.recommended_action("SOME_FUTURE_CATEGORY")
    assert "investigație manuală" in action.lower()


# ── explain (orchestrare) ─────────────────────────────────────────────────────

def test_explain_combines_verdict_and_dominant_cause(monkeypatch):
    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row())
    monkeypatch.setattr(queries, "list_recent_equivalence_evaluations",
                         lambda gk, e, limit=50: [{"root_cause_summary": {"VENUE_PRIORITY": 2}}])

    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    rep = mod.explain("R-Sync-7b", "scheduled_fixtures")
    assert rep.verdict.verdict == "PASS"
    assert rep.dominant_root_cause == "VENUE_PRIORITY"
    assert "SourcePriority" in rep.recommended_action


# ── build_attestation_payload (pur) ───────────────────────────────────────────

def test_build_attestation_payload_contains_verdict_and_digest():
    v = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(), _THRESHOLDS)
    payload = mod.build_attestation_payload(v, generated_at="2026-07-27T00:00:00+00:00")
    assert payload["gate_key"] == "R-Sync-7b"
    assert payload["verdict"] == "PASS"
    assert payload["evidence_digest"].startswith("sha256:")


def test_build_attestation_payload_digest_deterministic_for_same_verdict():
    v1 = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(), _THRESHOLDS)
    v2 = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(), _THRESHOLDS)
    p1 = mod.build_attestation_payload(v1, generated_at="2026-07-27T00:00:00+00:00")
    p2 = mod.build_attestation_payload(v2, generated_at="2026-07-27T00:00:00+00:00")
    assert p1["evidence_digest"] == p2["evidence_digest"]


def test_build_attestation_payload_digest_differs_for_different_verdict():
    v_pass = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(), _THRESHOLDS)
    v_fail = mod.compute_verdict("R-Sync-7b", "scheduled_fixtures", _view_row(current_health="red"), _THRESHOLDS)
    p_pass = mod.build_attestation_payload(v_pass, generated_at="t")
    p_fail = mod.build_attestation_payload(v_fail, generated_at="t")
    assert p_pass["evidence_digest"] != p_fail["evidence_digest"]


# ── attest / verify (I/O mockuit prin tmp_path) ───────────────────────────────

def test_attest_writes_file_with_current_verdict(tmp_path, monkeypatch):
    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row())
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    target = tmp_path / "R-Sync-7b.attestation.json"
    payload = mod.attest("R-Sync-7b", "scheduled_fixtures", path=target)

    assert target.exists()
    on_disk = json.loads(target.read_text())
    assert on_disk["verdict"] == payload["verdict"] == "PASS"


def test_attest_writes_even_when_verdict_is_fail(tmp_path, monkeypatch):
    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row(current_health="red"))
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    target = tmp_path / "R-Sync-7b.attestation.json"
    payload = mod.attest("R-Sync-7b", "scheduled_fixtures", path=target)
    assert payload["verdict"] == "FAIL"
    assert target.exists()


def test_verify_missing_file_is_invalid(tmp_path):
    result = mod.verify("R-Sync-7b", "scheduled_fixtures", path=tmp_path / "nope.json")
    assert result.valid is False
    assert "Nicio atestare" in result.reasons[0]


def test_verify_corrupted_file_is_invalid(tmp_path):
    target = tmp_path / "bad.json"
    target.write_text("{not valid json")
    result = mod.verify("R-Sync-7b", "scheduled_fixtures", path=target)
    assert result.valid is False


def test_verify_stale_attestation_flagged(tmp_path, monkeypatch):
    old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
    target = tmp_path / "stale.json"
    target.write_text(json.dumps({"verdict": "PASS", "generated_at": old_ts}))

    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row())
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    result = mod.verify("R-Sync-7b", "scheduled_fixtures", path=target)
    assert result.valid is False
    assert any("veche" in r for r in result.reasons)


def test_verify_mismatched_verdict_flagged(tmp_path, monkeypatch):
    fresh_ts = datetime.now(timezone.utc).isoformat()
    target = tmp_path / "mismatch.json"
    target.write_text(json.dumps({"verdict": "PASS", "generated_at": fresh_ts}))

    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row(current_health="red"))
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    result = mod.verify("R-Sync-7b", "scheduled_fixtures", path=target)
    assert result.valid is False
    assert any("FAIL" in r for r in result.reasons)


def test_verify_valid_fresh_matching_attestation(tmp_path, monkeypatch):
    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row())
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    target = tmp_path / "ok.json"
    mod.attest("R-Sync-7b", "scheduled_fixtures", path=target)

    result = mod.verify("R-Sync-7b", "scheduled_fixtures", path=target)
    assert result.valid is True


# ── CLI ───────────────────────────────────────────────────────────────────────

def test_cli_status_exit_code_matches_verdict(monkeypatch, capsys):
    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row(current_health="red"))
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))

    import sys
    monkeypatch.setattr(sys, "argv", ["migration_gate", "status", "R-Sync-7b"])
    code = mod._cli()
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out


def test_cli_attest_exit_zero(monkeypatch, tmp_path, capsys):
    import database.queries as queries
    monkeypatch.setattr(queries, "get_migration_gate_status_row", lambda gk, e: _view_row())
    import supabase_client as sb
    monkeypatch.setattr(sb, "load_config", lambda default: dict(default))
    monkeypatch.setattr(mod, "attestation_path", lambda gate_key: tmp_path / f"{gate_key}.json")

    import sys
    monkeypatch.setattr(sys, "argv", ["migration_gate", "attest", "R-Sync-7b"])
    code = mod._cli()
    assert code == 0
