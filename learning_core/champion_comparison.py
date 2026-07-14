"""
================================================================================
FOOTBALL ORACLE — Learning Core: Comparare model nou vs. Campion activ (v0.1)
================================================================================
Module: learning_core/champion_comparison.py

Compară metricile walk-forward (accuracy, log_loss, brier_score) ale unei
rulări de antrenare noi cu cele ale campionului activ curent — vezi
docs/00_GOVERNANCE/ADR-015-training-run-history-and-champion-comparison.md.

Pur informativ — NU decide, NU promovează, NU face rollback. Rezultatul e
un raport structurat, citit de un log sau de un Promotion Engine viitor
(neimplementat încă, per CLAUDE.md — "auto_promotion_enabled necesită ADR
dedicat înainte de activare"). Nu modifică nimic în producție.

Dacă nu există încă un campion promovat pentru (algorithm_family,
league_scope), situația e raportată explicit ca atare — nu se aproximează
și nu se tratează ca eroare (Regula #8).
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field

import supabase_client as sb

# Metrici unde o valoare MAI MICĂ e mai bună — restul (ex. accuracy) sunt
# "mai mare e mai bine". Listă explicită, nu presupunere per-nume generică.
_LOWER_IS_BETTER = {"log_loss", "brier_score"}


@dataclass
class ChampionComparisonReport:
    champion_exists:  bool
    comparable:       bool
    message:          str
    new_training_run_id:      str
    champion_training_run_id: str | None = None
    new_metrics:      dict = field(default_factory=dict)
    champion_metrics: dict = field(default_factory=dict)
    delta:            dict = field(default_factory=dict)          # new - champion, per metrică
    improved:         dict = field(default_factory=dict)          # metrică -> bool
    simultaneous_improvement: bool | None = None                  # None = incomparabil


def compare_to_champion(
    algorithm_family: str,
    algorithm_version: str,
    league_scope: str,
    new_training_run_id: str,
    new_metrics: dict,
) -> ChampionComparisonReport:
    """new_metrics: dict cu chei din {"accuracy", "log_loss", "brier_score"}
    (subset — chei lipsă sunt pur și simplu excluse din comparație, nu
    aproximate)."""
    champion = sb.get_active_champion(algorithm_family, league_scope)
    if champion is None:
        return ChampionComparisonReport(
            champion_exists=False, comparable=False,
            message=(
                f"Niciun campion promovat încă pentru "
                f"({algorithm_family}, {league_scope}) — rulare de referință, "
                f"nimic de comparat."
            ),
            new_training_run_id=new_training_run_id,
            new_metrics=dict(new_metrics),
        )

    champion_run_id = champion.get("training_run_id")
    champion_run = sb.get_training_run(champion_run_id) if champion_run_id else None
    if champion_run is None:
        return ChampionComparisonReport(
            champion_exists=True, comparable=False,
            message=(
                f"Campion activ găsit ({champion_run_id}), dar rândul lui din "
                f"training_runs nu a putut fi citit — istoric inconsistent, "
                f"nu se aproximează."
            ),
            new_training_run_id=new_training_run_id,
            champion_training_run_id=champion_run_id,
            new_metrics=dict(new_metrics),
        )

    champion_metrics = champion_run.get("walk_forward_metrics") or {}
    delta: dict[str, float] = {}
    improved: dict[str, bool] = {}
    for key, new_val in new_metrics.items():
        champ_val = champion_metrics.get(key)
        if new_val is None or champ_val is None:
            continue
        d = round(new_val - champ_val, 4)
        delta[key] = d
        improved[key] = (d < 0) if key in _LOWER_IS_BETTER else (d > 0)

    simultaneous_improvement = all(improved.values()) if improved else None

    return ChampionComparisonReport(
        champion_exists=True, comparable=bool(delta),
        message=(
            f"Comparat cu campionul activ ({champion_run_id})."
            if delta else
            f"Campion activ găsit ({champion_run_id}), dar nicio metrică "
            f"comună de comparat (chei lipsă în una din rulări)."
        ),
        new_training_run_id=new_training_run_id,
        champion_training_run_id=champion_run_id,
        new_metrics=dict(new_metrics),
        champion_metrics=dict(champion_metrics),
        delta=delta,
        improved=improved,
        simultaneous_improvement=simultaneous_improvement,
    )
