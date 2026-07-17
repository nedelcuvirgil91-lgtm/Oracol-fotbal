"""
================================================================================
FOOTBALL ORACLE — Learning Core: Promotion Service (Pasul 5, Implementation
Contract) — vezi ADR-019 și docs/04_LEARNING_CORE/PROMOTION_*.md
================================================================================
Module: learning_core/promotion_service.py

Owner exclusiv al evenimentului de domeniu „Promote Challenger" — vezi
`docs/04_LEARNING_CORE/PROMOTION_CONTRACT.md`. Un singur use-case, un
singur punct de intrare public (`promote_challenger()`). NU e un Learning
Orchestrator general — decizie explicită YAGNI (Chief Architect Review,
Pasul 4.5) — nu capătă alte responsabilități.

── Promotion execută, nu decide ────────────────────────────────────────────
Lanțul de decizie (Comparison → Shadow Evaluation → verdict
`candidate_for_promotion`, `challenger_evaluations`, ADR-018, imuabil) e
complet încheiat înainte ca acest modul să fie invocat. Acest modul NU
importă `shadow_testing`, NU rulează teste statistice, NU recalculează
`delta_brier`/`delta_logloss`/`delta_accuracy` — verifică EXCLUSIV
precondiții structurale (există/valid), niciodată o a doua opinie asupra
calității modelului.

── Diviziunea Python vs. tranzacție Postgres ───────────────────────────────
Precondițiile (citire Challenger, citire verdict, validare artefact) rulează
aici, în Python, ÎNAINTE de orice scriere — la primul eșec, zero apel RPC,
zero scriere. Cele două efecte cuplate (model_champions + challengers) sunt
aplicate de UN singur apel RPC (`promote_challenger`, migration 005) —
o singură tranzacție Postgres, fie ambele efecte se aplică, fie niciunul.
Vezi `docs/04_LEARNING_CORE/ATOMICITY_CONTRACT.md`.

Complet izolat: niciun alt fișier din proiect nu importă acest modul —
zero apelanți reali, la fel ca Pasul 1/2/4. Nu e wired în
`sync/run_daily.py`, `oracle_engine.py`, sau oriunde altundeva — apelat
exclusiv manual (CLI/UI viitoare, nescrise încă).
================================================================================
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("FootballOracle.LearningCore.PromotionService")


@dataclass
class PromotionResult:
    status: str  # "promoted" | "already_active" | "rejected"
    training_run_id: str
    reason: str | None = None


def promote_challenger(
    training_run_id: str, algorithm_family: str, league_scope: str, promoted_by: str,
) -> PromotionResult:
    """Execută evenimentul „Promote Challenger" pentru `training_run_id`,
    dacă și numai dacă toate precondițiile structurale sunt satisfăcute.
    Niciodată nu ridică excepție către apelant — orice eșec (precondiție
    nesatisfăcută, Supabase indisponibil, eroare neașteptată) se întoarce
    ca `PromotionResult(status="rejected", reason=...)`."""
    try:
        from learning_core import challenger_manager

        challenger = challenger_manager.get_challenger(training_run_id)
        if challenger is None:
            return PromotionResult(
                status="rejected", training_run_id=training_run_id,
                reason=f"niciun Challenger găsit pentru training_run_id={training_run_id!r}",
            )

        if challenger["algorithm_family"] != algorithm_family or challenger["league_scope"] != league_scope:
            return PromotionResult(
                status="rejected", training_run_id=training_run_id,
                reason=(
                    f"training_run_id={training_run_id!r} aparține de "
                    f"({challenger['algorithm_family']!r}, {challenger['league_scope']!r}), "
                    f"nu de ({algorithm_family!r}, {league_scope!r}) — verificați apelul"
                ),
            )

        if challenger["state"] != "SUCCEEDED":
            return PromotionResult(
                status="rejected", training_run_id=training_run_id,
                reason=f"Challenger nu este în starea SUCCEEDED (stare curentă: {challenger['state']!r})",
            )

        import supabase_client as sb

        latest_evaluation = sb.get_latest_challenger_evaluation(training_run_id)
        verdict = latest_evaluation.get("verdict") if latest_evaluation else None
        if verdict != "candidate_for_promotion":
            return PromotionResult(
                status="rejected", training_run_id=training_run_id,
                reason=f"niciun verdict 'candidate_for_promotion' înregistrat (găsit: {verdict!r})",
            )

        _artifact_error = _validate_artifact(training_run_id)
        if _artifact_error is not None:
            return PromotionResult(status="rejected", training_run_id=training_run_id, reason=_artifact_error)

        try:
            rpc_status = sb.rpc_promote_challenger(training_run_id, promoted_by)
        except Exception as exc:
            return PromotionResult(status="rejected", training_run_id=training_run_id, reason=str(exc))

        if rpc_status not in ("promoted", "already_active"):
            return PromotionResult(
                status="rejected", training_run_id=training_run_id,
                reason=f"răspuns neașteptat de la promote_challenger: {rpc_status!r}",
            )

        return PromotionResult(status=rpc_status, training_run_id=training_run_id)
    except Exception as exc:
        logger.warning("[PromotionService] promote_challenger eșuat pentru %s: %s", training_run_id, exc)
        return PromotionResult(status="rejected", training_run_id=training_run_id, reason=str(exc))


def _validate_artifact(training_run_id: str) -> str | None:
    """Re-validare funcțională a artefactului — nu doar „fișierul există",
    ci un test real de inferență (predict_proba pe un rând-sondă). None
    dacă validarea reușește, mesajul de eroare altfel."""
    try:
        from learning_core import model_artifact_storage

        model = model_artifact_storage.load_model_artifact(training_run_id)
        if model is None:
            return "artefactul modelului nu a putut fi încărcat (lipsă, corupt, sau Supabase indisponibil)"

        import numpy as np
        from ml_predictor import FEATURE_COLUMNS

        probe = np.zeros((1, len(FEATURE_COLUMNS)))
        model.predict_proba(probe)
        return None
    except Exception as exc:
        return f"artefactul nu produce predicții valide: {exc}"
