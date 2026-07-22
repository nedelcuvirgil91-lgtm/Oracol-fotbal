"""
Teste pentru supabase_client.get_champion_predecessor / rpc_rollback_champion
(Stage R1.6, ADR-037) — fără rețea, client Supabase fabricat.

get_champion_predecessor e o CITIRE (derivare predecesor); rpc_rollback_champion
e un WRAPPER RPC. Atomicitatea/concurența reală a funcției Postgres se validează
separat, pe DB live (R1.8) — aici se verifică doar contractul Python.
"""
import pytest

import supabase_client as sb


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeSelectQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **kw):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def is_(self, key, value):
        if value == "null":
            self._rows = [r for r in self._rows if r.get(key) is None]
        return self

    def order(self, key, desc=False):
        # None sortat ca cel mai mic (nu apare primul la DESC)
        self._rows = sorted(
            self._rows, key=lambda r: (r.get(key) is not None, r.get(key)), reverse=desc,
        )
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeTableProxy:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **kw):
        return _FakeSelectQuery(self._rows)


class _FakeRpc:
    def __init__(self, handler, name, params):
        self._handler = handler
        self._name = name
        self._params = params

    def execute(self):
        return _FakeResult(self._handler(self._name, self._params))


class _FakeClient:
    def __init__(self, tables=None, rpc_handler=None):
        self._tables = tables or {}
        self._rpc_handler = rpc_handler

    def table(self, name):
        return _FakeTableProxy(self._tables.get(name, []))

    def rpc(self, name, params):
        return _FakeRpc(self._rpc_handler, name, params)


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(sb, "get_client", lambda: client)


# ── get_champion_predecessor ────────────────────────────────────────────────

def test_predecessor_none_without_supabase(monkeypatch):
    _patch_client(monkeypatch, None)
    assert sb.get_champion_predecessor("xgboost_v1", "all") is None


def test_predecessor_none_when_no_active_champion(monkeypatch):
    # Doar rânduri istorice, niciun activ (superseded_at IS NULL) → None
    client = _FakeClient(tables={"model_champions": [
        {"algorithm_family": "xgboost_v1", "league_scope": "all",
         "training_run_id": "run-0", "superseded_at": "2026-01-01T00:00:00Z", "superseded_by": "run-1"},
    ]})
    _patch_client(monkeypatch, client)
    assert sb.get_champion_predecessor("xgboost_v1", "all") is None


def test_predecessor_none_when_active_has_no_predecessor(monkeypatch):
    # Campion activ, dar niciun rând supersedat de el (a fost primul) → None
    client = _FakeClient(tables={"model_champions": [
        {"algorithm_family": "xgboost_v1", "league_scope": "all",
         "training_run_id": "run-1", "superseded_at": None, "superseded_by": None},
    ]})
    _patch_client(monkeypatch, client)
    assert sb.get_champion_predecessor("xgboost_v1", "all") is None


def test_predecessor_returns_immediate_most_recent(monkeypatch):
    # Activ = run-3; două rânduri supersedate de run-3 → cel mai recent (run-2)
    client = _FakeClient(tables={"model_champions": [
        {"algorithm_family": "xgboost_v1", "league_scope": "all",
         "training_run_id": "run-3", "superseded_at": None, "superseded_by": None},
        {"algorithm_family": "xgboost_v1", "league_scope": "all",
         "training_run_id": "run-2", "superseded_at": "2026-05-01T00:00:00Z", "superseded_by": "run-3"},
        {"algorithm_family": "xgboost_v1", "league_scope": "all",
         "training_run_id": "run-1", "superseded_at": "2026-03-01T00:00:00Z", "superseded_by": "run-3"},
    ]})
    _patch_client(monkeypatch, client)
    assert sb.get_champion_predecessor("xgboost_v1", "all") == "run-2"


def test_predecessor_respects_family_and_league(monkeypatch):
    # Predecesor pentru altă (family, league) nu se scurge
    client = _FakeClient(tables={"model_champions": [
        {"algorithm_family": "xgboost_v1", "league_scope": "all",
         "training_run_id": "run-2", "superseded_at": None, "superseded_by": None},
        {"algorithm_family": "xgboost_v1", "league_scope": "all",
         "training_run_id": "run-1", "superseded_at": "2026-05-01T00:00:00Z", "superseded_by": "run-2"},
        {"algorithm_family": "other", "league_scope": "all",
         "training_run_id": "x-1", "superseded_at": "2026-05-01T00:00:00Z", "superseded_by": "run-2"},
    ]})
    _patch_client(monkeypatch, client)
    assert sb.get_champion_predecessor("xgboost_v1", "all") == "run-1"


def test_predecessor_none_on_query_exception(monkeypatch):
    class _Boom:
        def table(self, name):
            raise RuntimeError("boom")
    _patch_client(monkeypatch, _Boom())
    assert sb.get_champion_predecessor("xgboost_v1", "all") is None


# ── rpc_rollback_champion ───────────────────────────────────────────────────

def test_rpc_raises_runtimeerror_without_supabase(monkeypatch):
    _patch_client(monkeypatch, None)
    with pytest.raises(RuntimeError):
        sb.rpc_rollback_champion("xgboost_v1", "all", "pred-1", "operator", "chief")


def test_rpc_passes_correct_params_and_returns_data(monkeypatch):
    captured = {}

    def _handler(name, params):
        captured["name"] = name
        captured["params"] = params
        return "rolled_back"

    _patch_client(monkeypatch, _FakeClient(rpc_handler=_handler))
    out = sb.rpc_rollback_champion("xgboost_v1", "all", "pred-1", "regression", "guardian")
    assert out == "rolled_back"
    assert captured["name"] == "rollback_champion"
    assert captured["params"] == {
        "p_algorithm_family": "xgboost_v1",
        "p_league_scope": "all",
        "p_expected_predecessor_training_run_id": "pred-1",
        "p_reason": "regression",
        "p_rolled_back_by": "guardian",
    }


def test_rpc_returns_already_active(monkeypatch):
    _patch_client(monkeypatch, _FakeClient(rpc_handler=lambda n, p: "already_active"))
    assert sb.rpc_rollback_champion("xgboost_v1", "all", "pred-1", "operator", "x") == "already_active"


def test_rpc_exception_bubbles_up_uncaught(monkeypatch):
    def _handler(name, params):
        raise RuntimeError("rollback_champion: predecessor_mismatch — asteptat X, gasit Y")

    _patch_client(monkeypatch, _FakeClient(rpc_handler=_handler))
    with pytest.raises(RuntimeError, match="predecessor_mismatch"):
        sb.rpc_rollback_champion("xgboost_v1", "all", "pred-1", "operator", "x")
