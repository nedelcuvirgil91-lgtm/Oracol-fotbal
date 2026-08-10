"""
================================================================================
FOOTBALL ORACLE — Equivalence Governance (ADR-040, G2)
================================================================================
Module: equivalence_governance.py

Generic, entity-agnostic — NU cunoaște `scheduled_fixtures` sau orice altă
entitate specifică. Primește un raport deja calculat de un evaluator
entity-specific (ex. `scheduled_fixtures_shadow.py`) și face DOAR două
lucruri, ambele reutilizabile pentru orice `gate_key`/`entity` viitor
(match_stats, team_stats, injuries, lineups, weather, odds, feature
tables ML — ADR-040, principiul 7, „Future Extensions"):

  1. Clasifică starea evaluării — Nivel A (validitate individuală,
     `insufficient_data`) + scor MIN (Nivel B se calculează separat, în
     `migration_gate_status`, view Supabase, G3 — nu aici).
  2. Persistă, ÎNTOTDEAUNA (ADR-040, principiul 5, G2 — niciun return
     anticipat care sare scrierea), prin `database.queries` — zero SQL în
     acest modul.

Raportul e un obiect generic (orice tip cu atributele folosite mai jos —
duck typing deliberat, nu o clasă de bază impusă) — un evaluator viitor
pentru altă entitate nu trebuie să moștenească nimic de aici, doar să
producă un obiect cu aceleași nume de câmpuri.
================================================================================
"""
from __future__ import annotations

MIN_LIVE_FOR_EVALUATION = 30  # Nivel A — mirror direct champion_health_evaluations.MIN_MATCHES_FOR_HEALTH


def classify_evaluation(
    report, min_live_for_evaluation: int = MIN_LIVE_FOR_EVALUATION,
) -> tuple[float | None, str]:
    """
    Întoarce (equivalence_score, equivalence_state).

    Nivel A: `live_count < min_live_for_evaluation` -> insufficient_data,
    scor NULL (Regula #8 — nu se aproximează o dovadă insuficientă).

    `broken`: `scheduled_count == 0` cu `live_count > 0` — semnal structural
    (ADR-040, principiul 4), scor NULL.

    Altfel: scor MIN (niciodată medie — ADR-040, principiul 3) peste
    coverage/field_purity/id_purity, apoi RED (<1.0) / YELLOW (==1.0 ȘI
    accepted_exception_count>0) / GREEN (==1.0 ȘI accepted_exception_count==0).

    [REPARAT — 2026-08-10, incident live confirmat: cu mai multe diferențe
    de câmp/ID decât meciuri potrivite (`matched` mic, diferențe multe pe
    restul), `field_purity`/`id_purity` ieșeau negative — `score` (min
    peste toate trei) ieșea sub 0, respins de constraint-ul CHECK
    `equivalence_evaluations_score_range` la scriere, deci evaluarea
    respectivă nu se mai salva DELOC. `score` e o proporție — clamp la
    0.0 minim, ca `coverage` (deja garantat în [0,1] prin construcție).]
    """
    if report.live_count < min_live_for_evaluation:
        return None, "insufficient_data"

    if report.scheduled_count == 0 and report.live_count > 0:
        return None, "broken"

    denom = max(report.matched, 1)
    coverage = report.matched / max(report.live_count, report.scheduled_count, 1)
    unaccepted_field_diff = max(report.field_difference_count - report.accepted_exception_count, 0)
    field_purity = max(1 - (unaccepted_field_diff / denom), 0.0)
    id_purity = max(1 - (report.provider_id_difference_count / denom), 0.0)
    score = min(coverage, field_purity, id_purity)

    if score < 1.0:
        return score, "red"
    if report.accepted_exception_count > 0:
        return score, "yellow"
    return score, "green"


def persist_equivalence_evaluation(
    gate_key: str,
    entity: str,
    report,
    window_from: str,
    window_to: str,
    run_id: int | None = None,
    state_override: str | None = None,
    min_live_for_evaluation: int = MIN_LIVE_FOR_EVALUATION,
) -> bool:
    """
    Persistă ÎNTOTDEAUNA — inclusiv insufficient_data/broken/red/yellow/green,
    fără excepție (ADR-040, principiul 5, decizie explicită proprietar
    produs, G2: „istoricul complet e mai valoros decât un istoric curat").

    `state_override`: permite apelantului să forțeze `broken` când raportul
    nu poate fi produs deloc (evaluatorul însuși a eșuat structural) — vezi
    hook-ul din `oracle_api.py`, care construiește un raport minimal în
    acest caz (zero aproximare a numerelor reale — doar ce se știe sigur).
    """
    from database.queries import upsert_equivalence_evaluation

    if state_override is not None:
        score, state = None, state_override
    else:
        score, state = classify_evaluation(report, min_live_for_evaluation)

    return upsert_equivalence_evaluation(
        gate_key=gate_key,
        entity=entity,
        window_from=window_from,
        window_to=window_to,
        live_count=report.live_count,
        scheduled_count=report.scheduled_count,
        matched_count=report.matched,
        missing_scheduled_count=report.missing_scheduled_count,
        missing_live_count=report.missing_live_count,
        duplicate_key_count=getattr(report, "duplicate_key_count", 0),
        field_difference_count=report.field_difference_count,
        provider_id_difference_count=report.provider_id_difference_count,
        accepted_exception_count=report.accepted_exception_count,
        equivalence_score=score,
        equivalence_state=state,
        provider_breakdown=report.provider_breakdown,
        root_cause_summary=report.root_cause_summary,
        sample_missing_scheduled=report.missing_scheduled,
        sample_missing_live=report.missing_live,
        sample_field_differences=report.field_differences,
        sample_provider_id_diffs=report.provider_id_differences,
        run_id=run_id,
    )
