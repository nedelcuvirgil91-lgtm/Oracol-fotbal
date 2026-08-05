"""
Teste pentru supabase_client.save_training_run/get_training_run/
get_active_champion (ADR-015) — fără rețea, client Supabase fabricat.
"""
import supabase_client as sb


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeInsertQuery:
    def __init__(self, store, table_name, row):
        self.store = store
        self.table_name = table_name
        self.row = row

    def execute(self):
        self.store.setdefault(self.table_name, []).append(dict(self.row))
        return _FakeResult([self.row])


class _FakeSelectQuery:
    def __init__(self, rows):
        self._rows = rows
        self._single = False

    def select(self, *a, **kw):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def is_(self, key, value):
        # value vine ca "null" (string), simulăm IS NULL
        if value == "null":
            self._rows = [r for r in self._rows if r.get(key) is None]
        return self

    def single(self):
        self._single = True
        return self

    def execute(self):
        if self._single:
            if not self._rows:
                raise Exception("PGRST116: no rows found")
            return _FakeResult(self._rows[0])
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, tables: dict):
        self.tables = tables
        self.inserted: dict[str, list[dict]] = {}

    def table(self, name):
        return _FakeTableProxy(self, name)


class _FakeTableProxy:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def insert(self, row):
        return _FakeInsertQuery(self.client.inserted, self.name, row)

    def select(self, *a, **kw):
        rows = list(self.client.tables.get(self.name, []))
        return _FakeSelectQuery(rows)


def _patch_client(monkeypatch, client):
    monkeypatch.setattr(sb, "get_client", lambda: client)


def test_save_training_run_inserts_row(monkeypatch):
    client = _FakeClient(tables={})
    _patch_client(monkeypatch, client)

    ok = sb.save_training_run(
        training_run_id="run-1", algorithm_name="xgboost_v1", algorithm_version="1",
        league_scope="all", status="trained", samples_used=100,
        walk_forward_metrics={"accuracy": 0.5}, message="ok",
    )
    assert ok is True
    assert client.inserted["training_runs"][0]["training_run_id"] == "run-1"


def test_save_training_run_graceful_without_supabase():
    assert sb.save_training_run(
        training_run_id="x", algorithm_name="a", algorithm_version="1",
        league_scope="all", status="trained", samples_used=0,
        walk_forward_metrics={}, message="",
    ) is False


def test_get_training_run_found(monkeypatch):
    client = _FakeClient(tables={
        "training_runs": [{"training_run_id": "run-1", "status": "trained", "walk_forward_metrics": {"accuracy": 0.5}}],
    })
    _patch_client(monkeypatch, client)
    row = sb.get_training_run("run-1")
    assert row["status"] == "trained"


def test_get_training_run_not_found(monkeypatch):
    client = _FakeClient(tables={"training_runs": []})
    _patch_client(monkeypatch, client)
    assert sb.get_training_run("nope") is None


def test_get_active_champion_none_when_no_champion(monkeypatch):
    client = _FakeClient(tables={"model_champions": []})
    _patch_client(monkeypatch, client)
    assert sb.get_active_champion("xgboost_v1", "all") is None


def test_get_active_champion_returns_active_row(monkeypatch):
    client = _FakeClient(tables={
        "model_champions": [
            {"algorithm_family": "xgboost_v1", "league_scope": "all",
             "training_run_id": "run-1", "superseded_at": None},
            {"algorithm_family": "xgboost_v1", "league_scope": "all",
             "training_run_id": "run-0", "superseded_at": "2026-01-01T00:00:00Z"},
        ],
    })
    _patch_client(monkeypatch, client)
    champ = sb.get_active_champion("xgboost_v1", "all")
    assert champ["training_run_id"] == "run-1"


# ── get_latest_challenger / list_recent_training_runs ──────────────────────
# [ADAUGAT — fix bug Continuous Learning + fix "aplicatia porneste foarte greu"]
# Ambele necesita .order().limit() dupa .eq() — _FakeSelectQuery de mai sus
# nu le suporta (nu erau folosite pana acum) — fake dedicat, minimal, aici.

class _FakeOrderedQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **kw):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def order(self, key, desc=False):
        self._rows = sorted(self._rows, key=lambda r: r.get(key, ""), reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _FakeResult(list(self._rows))


class _FakeOrderedClient:
    def __init__(self, tables: dict):
        self.tables = tables

    def table(self, name):
        return _FakeOrderedQuery(self.tables.get(name, []))


def test_get_latest_challenger_returns_most_recent_any_state(monkeypatch):
    client = _FakeOrderedClient(tables={
        "challengers": [
            {"training_run_id": "old", "algorithm_family": "xgboost_v1", "league_scope": "all",
             "state": "REJECTED", "created_at": "2026-07-01T00:00:00Z"},
            {"training_run_id": "new", "algorithm_family": "xgboost_v1", "league_scope": "all",
             "state": "EVALUATING", "created_at": "2026-08-01T00:00:00Z"},
        ],
    })
    _patch_client(monkeypatch, client)
    result = sb.get_latest_challenger("xgboost_v1", "all")
    assert result["training_run_id"] == "new"


def test_get_latest_challenger_none_when_no_challenger_yet(monkeypatch):
    client = _FakeOrderedClient(tables={"challengers": []})
    _patch_client(monkeypatch, client)
    assert sb.get_latest_challenger("xgboost_v1", "all") is None


def test_get_latest_challenger_graceful_without_supabase():
    assert sb.get_latest_challenger("xgboost_v1", "all") is None


def test_list_recent_training_runs_ordered_newest_first(monkeypatch):
    client = _FakeOrderedClient(tables={
        "training_runs": [
            {"training_run_id": "r1", "algorithm_name": "xgboost_v1", "league_scope": "all",
             "created_at": "2026-07-01T00:00:00Z"},
            {"training_run_id": "r2", "algorithm_name": "xgboost_v1", "league_scope": "all",
             "created_at": "2026-08-01T00:00:00Z"},
        ],
    })
    _patch_client(monkeypatch, client)
    rows = sb.list_recent_training_runs("xgboost_v1", "all")
    assert [r["training_run_id"] for r in rows] == ["r2", "r1"]


def test_list_recent_training_runs_respects_limit(monkeypatch):
    client = _FakeOrderedClient(tables={
        "training_runs": [
            {"training_run_id": f"r{i}", "algorithm_name": "xgboost_v1", "league_scope": "all",
             "created_at": f"2026-08-{i:02d}T00:00:00Z"}
            for i in range(1, 6)
        ],
    })
    _patch_client(monkeypatch, client)
    rows = sb.list_recent_training_runs("xgboost_v1", "all", limit=2)
    assert len(rows) == 2
    assert [r["training_run_id"] for r in rows] == ["r5", "r4"]


def test_list_recent_training_runs_empty_when_none_trained(monkeypatch):
    client = _FakeOrderedClient(tables={"training_runs": []})
    _patch_client(monkeypatch, client)
    assert sb.list_recent_training_runs("xgboost_v1", "all") == []


def test_list_recent_training_runs_graceful_without_supabase():
    assert sb.list_recent_training_runs("xgboost_v1", "all") == []
