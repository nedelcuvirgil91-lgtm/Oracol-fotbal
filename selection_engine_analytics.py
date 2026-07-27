"""
================================================================================
FOOTBALL ORACLE — Advanced Selection Engine Analytics (ADR-041 Faza 2, Sprint 1.1 #6)
================================================================================
Module: selection_engine_analytics.py

NU modifică formula Selection Engine (`provider_selector.py`, ADR-034,
neatinsă) — strict analitică READ-ONLY peste date deja existente:
`shadow_provider_recommendations` (ADR-034 PR5, `shadow_recorder.py`) +
`provider_call_log` (Sprint 1.1 #2, `provider_health_score.py`).

Răspunde la o întrebare pe care raportul de bază
(`shadow_selection_report.py`) nu o poate răspunde singur: când Selection
Engine ar fi recomandat un provider diferit (`decision_changed=True`),
chiar susțin datele REALE de sănătate (Health Score 24h, din
`provider_call_log`) acea decizie, sau e doar teoretică (calculată din
scoruri, nicio confirmare independentă)?

Reutilizează, nu duplică: `shadow_recorder.get_shadow_rows()` pentru
observații, `provider_health_score.get_health_score_24h()` pentru starea
REALĂ curentă. `compute_decision_validations()`/`summarize_validations()`
sunt funcții pure — primesc date deja citite, nu citesc nimic singure
(Regula de Aur #4/#5, ADR-034).
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from provider_health_score import HealthScoreWindow


@dataclass(frozen=True)
class DecisionValidation:
    league: str
    data_type: str
    current_provider: str
    recommended_provider: str
    current_success_rate_24h: float | None
    recommended_success_rate_24h: float | None
    # True: recommended chiar are success_rate STRICT mai bun (decizia se
    # confirmă independent) — False: mai slab/egal (decizia se contrazice)
    # — None: date insuficiente pentru comparație (niciun trafic recent
    # pentru unul dintre provideri), niciodată aproximat (Regula #8).
    validated: bool | None


def compute_decision_validations(
    shadow_rows: list[dict], health_by_provider: dict[str, HealthScoreWindow],
) -> list[DecisionValidation]:
    """Funcție pură — pentru fiecare rând shadow cu `decision_changed=True`
    și un `recommended_provider` real, compară Health Score 24h REAL al
    providerului curent vs. al celui recomandat."""
    results: list[DecisionValidation] = []
    for row in shadow_rows:
        if not row.get("decision_changed") or not row.get("recommended_provider"):
            continue
        current_id = row.get("current_provider")
        recommended_id = row.get("recommended_provider")

        current_health = health_by_provider.get(current_id)
        recommended_health = health_by_provider.get(recommended_id)
        current_rate = current_health.success_rate if current_health is not None else None
        recommended_rate = recommended_health.success_rate if recommended_health is not None else None

        validated = None
        if current_rate is not None and recommended_rate is not None:
            validated = recommended_rate > current_rate

        results.append(DecisionValidation(
            league=row.get("league", ""), data_type=row.get("data_type", ""),
            current_provider=current_id, recommended_provider=recommended_id,
            current_success_rate_24h=current_rate, recommended_success_rate_24h=recommended_rate,
            validated=validated,
        ))
    return results


@dataclass(frozen=True)
class ValidationSummary:
    total_decisions: int
    validated_count: int      # recommended chiar mai bun (confirmat independent)
    contradicted_count: int   # recommended MAI SLAB/egal decat current
    unknown_count: int        # date insuficiente pentru comparatie


def summarize_validations(validations: list[DecisionValidation]) -> ValidationSummary:
    """Funcție pură — agregare simplă peste `compute_decision_validations()`."""
    validated = sum(1 for v in validations if v.validated is True)
    contradicted = sum(1 for v in validations if v.validated is False)
    unknown = sum(1 for v in validations if v.validated is None)
    return ValidationSummary(
        total_decisions=len(validations), validated_count=validated,
        contradicted_count=contradicted, unknown_count=unknown,
    )


def get_decision_validations(
    shadow_rows: list[dict] | None = None,
    health_score_fn: Callable[[str], HealthScoreWindow] | None = None,
) -> list[DecisionValidation]:
    """Accesor de conveniență — rezolvă dependințele implicite (shadow rows
    + Health Score per provider implicat), apoi deleagă la funcția pură.
    Import leneș, degradare grațioasă (consistent cu restul modulelor
    Sprint 1.1) — nicio excepție propagată dacă Supabase e indisponibil."""
    if shadow_rows is None:
        import shadow_recorder
        shadow_rows = shadow_recorder.get_shadow_rows()
    if health_score_fn is None:
        from provider_health_score import get_health_score_24h
        health_score_fn = get_health_score_24h

    provider_ids: set[str] = set()
    for row in shadow_rows:
        if not row.get("decision_changed") or not row.get("recommended_provider"):
            continue
        if row.get("current_provider"):
            provider_ids.add(row["current_provider"])
        provider_ids.add(row["recommended_provider"])

    health_by_provider = {pid: health_score_fn(pid) for pid in provider_ids}
    return compute_decision_validations(shadow_rows, health_by_provider)


def build_validation_report(validations: list[DecisionValidation]) -> str:
    """Text simplu, tiparul deja folosit de `shadow_selection_report.py` —
    funcție pură, aceleași input-uri produc mereu același text."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("Selection Engine — Validare deciziilor prin Health Score real (Sprint 1.1 #6)")
    lines.append("=" * 78)

    summary = summarize_validations(validations)
    if summary.total_decisions == 0:
        lines.append("\nNicio decizie 'diferită' de validat încă (necesită date shadow + trafic real).")
        return "\n".join(lines)

    lines.append(f"\nDecizii diferite analizate: {summary.total_decisions}")
    lines.append(f"  Confirmate de Health Score 24h real:  {summary.validated_count}")
    lines.append(f"  Contrazise de Health Score 24h real:  {summary.contradicted_count}")
    lines.append(f"  Date insuficiente (fără trafic recent): {summary.unknown_count}")

    lines.append("\n--- Detaliu ---")
    for v in validations:
        icon = "✅" if v.validated is True else ("❌" if v.validated is False else "❓")
        cur = f"{v.current_success_rate_24h * 100:.1f}%" if v.current_success_rate_24h is not None else "n/a"
        rec = f"{v.recommended_success_rate_24h * 100:.1f}%" if v.recommended_success_rate_24h is not None else "n/a"
        lines.append(
            f"  {icon} [{v.league}/{v.data_type}] {v.current_provider} ({cur}) -> "
            f"{v.recommended_provider} ({rec})"
        )

    return "\n".join(lines)


def main() -> None:
    validations = get_decision_validations()
    print(build_validation_report(validations))


if __name__ == "__main__":
    main()
