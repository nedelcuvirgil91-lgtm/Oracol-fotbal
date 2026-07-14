"""
Teste pentru FootballOracleEngine._probe_champion() — Pasul 6, Architecture
Gate 6. Verifică STRICT proprietatea centrală impusă de Chief Architect
(clarificată explicit înainte de implementare): Champion Loading în Pasul 6
NU schimbă ce servește Runtime — self.ml rămâne exclusiv din antrenarea
locală, `champion_diagnostic`/`ml_source` sunt informație separată, izolată.
"""
import ast
import inspect
import textwrap

import oracle_engine


class _FakeEngine:
    """Instanță minimală, fără Supabase/API real — identic ca tipar cu
    FakeEngine din tests/test_oracle_engine_compat.py."""
    _probe_champion = oracle_engine.FootballOracleEngine._probe_champion
    _champion_diagnostic_unavailable = staticmethod(
        oracle_engine.FootballOracleEngine._champion_diagnostic_unavailable
    )


_DIAGNOSTIC_SCHEMA = {"status", "reason", "training_run_id", "algorithm_version", "validated_at"}


def test_probe_champion_returns_unavailable_when_no_champion(monkeypatch):
    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", lambda family, scope: None)

    engine = _FakeEngine()
    result = engine._probe_champion()

    assert result["status"] == "unavailable"
    assert result["reason"] == "no_valid_champion"
    assert result["training_run_id"] is None
    assert result["algorithm_version"] is None
    assert result["validated_at"] is not None


def test_probe_champion_returns_validated_with_fixed_schema(monkeypatch):
    from learning_core.champion_loader import ChampionLoadResult

    class _FakeModel:
        def predict_proba(self, X):
            return [[0.5, 0.3, 0.2]]

    fake_result = ChampionLoadResult(
        training_run_id="run-1", model=_FakeModel(), samples_used=999,
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
    )
    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", lambda family, scope: fake_result)

    engine = _FakeEngine()
    result = engine._probe_champion()

    assert result["status"] == "validated"
    assert result["reason"] is None
    assert result["training_run_id"] == "run-1"
    assert result["algorithm_version"] == "1"
    assert result["validated_at"] is not None


def test_probe_champion_never_raises(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("eroare simulata")

    monkeypatch.setattr("learning_core.champion_loader.load_champion_or_none", _boom)

    engine = _FakeEngine()
    result = engine._probe_champion()

    assert result["status"] == "unavailable"
    assert result["reason"] == "probe_failed"


def test_champion_diagnostic_schema_is_fixed_and_minimal():
    """Recomandare explicita Chief Architect: champion_diagnostic trebuie
    sa ramana STRICT informativ (status/reason/training_run_id/
    algorithm_version/validated_at) — niciun camp suplimentar care ar
    sugera decizie/fallback/retry/statistica, in niciun scenariu."""
    import learning_core.champion_loader as cl_module

    class _FakeModel:
        def predict_proba(self, X):
            return [[0.5, 0.3, 0.2]]

    fake_result = cl_module.ChampionLoadResult(
        training_run_id="run-1", model=_FakeModel(), samples_used=999,
        algorithm_family="xgboost_v1", algorithm_version="1", league_scope="all",
    )

    scenarios = [
        lambda: None,
        lambda: fake_result,
    ]
    for i, scenario in enumerate(scenarios):
        import unittest.mock as mock
        with mock.patch("learning_core.champion_loader.load_champion_or_none", side_effect=lambda f, s: scenario()):
            engine = _FakeEngine()
            result = engine._probe_champion()
            assert set(result.keys()) == _DIAGNOSTIC_SCHEMA, f"schema alterata la scenariul {i}: {set(result.keys())}"

    unavailable = oracle_engine.FootballOracleEngine._champion_diagnostic_unavailable("no_supabase")
    assert set(unavailable.keys()) == _DIAGNOSTIC_SCHEMA


def test_probe_champion_body_never_assigns_self_ml():
    """Garda structurala: _probe_champion nu are voie sa scrie self.ml sau
    orice atribut al lui — Pasul 6 nu schimba ce serveste Runtime."""
    source = textwrap.dedent(inspect.getsource(oracle_engine.FootballOracleEngine._probe_champion))
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                target_str = ast.dump(target)
                assert "attr='ml'" not in target_str, (
                    "_probe_champion nu are voie sa scrie self.ml — "
                    "Pasul 6 e strict diagnostic, servirea ramane pe antrenarea locala"
                )


def test_ml_source_and_champion_diagnostic_defined_exactly_once_in_init():
    source = inspect.getsource(oracle_engine)
    assert source.count("self.ml_source: str =") == 1
    assert source.count("self.champion_diagnostic: dict =") == 1
    assert source.count("def _probe_champion(") == 1


def test_champion_diagnostic_module_is_probed_not_wired_to_serving():
    """Verificare directa a codului sursa: apelul catre champion_loader
    ramane in interiorul _probe_champion (diagnostic), niciodata langa
    linia unde self.ml e populat pentru servire."""
    source = inspect.getsource(oracle_engine)
    ml_train_idx = source.index("train_result = self.ml.train()")
    probe_def_idx = source.index("def _probe_champion(")
    champion_loader_import_idx = source.index("from learning_core.champion_loader import load_champion_or_none")

    # importul champion_loader trebuie sa fie DUPA definitia lui _probe_champion
    # (adica in interiorul metodei), nu langa antrenarea locala.
    assert champion_loader_import_idx > probe_def_idx > ml_train_idx
