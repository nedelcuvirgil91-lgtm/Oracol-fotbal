"""
================================================================================
FOOTBALL ORACLE — Shadow Recorder (ADR-034, PR5 — infrastructură)
================================================================================
Module: shadow_recorder.py

Singurul fișier din Selection Engine (ADR-034, strat 5/6) care cunoaște
Supabase — exact tiparul de izolare deja folosit la Health Monitor (PR4,
`provider_metrics_source_supabase.py`). `provider_selector.py` (domeniu,
pur) nu importă niciodată acest modul — direcția e strict inversă: hook-ul
din oracle_api.py apelează `provider_selector.recommend_provider()` (pur),
apoi predă rezultatul aici, DOAR dacă trebuie persistat.

`shadow_run_id` (UUID) și `observed_at` (timestamp, implicit `now()` în
schema SQL) sunt generate/atribuite EXCLUSIV aici, niciodată în
provider_selector.py — ProviderRecommendation rămâne atemporal prin
construcție (Regula de Aur #4).

Best-effort: orice eșec (Supabase indisponibil, eroare de rețea) e prins
aici, niciodată propagat către oracle_api.py — degradare grațioasă,
consistentă cu restul proiectului (record_provider_call/get_provider_metrics
în supabase_client.py, provider_metrics_source_supabase.py la PR4).
================================================================================
"""
from __future__ import annotations

import logging
import uuid

from provider_selector import ALGORITHM_VERSION, ProviderRecommendation, ShadowObservation

logger = logging.getLogger("FootballOracle.ShadowRecorder")

_TABLE = "shadow_provider_recommendations"


def new_shadow_run_id() -> uuid.UUID:
    """Un singur shadow_run_id per execuție (ex. per rulare a
    get_matches_for_week()) — apelat o singură dată de hook-ul din
    oracle_api.py, NICIODATĂ de provider_selector.py."""
    return uuid.uuid4()


def record_shadow_recommendation(
    recommendation: ProviderRecommendation, shadow_run_id: uuid.UUID,
    algorithm_version: int = ALGORITHM_VERSION,
) -> bool:
    try:
        import supabase_client as _sb
        client = _sb.get_client()
        if client is None:
            return False

        component_deltas = (
            dict(recommendation.reason.component_deltas) if recommendation.reason is not None else None
        )
        client.table(_TABLE).insert({
            "shadow_run_id": str(shadow_run_id),
            "algorithm_version": algorithm_version,
            "league": recommendation.league,
            "data_type": recommendation.data_type.value,
            "current_provider": recommendation.current_provider,
            "current_score": recommendation.current_score.total if recommendation.current_score else None,
            "recommended_provider": recommendation.recommended_provider,
            "recommended_score": recommendation.recommended_score.total if recommendation.recommended_score else None,
            "decision_changed": recommendation.decision_changed,
            "component_deltas": component_deltas,
        }).execute()
        return True
    except Exception as exc:
        logger.warning("[ShadowRecorder] record_shadow_recommendation eșuat: %s", exc)
        return False


def get_shadow_observations(shadow_run_id: uuid.UUID | None = None) -> list[ShadowObservation]:
    """Citește rândurile brute și le convertește în obiecte de domeniu
    (ShadowObservation) — conversia DB -> domeniu se face AICI, niciodată în
    provider_selector.py."""
    try:
        import supabase_client as _sb
        client = _sb.get_client()
        if client is None:
            return []
        query = client.table(_TABLE).select("*")
        if shadow_run_id is not None:
            query = query.eq("shadow_run_id", str(shadow_run_id))
        res = query.execute()
        rows = res.data or []
    except Exception as exc:
        logger.warning("[ShadowRecorder] get_shadow_observations eșuat: %s", exc)
        return []

    return [
        ShadowObservation(
            decision_changed=bool(row.get("decision_changed")),
            recommended_provider=row.get("recommended_provider"),
            current_total=row.get("current_score"),
            recommended_total=row.get("recommended_score"),
        )
        for row in rows
    ]
