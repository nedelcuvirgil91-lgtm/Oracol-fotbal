"""
================================================================================
FOOTBALL ORACLE — Learning Core: Training Runner (v0.1, manual)
================================================================================
Module: learning_core/training_runner.py

Orchestrează antrenarea manuală a unui algoritm din Model Registry — vezi
LEARNING_CORE_ARCHITECTURE.md §3.2, §6.

La v0.1: apelabil DOAR manual (CLI, learning_core/train.py) — NU e integrat
în sync/run_daily.py. Nu antrenează automat, nu evaluează, nu promovează, nu
decide nimic — doar rulează fit() pe un algoritm dat și persistă rezultatul.
Antrenarea automată/evaluarea/promovarea există azi ca fluxuri SEPARATE
(Continuous Learning / Daily Scheduler, ADR-030; shadow_testing.
evaluate_experiment(); promotion_service.py; Champion Manager,
model_champions) — acest modul rămâne, deliberat, doar calea manuală,
punctuală, nesuprapusă cu ele.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass

from learning_core import model_registry, storage


@dataclass
class RunReport:
    """Raport structurat al unei rulări — folosit atât de CLI (afișare),
    cât și de teste (verificare programatică)."""
    algorithm_name: str
    algorithm_version: str
    league_scope: str
    result: model_registry.TrainingRunResult
    saved_to: str


def run_training(algorithm_name: str, algorithm_version: str) -> RunReport:
    """Încarcă algoritmul din Model Registry, execută fit(), salvează
    rezultatul local (storage.save_training_run), întoarce un raport
    structurat.

    Nu prinde excepții proprii ale algoritmului — dacă fit() aruncă ceva
    neașteptat, propagă mai departe; apelantul (CLI) decide cum raportează.
    `KeyError` de la model_registry.get() (algoritm necunoscut) propagă la fel."""
    algorithm = model_registry.get(algorithm_name, algorithm_version)
    result = algorithm.fit(None)
    saved_path = storage.save_training_run(
        result,
        algorithm_name=algorithm.name,
        algorithm_version=algorithm.version,
        league_scope=algorithm.league_scope,
    )
    return RunReport(
        algorithm_name=algorithm.name,
        algorithm_version=algorithm.version,
        league_scope=algorithm.league_scope,
        result=result,
        saved_to=str(saved_path),
    )
