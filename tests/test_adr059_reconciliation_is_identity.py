"""
Garzi pentru ADR-059 — "Reconcilierea identitatii este o operatie de identitate,
nu de date".

Acesta e testul care conteaza cel mai mult din tot ADR-059: modul EXECUTE scrie
in productie, iar singura lui autorizare vine din faptul ca suprafata de
scriere e minuscula si demonstrabila. Aici se demonstreaza.

Trei familii:
  (A) SUPRAFATA DE SCRIERE — EXECUTE atinge EXCLUSIV cele 3 coloane de audit,
      exclusiv pe randul NECANONIC. Verificat prin captarea fiecarui apel de
      scriere, nu prin inspectia rezultatului.
  (B) GARDA STRUCTURALA (AST) — `process_group()` nu are voie sa mai contina
      nicio cale prin care o VALOARE de date sa ajunga in decizie. O
      reintroducere accidentala a contopirii pica aici, chiar daca testele de
      comportament ar fi ajustate sa treaca.
  (C) COMPLETITUDINEA MODELULUI DE OWNERSHIP — fiecare coloana observata are un
      owner, si niciun owner nu revendica o coloana de audit a reconcilierii.

Fara retea, fara Supabase.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from services.match_identity_reconciliation_service import (
    OBSERVED_DATA_COLUMNS,
    RECONCILIATION_OWNED_COLUMNS,
    MatchIdentityReconciliationService,
    column_owner,
    process_group,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICE_PATH = REPO_ROOT / "services" / "match_identity_reconciliation_service.py"


# ════════════════════════════════════════════════════════════════════════
# Client fals care CAPTEAZA fiecare scriere
# ════════════════════════════════════════════════════════════════════════

class _CapturingTable:
    def __init__(self, rows, writes):
        self._rows = rows
        self._writes = writes
        self._filters = []
        self._payload = None

    def select(self, cols):
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def upsert(self, *a, **kw):
        raise AssertionError("Reconcilierea nu are voie sa apeleze upsert()")

    def insert(self, *a, **kw):
        raise AssertionError("Reconcilierea nu are voie sa apeleze insert()")

    def delete(self, *a, **kw):
        raise AssertionError("Reconcilierea nu are voie sa apeleze delete()")

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def in_(self, col, values):
        self._filters.append(("in", col, set(values)))
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        if self._payload is not None:
            self._writes.append({"payload": dict(self._payload), "filters": list(self._filters)})

            class _R:
                data = []
            return _R()

        rows = self._rows
        for f in self._filters:
            if f[0] == "is" and f[1] == "superseded_by":
                rows = [r for r in rows if r.get("superseded_by") is None]
            elif f[0] == "in":
                rows = [r for r in rows if r.get(f[1]) in f[2]]
            elif f[0] == "eq":
                rows = [r for r in rows if r.get(f[1]) == f[2]]
        if hasattr(self, "_range"):
            s, e = self._range
            rows = rows[s:e + 1]

        class _R:
            pass
        r = _R()
        r.data = rows
        return r


class _CapturingClient:
    def __init__(self, rows, writes):
        self._rows = rows
        self._writes = writes

    def table(self, name):
        assert name == "match_history", f"Reconcilierea a atins tabela {name!r}"
        return _CapturingTable(self._rows, self._writes)

    def rpc(self, *a, **kw):
        raise AssertionError("Reconcilierea nu are voie sa apeleze rpc()")


class _CapturingSb:
    def __init__(self, rows):
        self.rows = rows
        self.writes: list[dict] = []

    def get_client(self):
        return _CapturingClient(self.rows, self.writes)


def _row(id, fixture_id, home="Alpha", away="Beta", date="2026-02-01",
         result="H", hg=1, ag=0, **extra):
    base = {
        "id": id, "fixture_id": fixture_id, "home_team": home, "away_team": away,
        "kickoff_date": date, "actual_result": result,
        "actual_home_goals": hg, "actual_away_goals": ag, "superseded_by": None,
    }
    base.update(extra)
    return base


def _pair(canonical=None, noncanonical=None):
    """Un grup de 2 randuri: canonic = fd (rang mai bun), necanonic = kaggle.

    Pentru a produce un GOL de date, valoarea trebuie sa fie pe randul
    NECANONIC si sa lipseasca de pe cel canonic — de aceea cele doua seturi de
    campuri sunt explicit separate aici, nu impartite pe ambele randuri."""
    return [
        _row(1, "fd_1", **(canonical or {})),
        _row(2, "kaggle_1", **(noncanonical or {})),
    ]


# ════════════════════════════════════════════════════════════════════════
# (A) SUPRAFATA DE SCRIERE
# ════════════════════════════════════════════════════════════════════════

def test_execute_writes_only_the_three_audit_columns():
    """INVARIANTA CENTRALA ADR-059. Orice coloana in plus in payload inseamna
    ca reconcilierea a redevenit un al doilea scriitor."""
    sb = _CapturingSb(_pair(noncanonical={"home_shots": 8}))
    MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False)

    assert sb.writes, "EXECUTE nu a scris nimic — testul si-a pierdut subiectul"
    for w in sb.writes:
        assert set(w["payload"]) == set(RECONCILIATION_OWNED_COLUMNS), (
            f"EXECUTE a scris coloane neautorizate: "
            f"{sorted(set(w['payload']) - set(RECONCILIATION_OWNED_COLUMNS))}"
        )


def test_execute_never_writes_any_observed_data_column():
    """Formularea complementara: niciuna dintre cele 52 de coloane observate nu
    are voie sa apara vreodata intr-un payload de scriere."""
    sb = _CapturingSb(_pair(noncanonical={"home_shots": 8, "home_elo": 1500, "home_xg_pred": 1.4}))
    MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False)

    for w in sb.writes:
        leaked = set(w["payload"]) & set(OBSERVED_DATA_COLUMNS)
        assert not leaked, f"EXECUTE a scris coloane de date: {sorted(leaked)}"


def test_execute_touches_only_the_noncanonical_row():
    """Randul canonic nu e atins de niciun octet (ADR-059 §Decizie 2)."""
    sb = _CapturingSb(_pair(noncanonical={"home_shots": 8}))
    report = MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False)

    targeted = {f[2] for w in sb.writes for f in w["filters"] if f[0] == "eq" and f[1] == "id"}
    assert targeted == {2}, f"EXECUTE a tintit si alte randuri decat necanonicul: {targeted}"
    assert report.rows_marked_superseded == 1


def test_execute_write_is_guarded_by_superseded_by_is_null():
    """Idempotenta: un rand deja marcat nu e re-marcat, deci o reluare dupa un
    esec partial nu suprascrie marcajul anterior si nu-i schimba `superseded_at`."""
    sb = _CapturingSb(_pair())
    MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False)

    for w in sb.writes:
        assert ("is", "superseded_by", "null") in w["filters"], (
            "scrierea nu e gatata de `superseded_by is null` — reluarea ar fi distructiva"
        )


def test_execute_payload_points_at_the_canonical_row():
    sb = _CapturingSb(_pair())
    MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False)
    assert sb.writes[0]["payload"]["superseded_by"] == 1
    assert "duplicate_cross_provider" in sb.writes[0]["payload"]["superseded_reason"]


def test_dry_run_writes_nothing_at_all():
    sb = _CapturingSb(_pair(noncanonical={"home_shots": 8}))
    report = MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=True)
    assert sb.writes == []
    assert report.rows_marked_superseded == 0
    # ...dar golul e raportat.
    assert report.canonical_rows_with_data_gap == 1


def test_hard_conflict_group_is_never_written():
    rows = [_row(1, "fd_1", result="H"), _row(2, "kaggle_1", result="A")]
    sb = _CapturingSb(rows)
    report = MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False)
    assert sb.writes == []
    assert report.excluded_hard_conflict_count == 1


def test_unknown_source_group_is_never_written():
    rows = [_row(1, "fd_1"), _row(2, "opta_1")]
    sb = _CapturingSb(rows)
    report = MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False)
    assert sb.writes == []
    assert report.excluded_unknown_source_count == 1


def test_limit_groups_caps_the_pilot():
    """ADR-025 Faza 3 cere un pilot pe subset izolat. Plafonul trebuie sa
    limiteze SCRIERILE, nu doar raportarea."""
    rows = []
    for i in range(5):
        rows.append(_row(10 + i, f"fd_{i}", home=f"H{i}", away=f"A{i}", date="2026-03-01"))
        rows.append(_row(20 + i, f"kaggle_{i}", home=f"H{i}", away=f"A{i}", date="2026-03-01"))
    sb = _CapturingSb(rows)
    report = MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False, limit_groups=2)

    assert len(sb.writes) == 2
    assert report.rows_marked_superseded == 2
    assert report.total_groups == 5  # descoperirea vede tot; doar scrierea e plafonata


def test_pilot_is_reproducible_same_groups_every_run():
    """Grupurile se proceseaza in ordine sortata a cheii naturale, deci un
    pilot cu acelasi plafon atinge exact aceleasi randuri la fiecare rulare —
    altfel "pilotul verificat manual" din ADR-025 n-ar insemna nimic."""
    def _mk():
        rows = []
        for i in range(5):
            rows.append(_row(10 + i, f"fd_{i}", home=f"H{i}", away=f"A{i}", date="2026-03-01"))
            rows.append(_row(20 + i, f"kaggle_{i}", home=f"H{i}", away=f"A{i}", date="2026-03-01"))
        return rows

    targets = []
    for _ in range(2):
        sb = _CapturingSb(_mk())
        MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=False, limit_groups=2)
        targets.append([f[2] for w in sb.writes for f in w["filters"] if f[0] == "eq" and f[1] == "id"])
    assert targets[0] == targets[1]


def test_write_failure_on_one_group_does_not_abort_the_rest():
    """Rollback Strategy ADR-025: un esec partial trebuie sa lase restul
    procesabil, iar erorile sa fie raportate, nu inghitite."""
    rows = []
    for i in range(3):
        rows.append(_row(10 + i, f"fd_{i}", home=f"H{i}", away=f"A{i}", date="2026-03-01"))
        rows.append(_row(20 + i, f"kaggle_{i}", home=f"H{i}", away=f"A{i}", date="2026-03-01"))

    sb = _CapturingSb(rows)
    original = sb.get_client

    calls = {"n": 0}

    class _FlakySb:
        rows = sb.rows
        writes = sb.writes

        def get_client(self):
            client = original()
            real_table = client.table

            def table(name):
                t = real_table(name)
                real_execute = t.execute

                def execute():
                    if t._payload is not None:
                        calls["n"] += 1
                        if calls["n"] == 2:
                            raise RuntimeError("eroare simulata de retea")
                    return real_execute()

                t.execute = execute
                return t

            client.table = table
            return client

    report = MatchIdentityReconciliationService(supabase_client=_FlakySb()).run(dry_run=False)

    assert len(report.write_errors) == 1
    assert report.rows_marked_superseded == 2  # celelalte doua au trecut
    assert report.reconciled_groups == 3


# ════════════════════════════════════════════════════════════════════════
# (B) GARDA STRUCTURALA (AST)
# ════════════════════════════════════════════════════════════════════════

def _process_group_ast() -> ast.FunctionDef:
    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "process_group":
            return node
    raise AssertionError("process_group() nu a fost gasita — garda AST a murit")


def test_process_group_never_reads_a_data_value_into_the_decision():
    """Garda structurala. Contopirea presupune obligatoriu citirea unei VALORI
    dintr-un rand necanonic (`row[col]` / `row.get(col)`) si punerea ei in
    decizie. Sub ADR-059, `process_group()` are voie sa citeasca valorile
    coloanelor observate DOAR ca test `is not None`, niciodata sa le
    transporte. Acest test verifica structural ca nicio valoare nu e atribuita
    intr-un camp al deciziei."""
    fn = _process_group_ast()

    offenders = []
    for node in ast.walk(fn):
        # decision.<camp>[...] = <expr>  — singura forma prin care o valoare ar
        # putea ajunge in decizie.
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                val = target.value
                if not (isinstance(val, ast.Attribute)
                        and isinstance(val.value, ast.Name)
                        and val.value.id == "decision"):
                    continue
                # Partea dreapta are voie sa fie DOAR un apel `column_owner(...)`.
                rhs = node.value
                ok = (isinstance(rhs, ast.Call)
                      and isinstance(rhs.func, ast.Name)
                      and rhs.func.id == "column_owner")
                if not ok:
                    offenders.append(ast.dump(node)[:160])

    assert not offenders, (
        "process_group() atribuie in decizie ceva care nu e `column_owner(...)` — "
        "contopirea a fost reintrodusa (ADR-059): " + "; ".join(offenders)
    )


def test_group_decision_has_no_merge_updates_field():
    """`merge_updates` a fost eliminat ca CAMP, nu doar ocolit. Verificat pe
    structura clasei, nu prin cautare de text — o mentiune in comentariu
    (istoricul deciziei) e legitima si nu trebuie sa pice testul."""
    tree = ast.parse(SERVICE_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "GroupDecision":
            fields = {
                n.target.id for n in node.body
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
            }
            assert "merge_updates" not in fields, (
                "GroupDecision are inca `merge_updates` — ADR-059 il elimina"
            )
            assert "data_gaps" in fields, "GroupDecision nu are `data_gaps`"
            return
    raise AssertionError("GroupDecision nu a fost gasita")


# ════════════════════════════════════════════════════════════════════════
# (C) COMPLETITUDINEA MODELULUI DE OWNERSHIP
# ════════════════════════════════════════════════════════════════════════

def test_every_observed_column_has_an_owner():
    for col in OBSERVED_DATA_COLUMNS:
        owner = column_owner(col)
        assert owner, f"coloana observata {col!r} nu are owner"
        assert owner in {"run_backfill", "stats_sync", "_cache_prediction", "import_sources"}, (
            f"owner necunoscut {owner!r} pentru {col!r}"
        )


def test_no_observed_column_is_an_audit_column():
    """Coloanele de audit ale reconcilierii nu au voie sa fie si observate —
    altfel reconcilierea ar raporta un gol pe propriile coloane."""
    overlap = set(OBSERVED_DATA_COLUMNS) & set(RECONCILIATION_OWNED_COLUMNS)
    assert not overlap, f"suprapunere audit/date: {sorted(overlap)}"


def test_backfill_owned_columns_match_the_real_backfill_list():
    """Maparea coloana->owner nu e scrisa din memorie: trebuie sa corespunda
    listei reale `BACKFILL_COLUMNS` din codul de backfill. Daca acolo se adauga
    o coloana noua, maparea de aici trebuie actualizata — testul o semnaleaza."""
    from sync.backfill_features import BACKFILL_COLUMNS

    for col in BACKFILL_COLUMNS:
        if col in OBSERVED_DATA_COLUMNS:
            assert column_owner(col) == "run_backfill", (
                f"{col!r} e in BACKFILL_COLUMNS dar maparea il da lui "
                f"{column_owner(col)!r}"
            )


def test_prediction_outputs_are_attributed_to_cache_prediction():
    """ADR-036 Stage 1: iesirile de predictie sunt owner-ate de _cache_prediction.
    Exact cele 11 coloane gasite de dry-run-ul real din 2026-08-21."""
    for col in ("home_xg_pred", "away_xg_pred", "prob_home_pred", "prob_draw_pred",
                "prob_away_pred", "mc_prob_home", "mc_prob_draw", "mc_prob_away",
                "weather_penalty", "home_data_quality", "away_data_quality"):
        assert column_owner(col) == "_cache_prediction", col


def test_backfill_owned_columns_are_never_attributed_to_prediction():
    """Regresia D3.5 in forma ei originala: cele 10 coloane care erau scrise
    concurent de _save_prediction si run_backfill nu au voie sa fie atribuite
    Prediction Engine-ului."""
    from tests.test_canonical_feature_ownership import BACKFILL_OWNED_CONFLICT

    for col in BACKFILL_OWNED_CONFLICT:
        assert column_owner(col) == "run_backfill", col


def test_dry_run_reports_the_plan_without_executing_it():
    """`rows_to_mark` e planul (numarat in ambele moduri); `rows_marked_superseded`
    numara doar scrierile chiar efectuate. In DRY-RUN, planul exista si executia
    e zero — asta face raportul util inainte de a autoriza scrierea."""
    sb = _CapturingSb(_pair(noncanonical={"home_shots": 8}))
    report = MatchIdentityReconciliationService(supabase_client=sb).run(dry_run=True)
    assert report.rows_to_mark == 1
    assert report.rows_marked_superseded == 0
    assert sb.writes == []


def test_gap_between_plan_and_execution_equals_write_failures():
    """Dupa un EXECUTE, `rows_to_mark - rows_marked_superseded` trebuie sa fie
    exact numarul de esecuri — altfel raportul ar putea ascunde scrieri ratate."""
    rows = []
    for i in range(3):
        rows.append(_row(10 + i, f"fd_{i}", home=f"H{i}", away=f"A{i}", date="2026-03-01"))
        rows.append(_row(20 + i, f"kaggle_{i}", home=f"H{i}", away=f"A{i}", date="2026-03-01"))

    sb = _CapturingSb(rows)
    original = sb.get_client
    calls = {"n": 0}

    class _FlakySb:
        rows = sb.rows
        writes = sb.writes

        def get_client(self):
            client = original()
            real_table = client.table

            def table(name):
                t = real_table(name)
                real_execute = t.execute

                def execute():
                    if t._payload is not None:
                        calls["n"] += 1
                        if calls["n"] == 2:
                            raise RuntimeError("eroare simulata")
                    return real_execute()

                t.execute = execute
                return t

            client.table = table
            return client

    report = MatchIdentityReconciliationService(supabase_client=_FlakySb()).run(dry_run=False)
    assert report.rows_to_mark - report.rows_marked_superseded == len(report.write_errors)
