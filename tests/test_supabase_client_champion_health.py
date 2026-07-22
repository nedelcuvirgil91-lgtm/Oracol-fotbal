"""
Teste pentru supabase_client.get_champion_served_outcomes /
record_champion_health_evaluation / get_recent_champion_health_evaluations
(Stage R2.6, ADR-037) — fără rețea, client Supabase fabricat.

Verifică contractele: degradare grațioasă fără client, INSERT idempotent
(ON CONFLICT DO NOTHING), citirea ferestrelor recente, filtrarea match_history.
"""
import supabase_client as sb


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _Not:
    def __init__(self, q):
        self.q = q

    def is_(self, key, value):
        if value == "null":
            self.q._rows = [r for r in self.q._rows if r.get(key) is not None]
        return self.q


class _FakeSelectQuery:
    def __init__(self, rows):
        self._rows = list(rows)
        self._orders = []   # sortare compusă (ca PostgREST): prima .order() = primară
        self._limit = None

    def select(self, *a, **kw):
        return self

    @property
    def not_(self):
        return _Not(self)

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def gte(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) is not None and str(r.get(key)) >= str(value)]
        return self

    def order(self, key, desc=False):
        self._orders.append((key, desc))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = self._rows
        # Aplică ordinele în REVERS (sort stabil → prima .order() = cheie primară),
        # apoi limit — exact semantica WHERE→ORDER→LIMIT din PostgREST.
        for key, desc in reversed(self._orders):
            rows = sorted(rows, key=lambda r, k=key: (r.get(k) is not None, r.get(k)), reverse=desc)
        if self._limit is not None:
            rows = rows[:self._limit]
        return _FakeResult(rows)


class _FakeUpsert:
    def __init__(self, store, row, on_conflict, ignore_duplicates):
        self.store = store
        self.row = row
        self.on_conflict = on_conflict
        self.ignore_duplicates = ignore_duplicates

    def execute(self):
        # Simulează ON CONFLICT DO NOTHING pe cheia on_conflict.
        keys = (self.on_conflict or "").split(",")
        sig = tuple(self.row.get(k) for k in keys)
        existing = {tuple(r.get(k) for k in keys) for r in self.store["rows"]}
        self.store["calls"].append({
            "row": self.row, "on_conflict": self.on_conflict,
            "ignore_duplicates": self.ignore_duplicates,
        })
        if self.ignore_duplicates and sig in existing:
            return _FakeResult([])  # DO NOTHING
        self.store["rows"].append(dict(self.row))
        return _FakeResult([self.row])


class _FakeTableProxy:
    def __init__(self, rows, store):
        self._rows = rows
        self._store = store

    def select(self, *a, **kw):
        return _FakeSelectQuery(self._rows)

    def upsert(self, row, on_conflict=None, ignore_duplicates=False):
        return _FakeUpsert(self._store, row, on_conflict, ignore_duplicates)


class _FakeClient:
    def __init__(self, tables=None):
        self._tables = tables or {}
        self.store = {"rows": [], "calls": []}

    def table(self, name):
        return _FakeTableProxy(self._tables.get(name, []), self.store)


def _patch(monkeypatch, client):
    monkeypatch.setattr(sb, "get_client", lambda: client)


# ── get_champion_served_outcomes ────────────────────────────────────────────

def test_served_outcomes_empty_without_client(monkeypatch):
    _patch(monkeypatch, None)
    assert sb.get_champion_served_outcomes("xgboost_v1", "all") == []


def test_served_outcomes_only_scoreable(monkeypatch):
    """Doar rânduri cu prob_home_pred ȘI actual_result prezente."""
    client = _FakeClient(tables={"match_history": [
        {"fixture_id": "a", "league": "L", "kickoff_date": "2026-05-01",
         "prob_home_pred": 0.5, "actual_result": "H"},
        {"fixture_id": "b", "league": "L", "kickoff_date": "2026-05-02",
         "prob_home_pred": None, "actual_result": "H"},        # fără predicție
        {"fixture_id": "c", "league": "L", "kickoff_date": "2026-05-03",
         "prob_home_pred": 0.6, "actual_result": None},        # fără rezultat
    ]})
    _patch(monkeypatch, client)
    out = sb.get_champion_served_outcomes("xgboost_v1", "L")
    assert [r["fixture_id"] for r in out] == ["a"]


def test_served_outcomes_league_all_no_filter(monkeypatch):
    client = _FakeClient(tables={"match_history": [
        {"fixture_id": "a", "league": "L1", "kickoff_date": "2026-05-01", "prob_home_pred": 0.5, "actual_result": "H"},
        {"fixture_id": "b", "league": "L2", "kickoff_date": "2026-05-02", "prob_home_pred": 0.5, "actual_result": "D"},
    ]})
    _patch(monkeypatch, client)
    out = sb.get_champion_served_outcomes("xgboost_v1", "all")  # sentinel → fără filtru
    assert {r["fixture_id"] for r in out} == {"a", "b"}


def test_served_outcomes_since_date_filter(monkeypatch):
    client = _FakeClient(tables={"match_history": [
        {"fixture_id": "old", "league": "L", "kickoff_date": "2026-04-01", "prob_home_pred": 0.5, "actual_result": "H"},
        {"fixture_id": "new", "league": "L", "kickoff_date": "2026-06-01", "prob_home_pred": 0.5, "actual_result": "H"},
    ]})
    _patch(monkeypatch, client)
    out = sb.get_champion_served_outcomes("xgboost_v1", "L", since_date="2026-05-01")
    assert [r["fixture_id"] for r in out] == ["new"]


def test_served_outcomes_deterministic_order(monkeypatch):
    """Ordine totală (kickoff_date, fixture_id) — meciuri în aceeași zi."""
    client = _FakeClient(tables={"match_history": [
        {"fixture_id": "z", "league": "L", "kickoff_date": "2026-05-01", "prob_home_pred": 0.5, "actual_result": "H"},
        {"fixture_id": "a", "league": "L", "kickoff_date": "2026-05-01", "prob_home_pred": 0.5, "actual_result": "H"},
        {"fixture_id": "m", "league": "L", "kickoff_date": "2026-04-01", "prob_home_pred": 0.5, "actual_result": "H"},
    ]})
    _patch(monkeypatch, client)
    out = sb.get_champion_served_outcomes("xgboost_v1", "L")
    assert [r["fixture_id"] for r in out] == ["m", "a", "z"]  # dată, apoi fixture_id


# ── record_champion_health_evaluation ───────────────────────────────────────

def test_record_false_without_client(monkeypatch):
    _patch(monkeypatch, None)
    assert sb.record_champion_health_evaluation(
        "run-1", "xgboost_v1", "all", "2026-05-01", 30, "healthy", "trend_only") is False


def test_record_uses_on_conflict_ignore_duplicates(monkeypatch):
    client = _FakeClient()
    _patch(monkeypatch, client)
    ok = sb.record_champion_health_evaluation(
        "run-1", "xgboost_v1", "all", "2026-05-01", 30, "healthy", "trend_only")
    assert ok is True
    call = client.store["calls"][0]
    assert call["on_conflict"] == "training_run_id,n_matches_evaluated"
    assert call["ignore_duplicates"] is True
    assert call["row"]["health_state"] == "healthy"


def test_record_idempotent_same_window(monkeypatch):
    """Aceeași fereastră (training_run_id, n_matches_evaluated) → un singur rând."""
    client = _FakeClient()
    _patch(monkeypatch, client)
    sb.record_champion_health_evaluation("run-1", "xgboost_v1", "all", "2026-05-01", 30, "watch", "trend_only")
    sb.record_champion_health_evaluation("run-1", "xgboost_v1", "all", "2026-05-01", 30, "degrading", "trend_only")
    assert len(client.store["rows"]) == 1  # a doua scriere = no-op (DO NOTHING)


# ── get_recent_champion_health_evaluations ──────────────────────────────────

def test_recent_empty_without_client(monkeypatch):
    _patch(monkeypatch, None)
    assert sb.get_recent_champion_health_evaluations("run-1") == []


def test_recent_ordered_desc_by_n_matches_and_limited(monkeypatch):
    client = _FakeClient(tables={"champion_health_evaluations": [
        {"training_run_id": "run-1", "n_matches_evaluated": 10},
        {"training_run_id": "run-1", "n_matches_evaluated": 30},
        {"training_run_id": "run-1", "n_matches_evaluated": 20},
        {"training_run_id": "other", "n_matches_evaluated": 99},
    ]})
    _patch(monkeypatch, client)
    out = sb.get_recent_champion_health_evaluations("run-1", limit=2)
    assert [r["n_matches_evaluated"] for r in out] == [30, 20]  # DESC, limitat, doar run-1
