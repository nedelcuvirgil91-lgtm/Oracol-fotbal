"""
Teste pentru learning_core.challenger_manager — Pasul 2 din Implementation
Contract (ADR-016). Fără rețea — Supabase fabricat, in-memory, care
reproduce fidel invariantele reale ale schemei (UNIQUE training_run_id,
index unic parțial pe Challenger activ, compare-and-swap la tranziție).

Cerințe de validat:
  1. Crearea unui Challenger reușește, stare inițială CREATED.
  2. Invariantul "cel mult un Challenger activ per (algorithm_family,
     league_scope)" e respectat.
  3. Un nou Challenger poate fi creat după ce precedentul a ajuns terminal.
  4. Tranzițiile valide funcționează (drumul fericit complet).
  5. Tranzițiile invalide ridică ChallengerManagerError, nu se aplică tăcut.
  6. REJECTED cere un motiv valid; celelalte tranziții îl interzic.
  7. Tranziția pe un Challenger inexistent eșuează explicit.
  8. O schimbare concurentă de stare (compare-and-swap eșuat) e detectată.
  9. Modulul rămâne izolat — zero importatori în afara propriilor teste.
"""
import pytest

from learning_core import challenger_manager as cm


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeChallengersTable:
    _ACTIVE_STATES = {"CREATED", "WAITING", "EVALUATING", "SUCCEEDED"}

    def __init__(self, rows: list):
        self._rows = rows
        self._mode = None
        self._insert_payload = None
        self._update_payload = None
        self._filters = []
        self._negate_next = False

    def insert(self, payload):
        self._mode = "insert"
        self._insert_payload = payload
        return self

    def select(self, cols="*"):
        self._mode = "select"
        return self

    def update(self, payload):
        self._mode = "update"
        self._update_payload = payload
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    @property
    def not_(self):
        self._negate_next = True
        return self

    def in_(self, col, values):
        op = "not_in" if self._negate_next else "in"
        self._negate_next = False
        self._filters.append((op, col, list(values)))
        return self

    def _apply_filters(self, rows):
        out = []
        for r in rows:
            ok = True
            for op, col, val in self._filters:
                if op == "eq" and r.get(col) != val:
                    ok = False
                    break
                if op == "in" and r.get(col) not in val:
                    ok = False
                    break
                if op == "not_in" and r.get(col) in val:
                    ok = False
                    break
            if ok:
                out.append(r)
        return out

    def execute(self):
        if self._mode == "insert":
            row = dict(self._insert_payload)
            if any(r["training_run_id"] == row["training_run_id"] for r in self._rows):
                raise Exception(
                    'duplicate key value violates unique constraint "challengers_training_run_id_key"'
                )
            state = row.get("state", "CREATED")
            if state in self._ACTIVE_STATES:
                for r in self._rows:
                    if (r["algorithm_family"] == row["algorithm_family"]
                            and r["league_scope"] == row["league_scope"]
                            and r["state"] in self._ACTIVE_STATES):
                        raise Exception(
                            'duplicate key value violates unique constraint "idx_challengers_active_unique"'
                        )
            row.setdefault("id", len(self._rows) + 1)
            row.setdefault("rejection_reason", None)
            row.setdefault("created_at", "2026-07-14T00:00:00Z")
            row.setdefault("updated_at", "2026-07-14T00:00:00Z")
            row.setdefault("terminal_at", None)
            self._rows.append(row)
            return _FakeResult([row])

        if self._mode == "select":
            return _FakeResult(self._apply_filters(self._rows))

        if self._mode == "update":
            matched = self._apply_filters(self._rows)
            for r in matched:
                r.update(self._update_payload)
            return _FakeResult(matched)

        raise AssertionError("mod necunoscut de query fabricat")


class _FakeSupabaseClient:
    def __init__(self):
        self.challengers_rows: list = []

    def table(self, name):
        assert name == "challengers", f"tabelă neașteptată în fake client: {name!r}"
        return _FakeChallengersTable(self.challengers_rows)


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeSupabaseClient()
    monkeypatch.setattr("supabase_client.get_client", lambda: client)
    return client


def test_create_challenger_success(fake_client):
    challenger = cm.create_challenger("run-1", "xgboost_v1", "all")
    assert challenger["training_run_id"] == "run-1"
    assert challenger["state"] == "CREATED"


def test_create_challenger_rejects_second_active_for_same_pair(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")
    with pytest.raises(cm.ChallengerManagerError, match="există deja un Challenger activ"):
        cm.create_challenger("run-2", "xgboost_v1", "all")


def test_create_challenger_allowed_for_different_league_scope(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")
    challenger_2 = cm.create_challenger("run-2", "xgboost_v1", "premier_league")
    assert challenger_2["state"] == "CREATED"


def test_create_challenger_allowed_after_previous_terminal(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")
    cm.transition("run-1", "REJECTED", rejection_reason="expired")

    challenger_2 = cm.create_challenger("run-2", "xgboost_v1", "all")
    assert challenger_2["state"] == "CREATED"


def test_full_happy_path_transitions(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")

    c = cm.transition("run-1", "WAITING")
    assert c["state"] == "WAITING"

    c = cm.transition("run-1", "EVALUATING")
    assert c["state"] == "EVALUATING"

    c = cm.transition("run-1", "SUCCEEDED")
    assert c["state"] == "SUCCEEDED"

    c = cm.transition("run-1", "PROMOTED")
    assert c["state"] == "PROMOTED"
    assert c["terminal_at"] is not None


def test_transition_evaluating_to_rejected_with_reason(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")
    cm.transition("run-1", "WAITING")
    cm.transition("run-1", "EVALUATING")

    c = cm.transition("run-1", "REJECTED", rejection_reason="verdict_negative")
    assert c["state"] == "REJECTED"
    assert c["rejection_reason"] == "verdict_negative"
    assert c["terminal_at"] is not None


def test_invalid_transition_raises(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")
    with pytest.raises(cm.ChallengerManagerError, match="tranziție invalidă"):
        cm.transition("run-1", "EVALUATING")  # CREATED -> EVALUATING nu e permis direct


def test_promoted_is_terminal_no_further_transition(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")
    cm.transition("run-1", "WAITING")
    cm.transition("run-1", "EVALUATING")
    cm.transition("run-1", "SUCCEEDED")
    cm.transition("run-1", "PROMOTED")

    with pytest.raises(cm.ChallengerManagerError, match="tranziție invalidă"):
        cm.transition("run-1", "WAITING")


def test_rejection_requires_valid_reason(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")
    with pytest.raises(cm.ChallengerManagerError, match="rejection_reason invalid"):
        cm.transition("run-1", "REJECTED", rejection_reason="pentru ca asa am vrut")


def test_rejection_reason_forbidden_for_non_rejected_transition(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")
    with pytest.raises(cm.ChallengerManagerError, match="permis doar la tranziția către REJECTED"):
        cm.transition("run-1", "WAITING", rejection_reason="expired")


def test_transition_nonexistent_challenger_raises(fake_client):
    with pytest.raises(cm.ChallengerManagerError, match="niciun Challenger găsit"):
        cm.transition("run-ghost", "WAITING")


def test_concurrent_state_change_detected_via_compare_and_swap(fake_client):
    cm.create_challenger("run-1", "xgboost_v1", "all")

    # Simuleaza o tranzitie concurenta reala, aplicata direct pe "baza de
    # date" fabricata, intre citirea starii si scrierea din transition().
    fake_client.challengers_rows[0]["state"] = "WAITING"

    # transition() citeste din nou (vede WAITING), calculeaza EVALUATING ca
    # tinta valida -- dar intre timp simulam Ã®nca o schimbare chiar Ã®nainte
    # de scriere, mutand starea manual la un state diferit de cel citit.
    original_update = fake_client.table

    def _table_with_race(name):
        table = original_update(name)
        real_execute = table.execute

        def _execute_with_race():
            if table._mode == "update":
                fake_client.challengers_rows[0]["state"] = "REJECTED"
                fake_client.challengers_rows[0]["rejection_reason"] = "expired"
            return real_execute()

        table.execute = _execute_with_race
        return table

    fake_client.table = _table_with_race

    with pytest.raises(cm.ChallengerManagerError, match="starea s-a schimbat concurent"):
        cm.transition("run-1", "EVALUATING")


def test_get_challenger_and_get_active_challenger(fake_client):
    assert cm.get_challenger("run-1") is None
    assert cm.get_active_challenger("xgboost_v1", "all") is None

    cm.create_challenger("run-1", "xgboost_v1", "all")

    assert cm.get_challenger("run-1")["training_run_id"] == "run-1"
    assert cm.get_active_challenger("xgboost_v1", "all")["training_run_id"] == "run-1"

    cm.transition("run-1", "WAITING")
    cm.transition("run-1", "EVALUATING")
    cm.transition("run-1", "REJECTED", rejection_reason="artifact_dead")

    assert cm.get_active_challenger("xgboost_v1", "all") is None


def test_module_has_single_known_importer():
    """La inchiderea Pasului 2, acest modul avea ZERO importatori de
    productie — invariant valabil doar pana la Pasul 3 (ADR-017), care l-a
    conectat, deliberat si gated printr-un flag dedicat. Dupa addendum-ul
    Chief Architect Review (regula OracleEngine -> Shadow Adapter ->
    ChallengerManager), singurul importator legitim e Shadow Adapter-ul
    (learning_core/challenger_shadow.py) — NU oracle_engine.py direct, care
    trece exclusiv prin adapter (verificat separat, in
    tests/test_challenger_shadow_logging.py). Garda ramane utila sub o
    forma mai stricta: NIMENI altcineva nu are voie sa importe modulul
    direct — un al doilea scriitor necontrolat ar reintroduce exact
    problema de ownership dublu pe care ADR-016 o elimina."""
    import ast
    import pathlib

    ALLOWED_IMPORTERS = {"challenger_shadow.py"}

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        if ".git" in path.parts:
            continue
        if path.name in ("challenger_manager.py", "test_challenger_manager.py"):
            continue
        if path.name in ALLOWED_IMPORTERS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".")[-1] == "challenger_manager" for alias in node.names):
                    offenders.append(str(path.relative_to(root)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[-1] == "challenger_manager" or any(
                    alias.name == "challenger_manager" for alias in node.names
                ):
                    offenders.append(str(path.relative_to(root)))

    assert offenders == [], f"challenger_manager e importat de un scriitor neasteptat: {offenders}"
