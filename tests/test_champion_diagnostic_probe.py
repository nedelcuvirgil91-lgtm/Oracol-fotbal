"""
Teste pentru FootballOracleEngine._initialize_ml()/_resolve_champion() —
Pasul 7B, Architecture Gate 7B. Verifică toate invariantele impuse la
aprobare:
  1. Decizie unică Champion vs Local vs None (CHAMPION_ML/LOCAL_ML/NO_ML).
  2. train() NU e apelat niciodată când Champion reușește (Defectul A).
  3. Un singur apel către champion_loader.load_champion_or_none() per
     construcție — rezultatul alimentează simultan decizia, diagnosticul,
     seeding-ul.
  4. Schema fixă a champion_diagnostic rămâne neschimbată.
  5. self.ml e scris o singură dată în toată clasa (grep/AST).
"""
import ast
import inspect
import textwrap

import ml_predictor
import oracle_engine
from learning_core.champion_loader import ChampionLoadResult
from learning_core.local_model_cache import LocalCacheLoadResult


class _FakeModel:
    def predict_proba(self, X):
        return [[0.5, 0.3, 0.2]]


def _fake_champion_result(training_run_id="run-1", samples_used=999, temperature=None):
    return ChampionLoadResult(
        training_run_id=training_run_id, model=_FakeModel(), samples_used=samples_used,
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
        accuracy=0.55, log_loss=0.95, trained_at="2026-07-14T00:00:00Z",
        temperature=temperature,
    )


def _fake_cache_result(training_run_id="cache-run-1", samples_used=500, temperature=None):
    return LocalCacheLoadResult(
        training_run_id=training_run_id, model=_FakeModel(), samples_used=samples_used,
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
        accuracy=0.52, log_loss=0.99, trained_at="2026-08-01T00:00:00Z",
        temperature=temperature,
    )


class _FakeEngine:
    """Instanță minimală, fără Supabase/API real — identic ca tipar cu
    FakeEngine din tests/test_oracle_engine_compat.py."""
    _initialize_ml = oracle_engine.FootballOracleEngine._initialize_ml
    _resolve_champion = oracle_engine.FootballOracleEngine._resolve_champion
    _resolve_local_cache = oracle_engine.FootballOracleEngine._resolve_local_cache
    _champion_diagnostic_unavailable = staticmethod(
        oracle_engine.FootballOracleEngine._champion_diagnostic_unavailable
    )
    _champion_diagnostic_from_result = staticmethod(
        oracle_engine.FootballOracleEngine._champion_diagnostic_from_result
    )

    def __init__(self, use_supabase=True):
        self.use_supabase = use_supabase


_DIAGNOSTIC_SCHEMA = {"status", "reason", "training_run_id", "algorithm_version", "validated_at"}


# ── Cerința centrală: "Champion wins over Local" ────────────────────────────

def test_champion_wins_over_local_train_never_called(monkeypatch):
    """train() trebuie sa fie EXCLUSIV fallback — apelul insusi lipseste
    cand Champion reuseste, nu doar rezultatul e ignorat (invariant impus
    explicit la aprobarea Architecture Gate 7B)."""
    monkeypatch.setattr(
        "learning_core.champion_loader.load_champion_or_none",
        lambda family, scope: _fake_champion_result(),
    )

    def _fail_if_called(self):
        raise AssertionError("train() NU trebuie apelat niciodata cand Champion reuseste")

    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "train", _fail_if_called)

    engine = _FakeEngine(use_supabase=True)
    engine._initialize_ml()  # nu trebuie sa ridice AssertionError

    assert engine.ml_source == "champion"
    assert engine.ml.is_trained is True
    assert isinstance(engine.ml.model, _FakeModel)


def _fail_if_train_called(self):
    raise AssertionError(
        "train() NU trebuie apelat niciodata din _initialize_ml() — antrenarea "
        "sincrona a fost eliminata complet din calea de servire (fix "
        "\"aplicatia porneste foarte greu\"); singurul fallback sub Champion "
        "e Local Model Cache (incarcare, nu antrenare)."
    )


def test_falls_back_to_local_cache_when_champion_unavailable(monkeypatch):
    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", lambda family, scope: None)
    monkeypatch.setattr(
        "learning_core.local_model_cache.load_latest_trained_model_or_none",
        lambda family, scope: _fake_cache_result(),
    )
    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "train", _fail_if_train_called)

    engine = _FakeEngine(use_supabase=True)
    engine._initialize_ml()  # nu trebuie sa ridice AssertionError

    assert engine.ml_source == "local"
    assert engine.ml.is_trained is True
    assert engine.ml.last_train_status == "trained_from_cache"


def test_no_ml_when_champion_and_cache_both_fail(monkeypatch):
    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", lambda family, scope: None)
    monkeypatch.setattr(
        "learning_core.local_model_cache.load_latest_trained_model_or_none", lambda family, scope: None,
    )
    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "train", _fail_if_train_called)

    engine = _FakeEngine(use_supabase=True)
    engine._initialize_ml()  # nu trebuie sa ridice AssertionError

    assert engine.ml_source == "none"
    assert engine.ml.is_trained is False


def test_train_never_called_from_initialize_ml_in_any_scenario(monkeypatch):
    """[ADAUGAT — fix "aplicatia porneste foarte greu"] Regresie centrala:
    indiferent de scenariu (Champion disponibil, doar cache disponibil,
    niciunul disponibil), _initialize_ml() nu antreneaza NICIODATA sincron —
    eliminat complet din calea de servire, mutat exclusiv in
    continuous_learning.py (Faza B, decuplat, in fundal)."""
    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "train", _fail_if_train_called)

    scenarios = {
        "champion": (lambda family, scope: _fake_champion_result(), lambda family, scope: _fake_cache_result()),
        "cache_only": (lambda family, scope: None, lambda family, scope: _fake_cache_result()),
        "neither": (lambda family, scope: None, lambda family, scope: None),
    }
    for name, (champion_fn, cache_fn) in scenarios.items():
        monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", champion_fn)
        monkeypatch.setattr("learning_core.local_model_cache.load_latest_trained_model_or_none", cache_fn)
        engine = _FakeEngine(use_supabase=True)
        engine._initialize_ml()  # nu trebuie sa ridice AssertionError in niciun scenariu


def test_no_supabase_means_no_ml_and_no_champion_attempt(monkeypatch):
    def _fail_if_called(family, scope):
        raise AssertionError("champion_loader nu trebuie atins fara Supabase")

    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", _fail_if_called)

    engine = _FakeEngine(use_supabase=False)
    engine._initialize_ml()

    assert engine.ml_source == "none"
    assert engine.champion_diagnostic["reason"] == "no_supabase"


# ── Un singur apel către champion_loader ────────────────────────────────────

def test_load_champion_or_none_called_exactly_once(monkeypatch):
    calls = []

    def _counting(family, scope):
        calls.append((family, scope))
        return _fake_champion_result()

    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", _counting)
    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "train",
                         lambda self: (_ for _ in ()).throw(AssertionError("nu trebuie apelat")))

    engine = _FakeEngine(use_supabase=True)
    engine._initialize_ml()

    assert len(calls) == 1


def test_diagnostic_and_serving_derived_from_same_call(monkeypatch):
    """champion_diagnostic si self.ml trebuie sa reflecte EXACT acelasi
    rezultat — imposibil sa diveraga, fiindca vin din acelasi apel."""
    result = _fake_champion_result(training_run_id="run-xyz")
    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", lambda family, scope: result)
    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "train",
                         lambda self: (_ for _ in ()).throw(AssertionError("nu trebuie apelat")))

    engine = _FakeEngine(use_supabase=True)
    engine._initialize_ml()

    assert engine.champion_diagnostic["training_run_id"] == "run-xyz"
    assert engine.ml.model is result.model


# ── _resolve_champion() în izolare ──────────────────────────────────────────

def test_resolve_champion_seeds_self_ml(monkeypatch):
    monkeypatch.setattr(
        "learning_core.champion_loader.load_champion_or_none",
        lambda family, scope: _fake_champion_result(samples_used=777),
    )

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    result = engine._resolve_champion()

    assert result is not None
    assert engine.ml.is_trained is True
    assert engine.ml.samples_used == 777
    assert engine.ml.last_train_status == "trained_from_champion"


def test_resolve_champion_leaves_ml_untouched_when_unavailable(monkeypatch):
    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", lambda family, scope: None)

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    result = engine._resolve_champion()

    assert result is None
    assert engine.ml.is_trained is False
    assert engine.ml.model is None


# ── _resolve_local_cache() în izolare (fix "aplicatia porneste foarte greu") ──

def test_resolve_local_cache_seeds_self_ml(monkeypatch):
    monkeypatch.setattr(
        "learning_core.local_model_cache.load_latest_trained_model_or_none",
        lambda family, scope: _fake_cache_result(samples_used=333),
    )

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    result = engine._resolve_local_cache()

    assert result is not None
    assert engine.ml.is_trained is True
    assert engine.ml.samples_used == 333
    assert engine.ml.last_train_status == "trained_from_cache"


def test_resolve_local_cache_sets_last_training_run_id_for_traceability(monkeypatch):
    """Spre deosebire de Champion (trasabilitatea vine din champion_diagnostic),
    _resolve_ml_traceability() cu ml_source=="local" citeste
    self.ml.last_training_run_id direct — seed_from_cache() trebuie sa-l
    populeze, altfel Validation Framework ar pierde trasabilitatea pentru
    un model servit din cache."""
    monkeypatch.setattr(
        "learning_core.local_model_cache.load_latest_trained_model_or_none",
        lambda family, scope: _fake_cache_result(training_run_id="cache-run-xyz"),
    )

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    engine._resolve_local_cache()

    assert engine.ml.last_training_run_id == "cache-run-xyz"


def test_resolve_local_cache_leaves_ml_untouched_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        "learning_core.local_model_cache.load_latest_trained_model_or_none", lambda family, scope: None,
    )

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    result = engine._resolve_local_cache()

    assert result is None
    assert engine.ml.is_trained is False
    assert engine.ml.model is None


def test_resolve_local_cache_never_raises(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare simulata")

    monkeypatch.setattr("learning_core.local_model_cache.load_latest_trained_model_or_none", _boom)

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    result = engine._resolve_local_cache()

    assert result is None


# ── Propagare temperatură (ADR-049, Pasul 10b) ──────────────────────────────

def test_resolve_champion_propagates_temperature_to_seed_from_champion(monkeypatch):
    monkeypatch.setattr(
        "learning_core.champion_loader.load_champion_or_none",
        lambda family, scope: _fake_champion_result(temperature=1.37),
    )

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    result = engine._resolve_champion()

    assert result is not None
    assert engine.ml.temperature == 1.37
    assert engine.ml.get_calibration_temperature() == 1.37


def test_resolve_champion_propagates_none_temperature_when_calibration_unavailable(monkeypatch):
    """Degradare grațioasă (ADR-049 §8/§9) — fără calibrare disponibilă
    pentru Champion, self.ml.temperature rămâne None, comportament identic
    cu cel dinainte de Pasul 10b. Champion-ul tot servește (result nu e
    None), doar probabilitățile rămân brute."""
    monkeypatch.setattr(
        "learning_core.champion_loader.load_champion_or_none",
        lambda family, scope: _fake_champion_result(temperature=None),
    )

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    result = engine._resolve_champion()

    assert result is not None
    assert engine.ml.temperature is None


def test_initialize_ml_end_to_end_carries_temperature_through_to_engine(monkeypatch):
    """Test de integrare (Implementation Plan 10b §3) — firul complet
    loader -> _resolve_champion() -> seed_from_champion() ->
    MLPredictorEngine, verificat prin punctul de intrare real
    (_initialize_ml()), nu doar prin _resolve_champion() izolat."""
    monkeypatch.setattr(
        "learning_core.champion_loader.load_champion_or_none",
        lambda family, scope: _fake_champion_result(temperature=2.1),
    )

    engine = _FakeEngine(use_supabase=True)
    engine._initialize_ml()

    assert engine.ml_source == "champion"
    assert engine.ml.temperature == 2.1


def test_resolve_champion_never_raises(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare simulata")

    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", _boom)

    engine = _FakeEngine(use_supabase=True)
    engine.ml = ml_predictor.MLPredictorEngine()
    result = engine._resolve_champion()

    assert result is None


# ── Schema fixă champion_diagnostic ──────────────────────────────────────────

def test_champion_diagnostic_schema_is_fixed_in_all_scenarios(monkeypatch):
    monkeypatch.setattr(ml_predictor.MLPredictorEngine, "train", _fail_if_train_called)
    monkeypatch.setattr(
        "learning_core.local_model_cache.load_latest_trained_model_or_none", lambda family, scope: None,
    )

    scenarios = {
        "champion": lambda family, scope: _fake_champion_result(),
        "no_champion": lambda family, scope: None,
    }
    for name, fn in scenarios.items():
        monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", fn)
        engine = _FakeEngine(use_supabase=True)
        engine._initialize_ml()
        assert set(engine.champion_diagnostic.keys()) == _DIAGNOSTIC_SCHEMA, f"schema alterata la {name}"

    unavailable = oracle_engine.FootballOracleEngine._champion_diagnostic_unavailable("no_supabase")
    assert set(unavailable.keys()) == _DIAGNOSTIC_SCHEMA


# ── Gărzi structurale ────────────────────────────────────────────────────────

def test_resolve_champion_body_never_reassigns_self_ml_reference():
    """self.ml.seed_from_champion(...) e o metoda apelata PE obiectul deja
    existent — self.ml insusi nu trebuie reasignat in _resolve_champion()."""
    source = textwrap.dedent(inspect.getsource(oracle_engine.FootballOracleEngine._resolve_champion))
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                assert ast.dump(target) != ast.dump(ast.parse("self.ml", mode="eval").body), (
                    "_resolve_champion nu are voie sa reasigneze self.ml — doar sa-l seedeze in loc"
                )


def test_self_ml_assigned_exactly_once_in_whole_file():
    source = inspect.getsource(oracle_engine)
    assignments = [line for line in source.splitlines() if line.strip().startswith("self.ml = ")]
    assert len(assignments) == 1, f"self.ml trebuie asignat o singura data: {assignments}"


def test_initialize_ml_defined_and_called_exactly_once():
    source = inspect.getsource(oracle_engine)
    assert source.count("def _initialize_ml(") == 1
    assert source.count("self._initialize_ml()") == 1
