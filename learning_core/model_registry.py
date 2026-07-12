"""
================================================================================
FOOTBALL ORACLE — Learning Core: Model Registry (v0.1)
================================================================================
Module: learning_core/model_registry.py

Catalog static al algoritmilor de predicție disponibili — vezi
docs/04_LEARNING_CORE/LEARNING_CORE_ARCHITECTURE.md §3.1, §6.

Tipar identic cu shadow_testing.STATISTICAL_TESTS și mappings.LEAGUE_PROVIDERS:
un dict populat prin register(), niciodată prin if/elif distribuit în cod.
Adăugarea unui algoritm nou = o intrare nouă aici, zero schimbare în restul
Learning Core.

Acest modul e pur catalog — nu antrenează, nu evaluează, nu decide nimic
(vezi LEARNING_CORE_ARCHITECTURE.md §5, rândul "Model Registry").
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class TrainingRunResult:
    """Rezultatul structurat al unei rulări de antrenare — vezi §6 din
    LEARNING_CORE_ARCHITECTURE.md. `walk_forward_metrics` reutilizează exact
    formatul deja produs de ml_predictor._walk_forward_validate()."""
    training_run_id: str
    status: str  # "trained" | "insufficient_data" | "error" | "unavailable"
    samples_used: int = 0
    walk_forward_metrics: dict = field(default_factory=dict)
    message: str = ""


@runtime_checkable
class LearningAlgorithm(Protocol):
    """Interfața uniformă pe care orice algoritm din Model Registry trebuie
    s-o respecte — vezi LEARNING_CORE_ARCHITECTURE.md §6.

    Notă de proiectare (semnalată explicit, nu ascunsă): `predict(features)`
    presupune feature-uri deja calculate. Pentru algoritmi care fac propriul
    feature engineering intern (ex. un viitor adaptor peste evaluate_match()
    din oracle_engine.py), `features` poate însemna un context mai bogat
    decât un dict pur numeric — fiecare adaptor documentează explicit ce
    așteaptă, în propriul docstring. Nu s-a construit încă o abstractizare
    unificatoare pentru asta (ar fi prematur — vezi CLAUDE.md, "nu introduce
    funcționalități speculative").
    """

    name: str
    version: str
    league_scope: str  # numele canonic al ligii (mappings.LEAGUE_PROVIDERS) sau "all"

    def fit(self, training_data: Any) -> TrainingRunResult: ...

    def predict(self, features: dict) -> tuple[float, float, float, dict]:
        """Întoarce (prob_home, prob_draw, prob_away, metadata)."""
        ...

    def describe(self) -> dict:
        """Hiperparametri / feature set — pentru persistare viitoare în training_runs."""
        ...


_REGISTRY: dict[tuple[str, str], LearningAlgorithm] = {}


def register(algorithm: LearningAlgorithm) -> None:
    """Înregistrează un algoritm — cheie (name, version). Aditiv: nu se
    suprascrie tăcut o intrare deja existentă (o versiune nouă = nume de
    versiune nou, nu un re-register peste aceeași cheie)."""
    key = (algorithm.name, algorithm.version)
    if key in _REGISTRY:
        raise ValueError(
            f"Algoritmul '{algorithm.name}' v{algorithm.version} e deja înregistrat — "
            f"folosește o versiune nouă, nu suprascrie una existentă."
        )
    _REGISTRY[key] = algorithm


def get(name: str, version: str) -> LearningAlgorithm:
    key = (name, version)
    if key not in _REGISTRY:
        raise KeyError(f"Algoritm necunoscut: '{name}' v{version}. Vezi list_available().")
    return _REGISTRY[key]


def list_available() -> list[tuple[str, str]]:
    return sorted(_REGISTRY.keys())


def _clear_registry_for_tests() -> None:
    """Folosit exclusiv de tests/ — reset între teste izolate. Nu se apelează
    din cod de producție."""
    _REGISTRY.clear()
