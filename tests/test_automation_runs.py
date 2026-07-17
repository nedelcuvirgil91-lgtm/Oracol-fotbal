"""
Teste pentru automation_runs.py (ADR-026) — substratul comun de raportare
pentru procesele autonome. Verifică exact contractul înghețat: tranzițiile
de stare, idempotency (reuse/new/ignore), și regula "rollback ca precondiție
structurală" pentru T3a.

Fake client, fără rețea/Supabase live — mimichează exact lanțurile de apeluri
folosite (table().select()/.insert()/.update()...eq()/.in_()/.limit().execute()).
"""
import pytest

import automation_runs as ar


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    """Simulează un query builder PostgREST minimal, suficient pentru
    apelurile folosite în automation_runs.py."""

    def __init__(self, table, op, payload=None):
        self.table = table
        self.op = op          # "select" | "insert" | "update"
        self.payload = payload
        self.filters = {}     # col -> val (eq)
        self.in_filters = {}  # col -> list
        self.lt_filters = {}  # col -> val
        self._limit = None
        self._order_col = None
        self._order_desc = False

    def eq(self, col, val):
        self.filters[col] = val
        return self

    def in_(self, col, vals):
        self.in_filters[col] = list(vals)
        return self

    def lt(self, col, val):
        self.lt_filters[col] = val
        return self

    def limit(self, n):
        self._limit = n
        return self

    def order(self, col, desc=False):
        self._order_col = col
        self._order_desc = desc
        return self

    def execute(self):
        return self.table._run(self)


class _FakeTable:
    def __init__(self, name, store, next_id):
        self.name = name
        self.store = store  # list[dict], référence partagée
        self._next_id = next_id  # mutable container [int]

    def select(self, cols):
        return _FakeQuery(self, "select")

    def insert(self, payload):
        return _FakeQuery(self, "insert", payload)

    def update(self, payload):
        return _FakeQuery(self, "update", payload)

    def _matches(self, row, q: _FakeQuery):
        for col, val in q.filters.items():
            if row.get(col) != val:
                return False
        for col, vals in q.in_filters.items():
            if row.get(col) not in vals:
                return False
        for col, val in q.lt_filters.items():
            rv = row.get(col)
            if rv is None or not (rv < val):
                return False
        return True

    def _run(self, q: _FakeQuery):
        if q.op == "insert":
            row = dict(q.payload)
            row["id"] = self._next_id[0]
            self._next_id[0] += 1
            row.setdefault("status", row.get("status"))
            self.store.append(row)
            return _Result([row])

        if q.op == "update":
            matched = [r for r in self.store if self._matches(r, q)]
            for r in matched:
                r.update(q.payload)
            return _Result(matched)

        # select
        matched = [r for r in self.store if self._matches(r, q)]
        if q._order_col:
            matched = sorted(matched, key=lambda r: r.get(q._order_col) or "", reverse=q._order_desc)
        if q._limit is not None:
            matched = matched[: q._limit]
        return _Result(matched)


class _FakeClient:
    def __init__(self):
        self._tables = {}
        self._next_id = {"automation_runs": [1], "decision_feed": [1]}

    def table(self, name):
        if name not in self._tables:
            self._tables[name] = ([], self._next_id.setdefault(name, [1]))
        store, next_id = self._tables[name]
        return _FakeTable(name, store, next_id)


@pytest.fixture()
def client(monkeypatch):
    c = _FakeClient()
    monkeypatch.setattr(ar, "get_client", lambda: c)
    return c


# ════════════════════════════════════════════════════════════════════════
# automation_runs — execuție
# ════════════════════════════════════════════════════════════════════════

def test_write_run_creates_queued_row(client):
    run_id = ar.write_run("ADR-027", "schema_drift_check", "T1")
    assert run_id is not None
    row = client.table("automation_runs")._run(
        _FakeQuery(client.table("automation_runs"), "select").eq("id", run_id)
    ).data[0]
    assert row["status"] == "queued"
    assert row["producer"] == "ADR-027"


def test_write_run_reuses_existing_open_run_for_same_target_key(client):
    run_id_1 = ar.write_run("ADR-030", "retrain", "T2", target_key="xgboost_v1|PL")
    run_id_2 = ar.write_run("ADR-030", "retrain", "T2", target_key="xgboost_v1|PL")
    assert run_id_1 == run_id_2, "duplicat concurent trebuie reutilizat, nu o rulare noua"


def test_write_run_allows_new_run_after_previous_completed(client):
    run_id_1 = ar.write_run("ADR-030", "retrain", "T2", target_key="xgboost_v1|PL")
    ar.complete_run(run_id_1)
    run_id_2 = ar.write_run("ADR-030", "retrain", "T2", target_key="xgboost_v1|PL")
    assert run_id_2 != run_id_1, "dupa completed, o rulare noua e permisa"


def test_run_lifecycle_transitions(client):
    run_id = ar.write_run("ADR-028", "recalibration_fit", "T2")
    assert ar.start_run(run_id)
    assert ar.complete_run(run_id, summary={"samples": 210})
    row = client.table("automation_runs")._run(
        _FakeQuery(client.table("automation_runs"), "select").eq("id", run_id)
    ).data[0]
    assert row["status"] == "completed"
    assert row["summary"] == {"samples": 210}


def test_skip_run_is_not_an_error_state(client):
    run_id = ar.write_run("ADR-030", "retrain", "T2")
    assert ar.skip_run(run_id, "insuficiente meciuri noi")
    row = client.table("automation_runs")._run(
        _FakeQuery(client.table("automation_runs"), "select").eq("id", run_id)
    ).data[0]
    assert row["status"] == "skipped"
    assert row["skip_reason"] == "insuficiente meciuri noi"


# ════════════════════════════════════════════════════════════════════════
# decision_feed — regula de rollback ca precondiție structurală
# ════════════════════════════════════════════════════════════════════════

def test_propose_t3a_decision_requires_rollback_plan(client):
    run_id = ar.write_run("ADR-030", "retrain", "T3a")
    with pytest.raises(ValueError, match="rollback_plan"):
        ar.propose_decision(run_id, tier="T3a", rollback_plan=None)


def test_propose_t3a_decision_with_rollback_plan_succeeds(client):
    run_id = ar.write_run("ADR-030", "retrain", "T3a")
    decision_id = ar.propose_decision(
        run_id, tier="T3a",
        rollback_plan="revert la campionul anterior din model_champions",
        evidence={"brier_delta": -0.02},
        correction_method="none — pre-ADR-034",
    )
    assert decision_id is not None


def test_propose_t3b_signal_does_not_require_rollback_plan(client):
    run_id = ar.write_run("ADR-027", "schema_drift_ambiguous", "T3b")
    decision_id = ar.propose_decision(run_id, tier="T3b", evidence={"note": "drift ambiguu"})
    assert decision_id is not None


# ════════════════════════════════════════════════════════════════════════
# decision_feed — idempotency (decizie reutilizată, nu duplicată)
# ════════════════════════════════════════════════════════════════════════

def test_propose_decision_reuses_open_decision_for_same_target_key(client):
    run_id_1 = ar.write_run("ADR-030", "retrain", "T3a", target_key="xgboost_v1|PL")
    d1 = ar.propose_decision(run_id_1, tier="T3a", rollback_plan="revert campion")
    ar.complete_run(run_id_1)

    run_id_2 = ar.write_run("ADR-030", "retrain", "T3a", target_key="xgboost_v1|PL")
    d2 = ar.propose_decision(run_id_2, tier="T3a", rollback_plan="revert campion",
                              evidence={"brier_delta": -0.03})
    assert d1 == d2, "decizie deja deschisa pentru aceeasi cheie trebuie reutilizata, nu duplicata"


# ════════════════════════════════════════════════════════════════════════
# decision_feed — ciclul de viață complet
# ════════════════════════════════════════════════════════════════════════

def test_decision_full_lifecycle_approve_and_commit(client):
    run_id = ar.write_run("ADR-030", "retrain", "T3a")
    decision_id = ar.propose_decision(run_id, tier="T3a", rollback_plan="revert campion")
    assert ar.surface_decision(decision_id)
    assert ar.approve_decision(decision_id, resolved_by="owner")
    assert ar.commit_decision(decision_id)

    row = client.table("decision_feed")._run(
        _FakeQuery(client.table("decision_feed"), "select").eq("id", decision_id)
    ).data[0]
    assert row["status"] == "committed"


def test_commit_failure_is_not_lost_silently(client):
    run_id = ar.write_run("ADR-030", "retrain", "T3a")
    decision_id = ar.propose_decision(run_id, tier="T3a", rollback_plan="revert campion")
    ar.surface_decision(decision_id)
    ar.approve_decision(decision_id, resolved_by="owner")
    assert ar.fail_decision_commit(decision_id, "RPC promote_challenger a esuat")

    row = client.table("decision_feed")._run(
        _FakeQuery(client.table("decision_feed"), "select").eq("id", decision_id)
    ).data[0]
    assert row["status"] == "commit_failed"
    assert "esuat" in row["commit_error"]


# ════════════════════════════════════════════════════════════════════════
# Staleness sweep — niciodată echivalent cu aprobare/respingere tacită
# ════════════════════════════════════════════════════════════════════════

def test_sweep_expires_stale_pending_decisions_not_as_approval_or_rejection(client):
    run_id = ar.write_run("ADR-032", "reconciliation", "T3a")
    decision_id = ar.propose_decision(run_id, tier="T3a", rollback_plan="revert merge")
    ar.surface_decision(decision_id)
    # simuleaza TTL depasit (in trecut)
    client.table("decision_feed").update({"ttl_at": "2020-01-01T00:00:00+00:00"}).eq(
        "id", decision_id
    ).execute()

    expired, orphaned = ar.sweep_stale_decisions()
    assert expired == 1

    row = client.table("decision_feed")._run(
        _FakeQuery(client.table("decision_feed"), "select").eq("id", decision_id)
    ).data[0]
    assert row["status"] == "expired"
    assert row["status"] not in ("approved", "rejected"), (
        "expirarea nu are voie sa fie echivalenta cu o decizie umana"
    )


def test_sweep_orphans_stale_approved_decisions(client):
    run_id = ar.write_run("ADR-030", "retrain", "T3a")
    decision_id = ar.propose_decision(run_id, tier="T3a", rollback_plan="revert campion")
    ar.surface_decision(decision_id)
    ar.approve_decision(decision_id, resolved_by="owner")
    client.table("decision_feed").update({"ttl_at": "2020-01-01T00:00:00+00:00"}).eq(
        "id", decision_id
    ).execute()

    expired, orphaned = ar.sweep_stale_decisions()
    assert orphaned == 1

    row = client.table("decision_feed")._run(
        _FakeQuery(client.table("decision_feed"), "select").eq("id", decision_id)
    ).data[0]
    assert row["status"] == "orphaned"


# ════════════════════════════════════════════════════════════════════════
# Citire — Activity Log / Decision Feed
# ════════════════════════════════════════════════════════════════════════

def test_list_recent_runs_returns_all_regardless_of_tier(client):
    ar.write_run("ADR-027", "schema_drift_check", "T1")
    ar.write_run("ADR-028", "recalibration_fit", "T2")
    runs = ar.list_recent_runs(limit=10)
    assert len(runs) == 2


def test_list_pending_decisions_empty_when_only_proposed(client):
    """Decision Feed gol implicit — proprietatea de design cea mai importantă.
    O decizie doar 'proposed' (nesurfaced) nu apare încă în feed."""
    run_id = ar.write_run("ADR-030", "retrain", "T3a")
    ar.propose_decision(run_id, tier="T3a", rollback_plan="revert campion")
    assert ar.list_pending_decisions() == []


def test_list_pending_decisions_shows_surfaced_items(client):
    run_id = ar.write_run("ADR-032", "reconciliation", "T3a")
    decision_id = ar.propose_decision(run_id, tier="T3a", rollback_plan="revert merge")
    assert ar.list_pending_decisions() == []
    ar.surface_decision(decision_id)
    pending = ar.list_pending_decisions()
    assert len(pending) == 1
    assert pending[0]["id"] == decision_id
