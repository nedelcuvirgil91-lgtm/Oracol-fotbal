"""
================================================================================
FOOTBALL ORACLE — Learning Core: adaptor Campion de Producție (v1)
================================================================================
Module: learning_core/algorithms/production_champion.py

Adaptor care înfășoară EXCLUSIV oracle_engine.FootballOracleEngine.evaluate_match()
— metoda publică, deja existentă, neschimbată. Nu apelează nicio metodă
privată (`_poisson_model`, `_monte_carlo` etc.), nu adaugă nicio metodă
publică nouă în oracle_engine.py, nu modifică nimic din fișierul respectiv.

Decizie de proiectare (aprobată explicit, vezi istoricul deciziei): acest
adaptor NU reprezintă doar Poisson/Monte Carlo izolat — reprezintă întregul
blend care rulează azi în producție (Poisson → Monte Carlo → blend ELO/ML →
de-vig → value betting), exact ce servește predicții live. Motivul: Learning
Core trebuie să compare orice challenger cu ceea ce rulează efectiv în
producție, nu cu un algoritm istoric sau izolat artificial. Indiferent cum
va evolua intern oracle_engine.py peste ani, acest adaptor rămâne definiția
"campionului curent" — nu se schimbă contractul, doar ce e în spatele lui.

`fit()` e no-op intenționat: campionul de producție nu se antrenează separat
prin acest adaptor — starea lui (weights.json/model_config, modelul ML deja
antrenat) e întreținută de fluxurile deja existente (League Learning,
retrain_ml_model()), în afara Learning Core la v4.1.

`predict(features)` la acest adaptor așteaptă contextul complet de meci
(dict cu fixture_id, home_team, away_team, league, kickoff_date etc. — exact
formatul deja consumat de evaluate_match()), NU un dict numeric de
feature-uri precalculate. Deviație documentată explicit față de restul
interfeței LearningAlgorithm — vezi nota din model_registry.py.

Construcție ÎNTÂRZIATĂ (lazy), descoperită la verificare directă, nu
presupusă: FootballOracleEngine() declanșează, prin
FootballOracleAPI._validate_api_keys(), o încercare reală de apel de rețea
la construcție (validare chei API live). Fără lazy loading, orice utilizare
a Model Registry — inclusiv doar `register_default_algorithms()` sau
listarea algoritmilor disponibili — ar plăti acest cost (câteva secunde de
retry-uri + log de rețea), chiar dacă acest adaptor nu ajunge să fie folosit
efectiv. Engine-ul se construiește abia la primul predict() real.
================================================================================
"""
from __future__ import annotations

import uuid
from typing import Any

from learning_core.model_registry import TrainingRunResult
from oracle_engine import FootballOracleEngine


class ProductionChampionAdapter:
    """Implementează LearningAlgorithm peste FootballOracleEngine.evaluate_match(),
    fără nicio atingere a oracle_engine.py."""

    name = "production_champion"
    version = "1"
    league_scope = "all"

    def __init__(self) -> None:
        self._engine: FootballOracleEngine | None = None

    def _get_engine(self) -> FootballOracleEngine:
        """Construiește engine-ul real doar la prima utilizare efectivă —
        vezi nota de lazy loading din header-ul modulului."""
        if self._engine is None:
            self._engine = FootballOracleEngine()
        return self._engine

    def fit(self, training_data: object = None) -> TrainingRunResult:
        """No-op — vezi nota de proiectare din header-ul modulului. Campionul
        de producție nu se antrenează prin Learning Core la v4.1; starea lui
        e cea deja întreținută de fluxurile existente."""
        return TrainingRunResult(
            training_run_id=str(uuid.uuid4()),
            status="not_applicable",
            samples_used=0,
            walk_forward_metrics={},
            message=(
                "ProductionChampionAdapter reprezintă starea curentă de producție — "
                "nu se antrenează separat prin acest adaptor."
            ),
        )

    def predict(self, features: dict) -> tuple[float, float, float, dict]:
        """`features` = contextul complet de meci (match dict), nu feature-uri
        numerice precalculate — vezi header-ul modulului.

        evaluate_match() indexează direct chei obligatorii (`match["home_team"]`
        etc.) — un context de meci incomplet aruncă KeyError/TypeError, nu
        întoarce None. Adaptorul prinde explicit acest caz (fără să modifice
        oracle_engine.py) și degradează controlat, ca Training Runner-ul să
        nu se oprească la un singur meci cu date lipsă."""
        try:
            pred = self._get_engine().evaluate_match(features)
        except (KeyError, TypeError) as exc:
            return (0.0, 0.0, 0.0, {"error": f"context de meci invalid/incomplet: {exc}"})
        if pred is None:
            return (0.0, 0.0, 0.0, {"error": "evaluate_match a eșuat sau meci invalid"})
        metadata = {
            "home_xg": pred.home_xg,
            "away_xg": pred.away_xg,
            "ml_active": pred.ml_active,
            "ml_blend_label": pred.ml_blend_label,
            "confidence_score": pred.confidence_score,
            "data_quality_home": pred.data_quality_home,
            "data_quality_away": pred.data_quality_away,
        }
        return (pred.prob_home_win, pred.prob_draw, pred.prob_away_win, metadata)

    def describe(self) -> dict:
        """Info statică — deliberat NU construiește engine-ul (evită costul
        de rețea al lui FootballOracleEngine() doar pentru metadate)."""
        return {
            "algorithm_family": self.name,
            "algorithm_version": self.version,
            "wraps": "oracle_engine.FootballOracleEngine.evaluate_match",
            "engine_constructed": self._engine is not None,
        }

    def get_trained_model(self) -> Any | None:
        """Vezi LearningAlgorithm.get_trained_model() (model_registry.py) pentru
        contractul complet. Niciodată un model real — fit() e no-op (vezi header-ul
        modulului), campionul de producție nu se antrenează prin acest adaptor."""
        return None
