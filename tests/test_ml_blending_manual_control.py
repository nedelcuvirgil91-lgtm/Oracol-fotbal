"""Teste pentru R-ARCH-REVIEW-01 - control manual al blend-ului Predictor/ML.

Cerinta explicita: ML continua sa se antreneze/salveze indiferent de acest
flag (is_trained neatins) - doar INFLUENTA asupra predictiei finale
(blend_predictions() aplicat in evaluate_match()) e gatata de
ml_blending_enabled, implicit False. Fara retea live - inspectie de sursa +
verificare de config, acelasi tipar ca test_oracle_engine_compat.py."""
from __future__ import annotations

import inspect

import oracle_engine


def test_ml_blending_disabled_by_default():
    assert oracle_engine.DEFAULT_CONFIG["ml_blending_enabled"] is False


def test_ml_blend_weight_unchanged_by_new_flag():
    """Regresie: noul flag nu schimba valoarea implicita a lui ml_blend_weight
    (algoritmul de blend insusi ramane neatins, cf. cerinta explicita)."""
    assert oracle_engine.DEFAULT_CONFIG["ml_blend_weight"] == 0.35


def test_evaluate_match_gates_blend_on_ml_blending_enabled_not_just_is_trained():
    """Regresie directa: inainte de R-ARCH-REVIEW-01, blocul de blend
    pornea doar din `self.ml.is_trained`. Verificam ca noua conditie cere
    explicit si `ml_blending_enabled` din config - fara retea live,
    inspectie de sursa (acelasi tipar ca test_log_shadow_experiment_called_
    exactly_once_in_evaluate_match din test_oracle_engine_compat.py)."""
    source = inspect.getsource(oracle_engine.FootballOracleEngine.evaluate_match)
    assert "self.ml and self.ml.is_trained and self.config.get(\"ml_blending_enabled\", False)" in source


def test_ml_blending_flag_does_not_appear_near_training_or_saving():
    """Cerinta explicita: antrenarea/salvarea modelului ML raman complet
    neatinse de acest flag - ml_predictor.py (unde traieste antrenarea/
    salvarea) nu trebuie sa contina deloc referinte la ml_blending_enabled."""
    import ml_predictor
    source = inspect.getsource(ml_predictor)
    assert "ml_blending_enabled" not in source
