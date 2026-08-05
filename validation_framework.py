"""
================================================================================
FOOTBALL ORACLE — Validation Framework (ADR-052)
================================================================================
Module: validation_framework.py

Colectare automată, per meci, a ieșirilor disponibile ale celor trei
motoare (Oracle/ML/Blend) — infrastructura de colectare cerută de ADR-052
pentru perioada de validare care urmează integrării complete Oracle-ML-Blend.

Scop exclusiv: colectare și organizare a datelor pentru analize ulterioare
(zilnice/săptămânale/lunare). Acest modul NU ia decizii, NU optimizează
modele, NU promovează modele — vezi ADR-052 §2.3.

Rezultatul real al meciului NU e stocat aici — rămâne exclusiv în
match_history.actual_result (owner unic, sync_results.py, Canonical
Feature Ownership, ADR-036/D3.5). Orice analiză care are nevoie de
rezultatul real face JOIN pe fixture_id între engine_comparison_snapshots
și match_history — nu se duplică scrierea.

Fail-safe prin construcție: orice eșec (Supabase indisponibil, eroare
neprevăzută) e prins aici, niciodată propagat — zero impact asupra
predicției servite (Regula #8 CLAUDE.md).
================================================================================
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from oracle_engine import MatchPrediction

logger = logging.getLogger("FootballOracle.ValidationFramework")


def _build_snapshot_row(pred: "MatchPrediction") -> dict:
    """Extrage, din `pred` deja construit complet, exact ce e nevoie pentru
    un rând `engine_comparison_snapshots`. Oracle e întotdeauna prezent
    (motorul principal, servește mereu). ML/Blend sunt prezente doar dacă
    erau deja disponibile pe `pred` la momentul apelului (flag-urile lor
    proprii, independente de acest modul)."""
    mp = pred.ml_engine_prediction
    bp = pred.blend_engine_prediction

    ml_available = bool(mp and mp.get("available"))
    blend_available = bp is not None

    return {
        "fixture_id":       pred.fixture_id,
        "league":           pred.league,
        "kickoff_date":     pred.kickoff_date,
        "oracle_prob_home": pred.prob_home_win,
        "oracle_prob_draw": pred.prob_draw,
        "oracle_prob_away": pred.prob_away_win,
        "ml_available":     ml_available,
        "ml_prob_home":     mp["prob_home"] if ml_available else None,
        "ml_prob_draw":     mp["prob_draw"] if ml_available else None,
        "ml_prob_away":     mp["prob_away"] if ml_available else None,
        "blend_available":  blend_available,
        "blend_prob_home":  bp["prob_home"] if blend_available else None,
        "blend_prob_draw":  bp["prob_draw"] if blend_available else None,
        "blend_prob_away":  bp["prob_away"] if blend_available else None,
    }


def save_snapshot(pred: "MatchPrediction") -> bool:
    """Persistă, pentru un singur meci, ieșirile disponibile ale celor trei
    motoare. Idempotent per fixture_id (upsert, vezi migrația 006) — o
    reanalizare a aceluiași meci actualizează rândul, nu creează duplicate.

    Întoarce False la orice eșec (Supabase indisponibil, scriere eșuată,
    eroare neprevăzută) — niciodată excepție propagată către apelant."""
    try:
        row = _build_snapshot_row(pred)
    except Exception as exc:
        logger.debug("[ValidationFramework] construire rând eșuată: %s", exc)
        return False

    try:
        import supabase_client as sb
        return sb.save_engine_comparison_snapshot(row)
    except Exception as exc:
        logger.debug("[ValidationFramework] save_snapshot failed: %s", exc)
        return False
