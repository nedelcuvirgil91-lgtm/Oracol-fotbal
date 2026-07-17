"""
Înregistrează algoritmii impliciți în Model Registry.

Apelat explicit de orice cod care are nevoie de registry populat (viitorul
Training Runner, CLI-uri, teste de integrare) — NU se rulează la simplul
`import learning_core`, ca să nu existe efecte secundare implicite doar la
import (vezi CLAUDE.md, North Star #3: niciun comportament nou nu pornește
implicit activ).

Idempotent: apeluri repetate nu aruncă eroare.
"""
from __future__ import annotations

from learning_core import model_registry
from learning_core.algorithms.production_champion import ProductionChampionAdapter
from learning_core.algorithms.xgboost_v1 import XGBoostV1Algorithm


def register_default_algorithms() -> None:
    try:
        model_registry.get("xgboost_v1", "1")
    except KeyError:
        model_registry.register(XGBoostV1Algorithm())

    try:
        model_registry.get("production_champion", "1")
    except KeyError:
        model_registry.register(ProductionChampionAdapter())
