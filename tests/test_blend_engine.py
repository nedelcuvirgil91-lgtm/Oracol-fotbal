"""
Teste pentru blend_engine.py (ADR-051/ADR-052) — motor independent, pur,
fără I/O. Verifică exact contractul public (EngineOutput/BlendConfig/
BlendEngine.predict()) și separarea de responsabilitate față de ML Engine
(nicio antrenare, nicio învățare, doar combinare de predicții deja
calculate).
"""
import blend_engine
from blend_engine import BlendConfig, BlendEngine, EngineOutput, WeightedAverageStrategy


def test_module_has_zero_coupling_with_rest_of_project():
    """Verificare STATICĂ, nu doar afirmată — blend_engine.py nu importă
    niciun modul din proiect (oracle_engine/ml_predictor/feature_engine/
    learning_core.*)."""
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(blend_engine.__file__).read_text(encoding="utf-8"))
    forbidden = {"oracle_engine", "ml_predictor", "feature_engine", "learning_core",
                 "supabase_client", "shadow_testing", "challenger_manager"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden, f"import interzis: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            assert module not in forbidden, f"import interzis: {node.module}"


def test_predict_with_single_provider_returns_that_providers_probs():
    """Cu un singur furnizor (azi: doar Oracle), Blend == acel furnizor —
    nu e o aproximare, e definiția exactă a unei medii cu un singur termen."""
    engine = BlendEngine()
    outputs = [EngineOutput("oracle", 0.46, 0.29, 0.25)]
    result = engine.predict(outputs)
    assert result == {"prob_home": 0.46, "prob_draw": 0.29, "prob_away": 0.25}


def test_predict_with_empty_outputs_returns_none():
    engine = BlendEngine()
    assert engine.predict([]) is None


def test_predict_with_two_providers_equal_weight_is_true_average():
    engine = BlendEngine(BlendConfig(weights={}))
    outputs = [
        EngineOutput("oracle", 0.40, 0.30, 0.30),
        EngineOutput("ml", 0.60, 0.20, 0.20),
    ]
    result = engine.predict(outputs)
    assert abs(result["prob_home"] - 0.50) < 1e-9
    assert abs(result["prob_draw"] - 0.25) < 1e-9
    assert abs(result["prob_away"] - 0.25) < 1e-9


def test_weights_from_config_change_the_blend():
    engine_equal = BlendEngine(BlendConfig(weights={}))
    engine_favor_ml = BlendEngine(BlendConfig(weights={"oracle": 0.2, "ml": 0.8}))
    outputs = [
        EngineOutput("oracle", 0.40, 0.30, 0.30),
        EngineOutput("ml", 0.60, 0.20, 0.20),
    ]
    r_equal = engine_equal.predict(outputs)
    r_favor_ml = engine_favor_ml.predict(outputs)
    assert r_equal["prob_home"] != r_favor_ml["prob_home"]
    # ponderea mai mare pe ml (care are prob_home mai mare) trage rezultatul spre 0.60
    assert r_favor_ml["prob_home"] > r_equal["prob_home"]


def test_missing_weight_for_a_provider_defaults_to_neutral_one():
    """Fără o pondere explicită pentru un motor, default-ul e 1.0 (neutru),
    niciodată o valoare inventată specific per motor."""
    engine_default = BlendEngine(BlendConfig(weights={}))
    engine_explicit_one = BlendEngine(BlendConfig(weights={"oracle": 1.0, "ml": 1.0}))
    outputs = [
        EngineOutput("oracle", 0.40, 0.30, 0.30),
        EngineOutput("ml", 0.60, 0.20, 0.20),
    ]
    assert engine_default.predict(outputs) == engine_explicit_one.predict(outputs)


def test_output_probabilities_sum_to_one():
    engine = BlendEngine()
    outputs = [
        EngineOutput("oracle", 0.40, 0.30, 0.30),
        EngineOutput("ml", 0.55, 0.25, 0.20),
    ]
    result = engine.predict(outputs)
    assert abs(sum(result.values()) - 1.0) < 1e-9


def test_blend_config_from_dict_defaults_on_missing_keys():
    cfg = BlendConfig.from_dict({})
    assert cfg.strategy == "weighted_average"
    assert cfg.weights == {}


def test_blend_config_from_dict_ignores_unknown_keys():
    cfg = BlendConfig.from_dict({"strategy": "weighted_average", "weights": {"oracle": 1.0}, "bogus_key": 123})
    assert cfg.strategy == "weighted_average"
    assert cfg.weights == {"oracle": 1.0}


def test_blend_config_from_dict_handles_none():
    cfg = BlendConfig.from_dict(None)
    assert cfg == BlendConfig()


def test_unknown_strategy_falls_back_to_weighted_average():
    """Contract robust — un nume de strategie necunoscut (ex. config
    stricat/versiune veche) nu crapă, cade grațios pe V1."""
    engine = BlendEngine(BlendConfig(strategy="does_not_exist"))
    outputs = [EngineOutput("oracle", 0.46, 0.29, 0.25)]
    result = engine.predict(outputs)
    assert result == {"prob_home": 0.46, "prob_draw": 0.29, "prob_away": 0.25}


def test_weighted_average_strategy_is_registered_as_default():
    engine = BlendEngine()
    assert engine.config.strategy == "weighted_average"
    assert isinstance(BlendEngine._STRATEGIES["weighted_average"], WeightedAverageStrategy)


def test_blend_strategy_has_no_training_related_methods():
    """Separare de responsabilitate față de ML Engine (cerință explicită):
    o strategie de combinare NU are metode de antrenare/învățare —
    verificat direct pe interfața publică, nu doar afirmat."""
    strategy = WeightedAverageStrategy()
    forbidden_method_names = {"fit", "train", "update_weights", "learn", "backward"}
    public_methods = {name for name in dir(strategy) if not name.startswith("_")}
    assert forbidden_method_names.isdisjoint(public_methods)


def test_engine_output_and_blend_config_are_immutable():
    """Contracte publice imuabile (frozen dataclass) — nicio mutație
    accidentală a unei ieșiri de motor sau a unui config partajat."""
    import dataclasses

    output = EngineOutput("oracle", 0.4, 0.3, 0.3)
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        output.prob_home = 0.9

    config = BlendConfig()
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        config.strategy = "other"
