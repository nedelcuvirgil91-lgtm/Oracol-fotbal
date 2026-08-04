"""
Teste pentru learning_core.calibration_artifact_storage — Pasul 10a
(ADR-049). Fără rețea — Storage Supabase fabricat, in-memory. Mirror
structural al tests/test_model_artifact_storage.py, dar fără dependența
de XGBoost real (artefactul de calibrare e doar un JSON minimal).
"""
import json

import pytest

from learning_core import calibration_artifact_storage as cas


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


@pytest.fixture
def fake_store(monkeypatch):
    store: dict = {}
    fake_client = _FakeClient(store)
    monkeypatch.setattr("supabase_client.get_client", lambda: fake_client)
    return store


def test_save_and_load_roundtrip(fake_store):
    path = cas.save_calibration_artifact(1.35, training_run_id="run-abc-123")
    assert path == "run-abc-123.calibration.json"
    assert path in fake_store

    reloaded = cas.load_calibration_artifact("run-abc-123")
    assert reloaded == pytest.approx(1.35)


def test_save_rejects_non_positive_temperature(fake_store):
    assert cas.save_calibration_artifact(0.0, training_run_id="run-zero") is None
    assert cas.save_calibration_artifact(-1.2, training_run_id="run-neg") is None
    assert "run-zero.calibration.json" not in fake_store
    assert "run-neg.calibration.json" not in fake_store


def test_save_rejects_non_finite_temperature(fake_store):
    """[ADAUGAT — review Pasul 10a, observatia 2] NaN/±inf trebuie respinse
    explicit, nu doar T<=0."""
    assert cas.save_calibration_artifact(float("nan"), training_run_id="run-nan") is None
    assert cas.save_calibration_artifact(float("inf"), training_run_id="run-inf") is None
    assert cas.save_calibration_artifact(float("-inf"), training_run_id="run-neginf") is None
    assert "run-nan.calibration.json" not in fake_store
    assert "run-inf.calibration.json" not in fake_store
    assert "run-neginf.calibration.json" not in fake_store


def test_save_accepts_temperature_equal_to_one(fake_store):
    """T=1.0 e o valoare valida (calibrare fara efect), nu trebuie respinsa."""
    path = cas.save_calibration_artifact(1.0, training_run_id="run-t1")
    assert path is not None
    assert cas.load_calibration_artifact("run-t1") == 1.0


def test_save_graceful_without_supabase(monkeypatch):
    monkeypatch.setattr("supabase_client.get_client", lambda: None)
    assert cas.save_calibration_artifact(1.2, training_run_id="run-x") is None


def test_load_graceful_without_supabase(monkeypatch):
    monkeypatch.setattr("supabase_client.get_client", lambda: None)
    assert cas.load_calibration_artifact("run-x") is None


def test_load_graceful_missing_artifact(fake_store):
    assert cas.load_calibration_artifact("never-saved") is None


def test_load_graceful_corrupted_bytes(fake_store):
    fake_store["corrupted-run.calibration.json"] = b"not valid json at all"
    assert cas.load_calibration_artifact("corrupted-run") is None


def test_load_rejects_non_positive_temperature_in_artifact(fake_store):
    fake_store["bad-run.calibration.json"] = b'{"temperature": -0.5}'
    assert cas.load_calibration_artifact("bad-run") is None


def test_load_rejects_non_finite_temperature_in_artifact(fake_store):
    """[ADAUGAT — review Pasul 10a, observatia 3] Un artefact corupt/manipulat
    manual cu NaN/inf trebuie respins la incarcare, nu propagat mai departe."""
    fake_store["nan-run.calibration.json"] = json.dumps({"temperature": float("nan")}).encode("utf-8")
    fake_store["inf-run.calibration.json"] = json.dumps({"temperature": float("inf")}).encode("utf-8")
    assert cas.load_calibration_artifact("nan-run") is None
    assert cas.load_calibration_artifact("inf-run") is None


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
    assert cas.save_calibration_artifact(1.1, training_run_id="run-y") is None
