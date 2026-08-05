"""
================================================================================
FOOTBALL ORACLE — Learning Core: Challenger Runner (v0.1)
================================================================================
Module: learning_core/challenger_runner.py

Rulează orice algoritm din Model Registry ("challenger") și campionul curent
("production_champion", implicit) pe același input, producând un rezultat
comparabil, side-by-side. Nu evaluează statistic — evaluarea statistică
reală (Brier/Log-loss/Accuracy, simultan) există azi în shadow_testing.
evaluate_experiment() + Challenger FSM (ADR-016), fluxuri separate, complet
neatinse de acest modul — Challenger Runner rămâne exclusiv un instrument
punctual de comparație manuală, nu decide nimic, nu scrie în
shadow_predictions/experiment_registry — doar rulează și compară.

NU atinge Prediction Engine / calea de servire live (app.py) — funcționează
exclusiv ca instrument intern de Learning Core, apelat manual. Folosește
ProductionChampionAdapter (construit tot pentru Learning Core, la Pasul 1)
ca sursă a rezultatului campionului — asta nu e "atingerea" fluxului care
servește utilizatori, e comparație internă, izolată.

Notă de compatibilitate (semnalată explicit, nu ascunsă): challenger și
campion pot aștepta formate diferite pentru `features` (vezi nota din
model_registry.LearningAlgorithm — production_champion așteaptă context
complet de meci, xgboost_v1 așteaptă feature-uri numerice precalculate).
Challenger Runner NU rezolvă această discrepanță — trimite EXACT același
`features` ambilor algoritmi; dacă unul nu-l poate interpreta, propriul lui
`error` apare în metadata rezultatului (comportament deja gestionat de
adaptorii existenți), vizibil în comparație, nu ascuns.

Robustețe pentru "orice algoritm" (cerință explicită): un algoritm al cărui
predict() aruncă o excepție neașteptată nu oprește comparația — Challenger
Runner o prinde și o raportează ca rezultat degradat (0.0/0.0/0.0 + error),
exact tiparul deja aplicat în adaptorii xgboost_v1/production_champion.
================================================================================
"""
from __future__ import annotations

from dataclasses import dataclass

from learning_core import model_registry


@dataclass
class AlgorithmOutcome:
    """Rezultatul unui singur algoritm, în formatul comun al comparației."""
    algorithm_name: str
    algorithm_version: str
    prob_home: float
    prob_draw: float
    prob_away: float
    metadata: dict


@dataclass
class ChallengerComparisonResult:
    """Rezultatul complet al unei comparații challenger vs. campion."""
    champion: AlgorithmOutcome
    challenger: AlgorithmOutcome
    probability_delta: dict[str, float]


def _run_algorithm(name: str, version: str, features: dict) -> AlgorithmOutcome:
    """`model_registry.get()` aruncă KeyError necaptat dacă algoritmul nu e
    înregistrat — eroare de configurare, apelantul decide cum raportează.
    Excepțiile din interiorul predict() propriu-zis (comportament neașteptat
    al unui algoritm oarecare) SUNT prinse aici — vezi nota din header."""
    algorithm = model_registry.get(name, version)
    try:
        ph, pd, pa, metadata = algorithm.predict(features)
    except Exception as exc:
        ph, pd, pa, metadata = 0.0, 0.0, 0.0, {"error": f"predict() a eșuat: {exc}"}
    return AlgorithmOutcome(
        algorithm_name=algorithm.name,
        algorithm_version=algorithm.version,
        prob_home=ph, prob_draw=pd, prob_away=pa,
        metadata=metadata,
    )


def run_challenger(
    challenger_name: str,
    challenger_version: str,
    features: dict,
    champion_name: str = "production_champion",
    champion_version: str = "1",
) -> ChallengerComparisonResult:
    """Rulează challenger-ul și campionul pe același `features`, întoarce un
    rezultat comparabil (probabilități side-by-side + delta simplu).

    Campionul implicit e production_champion v1 — reprezintă azi ceea ce
    rulează efectiv în producție (vezi learning_core/algorithms/production_champion.py).
    Nu presupune existența unui Champion Manager (neimplementat încă) — dacă
    va exista, îi va înlocui doar valorile implicite ale acestor parametri,
    fără schimbare de interfață aici."""
    champion_outcome = _run_algorithm(champion_name, champion_version, features)
    challenger_outcome = _run_algorithm(challenger_name, challenger_version, features)

    delta = {
        "home": round(challenger_outcome.prob_home - champion_outcome.prob_home, 4),
        "draw": round(challenger_outcome.prob_draw - champion_outcome.prob_draw, 4),
        "away": round(challenger_outcome.prob_away - champion_outcome.prob_away, 4),
    }

    return ChallengerComparisonResult(
        champion=champion_outcome,
        challenger=challenger_outcome,
        probability_delta=delta,
    )
