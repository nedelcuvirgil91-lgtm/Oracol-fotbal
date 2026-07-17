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
