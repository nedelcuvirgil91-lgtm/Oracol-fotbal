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
