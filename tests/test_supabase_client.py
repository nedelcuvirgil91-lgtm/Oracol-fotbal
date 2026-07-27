import supabase_client as sb


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Simulează chain-ul real .table().select().not_.is_().order().range().execute()
    din supabase-py, cu date paginate fabricate - confirmă logica de paginare
    din get_training_data(), fără nevoie de credențiale reale."""
    def __init__(self, all_rows):
        self._all_rows = all_rows
        self._start = 0
        self._end = None

    def select(self, *a, **kw): return self

    @property
    def not_(self): return self

    def is_(self, *a, **kw): return self

    def order(self, *a, **kw): return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        page = self._all_rows[self._start:self._end + 1]
        return _FakeResult(page)


class _FakeClient:
    def __init__(self, all_rows):
        self._all_rows = all_rows

    def table(self, name):
        return _FakeQuery(self._all_rows)


def test_get_training_data_paginates_across_multiple_pages():
    """Regresie directa pe descoperirea reala: Supabase/PostgREST limiteaza
    implicit la 1000 randuri per cerere - confirmat oficial din documentatie.
    Simuleaza 2500 randuri fabricate (peste 2 pagini de 1000) si confirma ca
    get_training_data() le aduce pe TOATE, nu doar primele 1000."""
    fake_rows = [{"fixture_id": f"fx{i}", "actual_result": "H"} for i in range(2500)]
    original_get_client = sb.get_client
    sb.get_client = lambda: _FakeClient(fake_rows)
    try:
        result = sb.get_training_data(only_with_results=True)
        assert len(result) == 2500, f"Asteptam toate cele 2500 - am primit doar {len(result)}"
    finally:
        sb.get_client = original_get_client


def test_get_training_data_stops_at_partial_last_page():
    """Confirma ca bucla se opreste corect cand ultima pagina e partiala
    (< page_size) - nu continua la infinit sau nu rateaza ultimele randuri."""
    fake_rows = [{"fixture_id": f"fx{i}"} for i in range(1543)]  # 1 pagina plina + 543
    original_get_client = sb.get_client
    sb.get_client = lambda: _FakeClient(fake_rows)
    try:
        result = sb.get_training_data(only_with_results=False)
        assert len(result) == 1543
    finally:
        sb.get_client = original_get_client


def test_get_training_data_graceful_without_supabase():
    assert sb.get_training_data() == []


class _FakeSelectAllQuery:
    """Simulează .table().select("*").execute() — fără filtre, pentru
    get_provider_metrics()."""
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **kw): return self

    def execute(self): return _FakeResult(self._rows)


class _FakeClientSelectAll:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _FakeSelectAllQuery(self._rows)


def test_get_provider_metrics_returns_rows():
    """[Diagnostics Dashboard] provider_metrics era scris (record_provider_call)
    dar niciodată citit — confirmă că citirea aduce exact rândurile din tabelă."""
    fake_rows = [
        {"provider": "football_data", "endpoint": "/matches", "calls": 10,
         "errors": 1, "consecutive_failures": 0, "avg_latency_ms": 120.5,
         "last_success": "2026-07-12T10:00:00Z", "last_failure": None},
    ]
    original_get_client = sb.get_client
    sb.get_client = lambda: _FakeClientSelectAll(fake_rows)
    try:
        result = sb.get_provider_metrics()
        assert result == fake_rows
    finally:
        sb.get_client = original_get_client


def test_get_provider_metrics_graceful_without_supabase():
    assert sb.get_provider_metrics() == []


# ── record_provider_call / provider_call_log (ADR-041 Faza 2, Sprint 1.1 #2) ──

class _ChainableQuery:
    """Fake generic pentru lanțul .table().select/insert/update/delete()
    .eq/gte/lt/limit().execute() — suficient pentru record_provider_call(),
    get_provider_call_log(), cleanup_provider_call_log(). Nu simulează SQL
    real, doar înregistrează operațiile și payload-urile, ca testele să
    verifice CE s-a scris/citit, nu cum răspunde Postgres."""

    def __init__(self, table_name, log, select_response=None, raise_on_ops=frozenset()):
        self._table = table_name
        self._log = log
        self._select_response = select_response if select_response is not None else []
        self._raise_on_ops = raise_on_ops

    def select(self, *a, **kw):
        return self

    def insert(self, payload):
        if (self._table, "insert") in self._raise_on_ops:
            raise RuntimeError(f"simulated insert failure on {self._table}")
        self._log.append((self._table, "insert", payload))
        return self

    def update(self, payload):
        if (self._table, "update") in self._raise_on_ops:
            raise RuntimeError(f"simulated update failure on {self._table}")
        self._log.append((self._table, "update", payload))
        return self

    def delete(self):
        self._log.append((self._table, "delete", None))
        return self

    def eq(self, *a, **kw): return self
    def gte(self, *a, **kw): return self
    def lt(self, *a, **kw): return self
    def limit(self, *a, **kw): return self

    def execute(self):
        return _FakeResult(self._select_response)


class _RecordingFakeClient:
    def __init__(self, select_responses=None, raise_on_ops=frozenset()):
        self.log: list[tuple[str, str, dict | None]] = []
        self._select_responses = select_responses or {}
        self._raise_on_ops = raise_on_ops

    def table(self, name):
        return _ChainableQuery(
            name, self.log,
            select_response=self._select_responses.get(name),
            raise_on_ops=self._raise_on_ops,
        )


def _with_fake_client(client, fn):
    original_get_client = sb.get_client
    sb.get_client = lambda: client
    try:
        return fn()
    finally:
        sb.get_client = original_get_client


def test_record_provider_call_inserts_new_row_and_writes_call_log():
    client = _RecordingFakeClient(select_responses={"provider_metrics": []})
    ok = _with_fake_client(client, lambda: sb.record_provider_call(
        "sportapi", "fixtures", True, 120.0,
        http_status=200, failure_reason=None, cache_hit=True,
    ))
    assert ok is True

    metrics_inserts = [entry for entry in client.log if entry[0] == "provider_metrics" and entry[1] == "insert"]
    assert len(metrics_inserts) == 1
    assert metrics_inserts[0][2]["calls"] == 1

    call_log_inserts = [entry for entry in client.log if entry[0] == "provider_call_log" and entry[1] == "insert"]
    assert len(call_log_inserts) == 1
    payload = call_log_inserts[0][2]
    assert payload == {
        "provider": "sportapi", "endpoint": "fixtures", "success": True,
        "http_status": 200, "failure_reason": None, "cache_hit": True,
        "latency_ms": 120.0,
    }


def test_record_provider_call_updates_existing_row_and_writes_call_log():
    existing = {"provider": "sportapi", "endpoint": "fixtures", "calls": 5, "errors": 1,
                "avg_latency_ms": 100.0, "consecutive_failures": 1}
    client = _RecordingFakeClient(select_responses={"provider_metrics": [existing]})
    ok = _with_fake_client(client, lambda: sb.record_provider_call(
        "sportapi", "fixtures", False, 500.0, http_status=503, failure_reason="upstream_5xx",
    ))
    assert ok is True

    metrics_updates = [entry for entry in client.log if entry[0] == "provider_metrics" and entry[1] == "update"]
    assert len(metrics_updates) == 1
    assert metrics_updates[0][2]["calls"] == 6
    assert metrics_updates[0][2]["errors"] == 2

    call_log_inserts = [entry for entry in client.log if entry[0] == "provider_call_log" and entry[1] == "insert"]
    payload = call_log_inserts[0][2]
    assert payload["success"] is False
    assert payload["http_status"] == 503
    assert payload["failure_reason"] == "upstream_5xx"
    assert payload["cache_hit"] is False  # default cand nu e pasat explicit


def test_record_provider_call_defaults_optional_fields_when_not_passed():
    """Apelanții existenți (oracle_api.py/football_providers.py, care nu
    pasează încă http_status/failure_reason/cache_hit) scriu rânduri
    NULL/False — zero eroare, zero schimbare de comportament pentru ei."""
    client = _RecordingFakeClient(select_responses={"provider_metrics": []})
    _with_fake_client(client, lambda: sb.record_provider_call("sportapi", "fixtures", True, 100.0))

    call_log_inserts = [entry for entry in client.log if entry[0] == "provider_call_log" and entry[1] == "insert"]
    payload = call_log_inserts[0][2]
    assert payload["http_status"] is None
    assert payload["failure_reason"] is None
    assert payload["cache_hit"] is False


def test_record_provider_call_returns_true_even_if_call_log_insert_fails():
    """Scrierea în provider_call_log e best-effort — un eșec acolo NU
    trebuie să afecteze rezultatul (provider_metrics deja scris cu succes)."""
    client = _RecordingFakeClient(
        select_responses={"provider_metrics": []},
        raise_on_ops=frozenset({("provider_call_log", "insert")}),
    )
    ok = _with_fake_client(client, lambda: sb.record_provider_call("sportapi", "fixtures", True, 100.0))
    assert ok is True
    metrics_inserts = [entry for entry in client.log if entry[0] == "provider_metrics"]
    assert len(metrics_inserts) == 1  # provider_metrics tot s-a scris


def test_record_provider_call_graceful_without_supabase():
    assert sb.record_provider_call("sportapi", "fixtures", True, 100.0) is False


def test_get_provider_call_log_returns_rows():
    fake_rows = [{"provider": "sportapi", "endpoint": "fixtures", "success": True,
                  "http_status": 200, "failure_reason": None, "cache_hit": False,
                  "latency_ms": 100.0, "called_at": "2026-07-28T10:00:00+00:00"}]
    client = _RecordingFakeClient(select_responses={"provider_call_log": fake_rows})
    result = _with_fake_client(client, lambda: sb.get_provider_call_log("sportapi", 24))
    assert result == fake_rows


def test_get_provider_call_log_graceful_without_supabase():
    assert sb.get_provider_call_log("sportapi", 24) == []


def test_cleanup_provider_call_log_returns_deleted_count():
    deleted_rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    client = _RecordingFakeClient(select_responses={"provider_call_log": deleted_rows})
    count = _with_fake_client(client, lambda: sb.cleanup_provider_call_log(retention_days=9))
    assert count == 3
    deletes = [entry for entry in client.log if entry[0] == "provider_call_log" and entry[1] == "delete"]
    assert len(deletes) == 1


def test_cleanup_provider_call_log_graceful_without_supabase():
    assert sb.cleanup_provider_call_log() == 0
