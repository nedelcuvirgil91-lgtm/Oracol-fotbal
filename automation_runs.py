"""
================================================================================
FOOTBALL ORACLE — automation_runs.py (ADR-026)
================================================================================
Substratul comun de raportare pentru orice proces autonom — generalizarea
tiparului deja dovedit `sync_status` la scara întregii serii vNext.

Implementează exact contractul înghețat prin ADR-026:
docs/00_GOVERNANCE/ADR-026-automation-runs-decision-feed.md

Două state machine-uri, independente, legate prin run_id:
  - automation_runs: execuție (queued -> running -> completed|failed|skipped)
  - decision_feed:   decizie T3a/T3b (proposed -> pending -> approved|rejected|
                      expired|withdrawn; approved -> committed|commit_failed|
                      orphaned; T3b: flagged -> acknowledged -> resolved)

Regula de escaladare la incertitudine (ADR-026 §Tiering) și regula de
rollback ca precondiție structurală (Blueprint, principiul #9) sunt
responsabilitatea apelantului (fiecare ADR producător) — acest modul impune
doar contractul mecanic (stări, tranziții, idempotency), nu logica de
clasificare pe tier.

Niciun apel din acest modul nu atinge vreodată stare canonică de business
(match_history, model_champions etc.) — exclusiv jurnal + poartă de aprobare,
per Ownership din ADR-026.
================================================================================
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from database.queries import get_client

logger = logging.getLogger("FootballOracle.AutomationRuns")

_OPEN_RUN_STATUSES = ("queued", "running")
_OPEN_DECISION_STATUSES = ("proposed", "pending", "approved")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ════════════════════════════════════════════════════════════════════════════
# automation_runs — execuție
# ════════════════════════════════════════════════════════════════════════════

def write_run(
    producer: str,
    process_type: str,
    tier: str,
    target_key: str | None = None,
) -> int | None:
    """
    Creează o rulare nouă (status='queued'), sau reutilizează una existentă
    dacă un run e deja queued/running pentru aceeași (producer, process_type,
    target_key) — regula de idempotency „reuse" din ADR-026 §Idempotency.

    Returnează run_id-ul (nou sau reutilizat), sau None la eroare de client.
    """
    client = get_client()
    if client is None:
        logger.error("[AutomationRuns] Supabase indisponibil — write_run refuzat")
        return None

    if target_key:
        try:
            existing = (
                client.table("automation_runs")
                .select("id")
                .eq("producer", producer)
                .eq("process_type", process_type)
                .eq("target_key", target_key)
                .in_("status", list(_OPEN_RUN_STATUSES))
                .limit(1)
                .execute()
            )
            if existing.data:
                run_id = existing.data[0]["id"]
                logger.info(
                    "[AutomationRuns] rulare deja in curs pentru %s/%s/%s (run_id=%s) — reutilizata, nicio rulare noua",
                    producer, process_type, target_key, run_id,
                )
                return run_id
        except Exception as exc:
            logger.error("[AutomationRuns] verificare idempotency esuata: %s", exc)
            return None

    try:
        res = (
            client.table("automation_runs")
            .insert({
                "producer":     producer,
                "process_type": process_type,
                "tier":         tier,
                "target_key":   target_key,
                "status":       "queued",
            })
            .execute()
        )
        return res.data[0]["id"] if res.data else None
    except Exception as exc:
        logger.error("[AutomationRuns] write_run esuat: %s", exc)
        return None


def start_run(run_id: int) -> bool:
    """queued -> running."""
    return _transition_run(run_id, {"status": "running", "started_at": _now_iso()})


def complete_run(run_id: int, summary: dict[str, Any] | None = None) -> bool:
    """running -> completed."""
    payload: dict[str, Any] = {"status": "completed", "completed_at": _now_iso()}
    if summary is not None:
        payload["summary"] = summary
    return _transition_run(run_id, payload)


def fail_run(run_id: int, error_detail: str) -> bool:
    """running -> failed."""
    return _transition_run(run_id, {
        "status": "failed", "completed_at": _now_iso(), "error_detail": error_detail,
    })


def skip_run(run_id: int, skip_reason: str) -> bool:
    """queued -> skipped. Rezultat legitim (precondiții neîndeplinite sau
    stare identică, nimic de raportat), nu o eroare."""
    return _transition_run(run_id, {
        "status": "skipped", "completed_at": _now_iso(), "skip_reason": skip_reason,
    })


def _transition_run(run_id: int, payload: dict[str, Any]) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("automation_runs").update(payload).eq("id", run_id).execute()
        return True
    except Exception as exc:
        logger.error("[AutomationRuns] tranzitie run_id=%s esuata: %s", run_id, exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# decision_feed — decizie (T3a / T3b)
# ════════════════════════════════════════════════════════════════════════════

def propose_decision(
    run_id: int,
    tier: str,
    rollback_plan: str | None = None,
    evidence: dict[str, Any] | None = None,
    correction_method: str | None = None,
    ttl_hours: float | None = None,
) -> int | None:
    """
    Creează o decizie nouă (status='proposed'), sau actualizează dovada unei
    decizii deja deschise pentru aceeași cheie (regula de idempotency „new
    run, decizie reutilizată" din ADR-026 §Idempotency).

    tier='T3a' necesită rollback_plan (impus și la nivel de schema — vezi
    migrarea 011, constrângerea decision_feed_t3a_requires_rollback).
    """
    if tier == "T3a" and not rollback_plan:
        raise ValueError("propose_decision: T3a necesita rollback_plan (precondiție structurală)")

    client = get_client()
    if client is None:
        logger.error("[AutomationRuns] Supabase indisponibil — propose_decision refuzat")
        return None

    try:
        run = client.table("automation_runs").select("target_key").eq("id", run_id).limit(1).execute()
        target_key = run.data[0]["target_key"] if run.data else None
    except Exception as exc:
        logger.error("[AutomationRuns] citire target_key pentru run_id=%s esuata: %s", run_id, exc)
        target_key = None

    if target_key:
        try:
            sibling_runs = (
                client.table("automation_runs")
                .select("id")
                .eq("target_key", target_key)
                .execute()
            )
            sibling_run_ids = [r["id"] for r in (sibling_runs.data or [])]
            existing = (
                client.table("decision_feed")
                .select("id")
                .in_("run_id", sibling_run_ids)
                .in_("status", list(_OPEN_DECISION_STATUSES))
                .limit(1)
                .execute()
                if sibling_run_ids else None
            )
            if existing and existing.data:
                decision_id = existing.data[0]["id"]
                update_payload: dict[str, Any] = {}
                if evidence is not None:
                    update_payload["evidence"] = evidence
                if update_payload:
                    client.table("decision_feed").update(update_payload).eq("id", decision_id).execute()
                logger.info(
                    "[AutomationRuns] decizie deschisa deja existenta pentru target_key=%s (decision_id=%s) — actualizata, nu duplicata",
                    target_key, decision_id,
                )
                return decision_id
        except Exception as exc:
            logger.error("[AutomationRuns] verificare idempotency decizie esuata: %s", exc)
            return None

    ttl_at = None
    if ttl_hours is not None:
        ttl_at = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()

    try:
        res = (
            client.table("decision_feed")
            .insert({
                "run_id":            run_id,
                "tier":              tier,
                "status":            "proposed",
                "evidence":          evidence,
                "rollback_plan":     rollback_plan,
                "correction_method": correction_method,
                "ttl_at":            ttl_at,
            })
            .execute()
        )
        return res.data[0]["id"] if res.data else None
    except Exception as exc:
        logger.error("[AutomationRuns] propose_decision esuata: %s", exc)
        return None


def surface_decision(decision_id: int) -> bool:
    """proposed -> pending (devine vizibil in Decision Feed)."""
    return _transition_decision(decision_id, {"status": "pending"})


def approve_decision(decision_id: int, resolved_by: str) -> bool:
    """pending -> approved. Exclusiv acțiune umană."""
    return _transition_decision(decision_id, {
        "status": "approved", "resolved_by": resolved_by, "resolved_at": _now_iso(),
    })


def reject_decision(decision_id: int, resolved_by: str) -> bool:
    """pending -> rejected. Exclusiv acțiune umană, terminal."""
    return _transition_decision(decision_id, {
        "status": "rejected", "resolved_by": resolved_by, "resolved_at": _now_iso(),
    })


def commit_decision(decision_id: int) -> bool:
    """approved -> committed. Exclusiv apelat de subsistemul proprietar,
    după scriere reușită pe stare canonică. Terminal, imuabil."""
    return _transition_decision(decision_id, {"status": "committed"})


def fail_decision_commit(decision_id: int, error_detail: str) -> bool:
    """approved -> commit_failed. Re-intră obligatoriu în vizibilitate activă
    — nu se pierde silențios."""
    return _transition_decision(decision_id, {
        "status": "commit_failed", "commit_error": error_detail,
    })


def withdraw_decision(decision_id: int, reason: str) -> bool:
    """proposed/pending -> withdrawn. Procesul originator, dacă condiția
    s-a rezolvat singură."""
    return _transition_decision(decision_id, {
        "status": "withdrawn", "commit_error": reason,
    })


def acknowledge_signal(decision_id: int, resolved_by: str) -> bool:
    """T3b: flagged -> acknowledged."""
    return _transition_decision(decision_id, {
        "status": "acknowledged", "resolved_by": resolved_by,
    })


def resolve_signal(decision_id: int) -> bool:
    """T3b: acknowledged -> resolved."""
    return _transition_decision(decision_id, {"status": "resolved", "resolved_at": _now_iso()})


def _transition_decision(decision_id: int, payload: dict[str, Any]) -> bool:
    client = get_client()
    if client is None:
        return False
    try:
        client.table("decision_feed").update(payload).eq("id", decision_id).execute()
        return True
    except Exception as exc:
        logger.error("[AutomationRuns] tranzitie decision_id=%s esuata: %s", decision_id, exc)
        return False


# ════════════════════════════════════════════════════════════════════════════
# Staleness sweep (ADR-026 §Staleness Policy)
# ════════════════════════════════════════════════════════════════════════════

def sweep_stale_decisions() -> tuple[int, int]:
    """
    Tranziții automate de staleness — NICIODATĂ echivalente cu o aprobare
    sau respingere tacită (regula North Star #6):
      - pending, ttl_at depășit  -> expired
      - approved, ttl_at depășit -> orphaned (producer failure — vezi
        ADR-026 §State Machines, extensia Producer Failure)

    Returnează (nr_expirate, nr_orfanizate).
    """
    client = get_client()
    if client is None:
        return (0, 0)

    now = _now_iso()
    expired = orphaned = 0
    try:
        res = (
            client.table("decision_feed")
            .update({"status": "expired"})
            .eq("status", "pending")
            .lt("ttl_at", now)
            .execute()
        )
        expired = len(res.data or [])
    except Exception as exc:
        logger.error("[AutomationRuns] sweep expired esuat: %s", exc)

    try:
        res = (
            client.table("decision_feed")
            .update({"status": "orphaned"})
            .eq("status", "approved")
            .lt("ttl_at", now)
            .execute()
        )
        orphaned = len(res.data or [])
    except Exception as exc:
        logger.error("[AutomationRuns] sweep orphaned esuat: %s", exc)

    return (expired, orphaned)


# ════════════════════════════════════════════════════════════════════════════
# Citire — Activity Log / Decision Feed (L7, strict read-only)
# ════════════════════════════════════════════════════════════════════════════

def list_recent_runs(limit: int = 50) -> list[dict[str, Any]]:
    """Activity Log — tot ce sistemul a făcut singur, cele mai recente
    rulări, indiferent de tier/status. Pasiv, interogabil, nu cere nimic."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("automation_runs")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[AutomationRuns] list_recent_runs esuat: %s", exc)
        return []


def list_pending_decisions() -> list[dict[str, Any]]:
    """Decision Feed — exclusiv elementele care chiar așteaptă o decizie
    umană (status='pending'). Gol implicit, per design."""
    client = get_client()
    if client is None:
        return []
    try:
        res = (
            client.table("decision_feed")
            .select("*")
            .eq("status", "pending")
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error("[AutomationRuns] list_pending_decisions esuat: %s", exc)
        return []
