"""
Teste pentru learning_core.model_artifact_storage — Pasul 1 din
Implementation Contract. Fără rețea — Storage Supabase fabricat, in-memory.

Cerința centrală de validat: modelul deserializat produce predicții
identice cu modelul original (în limitele toleranțelor numerice).

Notă tehnică: tests/conftest.py inserează un stub `xgboost` (creat pentru
un sandbox anterior fără XGBoost real instalat) în fața sys.path — stub-ul
nu implementează save_model/load_model, folosit doar pentru teste de
structură (walk-forward). Fidelitatea reală de serializare, cerută explicit
aici, nu poate fi validată pe un stub — încărcăm biblioteca REALĂ, izolat,
fără să atingem sys.path/sys.modules global (celelalte teste care depind
de stub rămân neafectate).
"""
import contextlib
import importlib
import sys

import numpy as np
import pytest


@contextlib.contextmanager
def _real_xgboost_active():
    """Face temporar activ xgboost-ul REAL instalat (ocolind stub-ul din
    tests/_stubs care e implicit primul pe sys.path via conftest.py), pentru
    durata blocului — apoi restaurează starea anterioară exact, fără efect
    persistent asupra sys.path/sys.modules pentru restul suitei de teste.

    Necesar fiindca learning_core/model_artifact_storage.py (cod de
    productie, neatins) face `from xgboost import XGBClassifier` la nivel
    de apel — acel import trebuie sa rezolve la biblioteca reala, nu la
    stub-ul de teste care nu implementeaza save_model/load_model."""
    saved_modules = {k: v for k, v in sys.modules.items() if k == "xgboost" or k.startswith("xgboost.")}
    for k in list(saved_modules):
        del sys.modules[k]

    stub_paths = [p for p in sys.path if p.endswith("_stubs")]
    saved_path = sys.path[:]
    sys.path = [p for p in sys.path if p not in stub_paths]
    try:
        importlib.invalidate_caches()
        importlib.import_module("xgboost")
        yield
    finally:
        sys.path = saved_path
        for k in list(sys.modules):
            if k == "xgboost" or k.startswith("xgboost."):
                del sys.modules[k]
        sys.modules.update(saved_modules)


with _real_xgboost_active():
    import xgboost as _real_xgboost_module
    XGBClassifier = _real_xgboost_module.XGBClassifier

from learning_core import model_artifact_storage as mas


class _FakeStorageBucket:
    def __init__(self, store: dict):
        self._store = store

    def upload(self, path, data, options=None):
        self._store[path] = data
        return {"path": path}

    def download(self, path):
        if path not in self._store:
            raise Exception(f"object not found: {path}")
        return self._store[path]


class _FakeStorage:
    def __init__(self, store: dict):
        self._store = store

    def from_(self, bucket_name):
        return _FakeStorageBucket(self._store)


class _FakeClient:
    def __init__(self, store: dict):
        self.storage = _FakeStorage(store)


def _train_tiny_model() -> tuple[XGBClassifier, np.ndarray]:
    """Model XGBoost REAL, mic, determinist — nu un mock — pentru a
    valida ca serializarea/deserializarea pastreaza fidelitatea reala.

    fit() declanseaza intern import-uri relative (`xgboost.data` etc.) care
    necesita sys.modules['xgboost'] sa fie pachetul real, nu stub-ul — de
    aceea antrenarea insasi ruleaza sub _real_xgboost_active()."""
    rng_X = np.array([
        [i % 7, (i * 3) % 11, (i + 2) % 5, i % 4]
        for i in range(60)
    ], dtype=float)
    y = np.array([i % 3 for i in range(60)])
    model = XGBClassifier(
        n_estimators=20, max_depth=3, random_state=42,
        objective="multi:softprob", num_class=3, eval_metric="mlogloss",
    )
    with _real_xgboost_active():
        model.fit(rng_X, y)
    return model, rng_X


@pytest.fixture
def fake_store(monkeypatch):
    store: dict = {}
    fake_client = _FakeClient(store)
    monkeypatch.setattr("supabase_client.get_client", lambda: fake_client)
    return store


def test_save_and_load_roundtrip_predictions_match_exactly(fake_store):
    model, X = _train_tiny_model()
    with _real_xgboost_active():
        original_probs = model.predict_proba(X)

        path = mas.save_model_artifact(model, training_run_id="run-abc-123")
        assert path == "run-abc-123.json"
        assert path in fake_store

        reloaded = mas.load_model_artifact("run-abc-123")
        assert reloaded is not None
        reloaded_probs = reloaded.predict_proba(X)

    assert np.allclose(original_probs, reloaded_probs, atol=1e-6), (
        "predictiile modelului reincarcat trebuie sa fie identice "
        "(in limita tolerantei numerice) cu cele ale modelului original"
    )


def test_save_graceful_without_supabase(monkeypatch):
    monkeypatch.setattr("supabase_client.get_client", lambda: None)
    model, _ = _train_tiny_model()
    with _real_xgboost_active():
        assert mas.save_model_artifact(model, training_run_id="run-x") is None


def test_load_graceful_without_supabase(monkeypatch):
    monkeypatch.setattr("supabase_client.get_client", lambda: None)
    assert mas.load_model_artifact("run-x") is None


def test_load_graceful_missing_artifact(fake_store):
    assert mas.load_model_artifact("never-saved") is None


def test_load_graceful_corrupted_bytes(fake_store):
    fake_store["corrupted-run.json"] = b"not a valid xgboost model file at all"
    assert mas.load_model_artifact("corrupted-run") is None


def test_save_graceful_on_storage_error(monkeypatch):
    class _BoomBucket:
        def upload(self, *a, **kw):
            raise Exception("network timeout")

    class _BoomStorage:
        def from_(self, bucket_name):
            return _BoomBucket()

    class _BoomClient:
        storage = _BoomStorage()

    monkeypatch.setattr("supabase_client.get_client", lambda: _BoomClient())
    model, _ = _train_tiny_model()
    with _real_xgboost_active():
        assert mas.save_model_artifact(model, training_run_id="run-y") is None
