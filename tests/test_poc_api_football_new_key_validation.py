"""Teste pentru sync/poc_api_football_new_key_validation.py — Etapa C,
Regula 1/2 (aprobate explicit, 2026-07-27).

Gardă AST: dovedește structural izolarea cerută (nu doar prin convenție):
  - nu importă key_manager / football_providers
  - nu citește niciodată API_FOOTBALL_KEY (cea veche), doar API_FOOTBALL_KEY_NEW

Restul: teste pure pe funcțiile de comparație structurală (fără rețea) și pe
plafonul de apeluri (CallBudget)."""
from __future__ import annotations

import ast
import inspect
import textwrap

import sync.poc_api_football_new_key_validation as mod


def test_module_never_imports_key_manager_or_football_providers():
    src = inspect.getsource(mod)
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert "key_manager" not in imported
    assert "football_providers" not in imported


def test_module_never_reads_old_key_env_var():
    """Gardă structurală: singurul argument literal permis pentru
    os.environ.get(...)/os.environ[...] e API_FOOTBALL_KEY_NEW — niciodată
    API_FOOTBALL_KEY (cea veche, neatinsă)."""
    src = inspect.getsource(mod)
    tree = ast.parse(src)

    # Rezolvă constantele module-level (ex. NEW_KEY_ENV_VAR = "API_FOOTBALL_KEY_NEW")
    # ca să prindă și referințele indirecte, nu doar literalii inline.
    module_constants: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    module_constants[target.id] = node.value.value

    def _resolve(value_node: ast.AST):
        if isinstance(value_node, ast.Constant):
            return value_node.value
        if isinstance(value_node, ast.Name) and value_node.id in module_constants:
            return module_constants[value_node.id]
        return None

    read_env_vars: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            is_environ_get = (
                isinstance(func, ast.Attribute) and func.attr == "get"
                and isinstance(func.value, ast.Attribute) and func.value.attr == "environ"
            )
            if is_environ_get and node.args:
                resolved = _resolve(node.args[0])
                if resolved is not None:
                    read_env_vars.add(resolved)
        elif isinstance(node, ast.Subscript):
            val = node.value
            if isinstance(val, ast.Attribute) and val.attr == "environ":
                resolved = _resolve(node.slice)
                if resolved is not None:
                    read_env_vars.add(resolved)

    assert read_env_vars == {"API_FOOTBALL_KEY_NEW"}, (
        f"Modulul citește variabile de mediu neașteptate: {read_env_vars} — "
        "singura permisă e API_FOOTBALL_KEY_NEW"
    )


def test_module_not_imported_by_any_production_code():
    """Precedent: fișierele poc_* nu sunt niciodată importate în afara altor
    poc_*/teste — verificare simplă de siguranță, nu doar convenție."""
    import pathlib
    repo_root = pathlib.Path(mod.__file__).resolve().parent.parent
    offenders = []
    for py_file in repo_root.rglob("*.py"):
        if "poc_" in py_file.name or "/tests/" in str(py_file) or "/.git/" in str(py_file):
            continue
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if "poc_api_football_new_key_validation" in text:
            offenders.append(str(py_file))
    assert offenders == [], f"Fișiere de producție care referențiază POC-ul: {offenders}"


def test_get_new_key_reads_only_the_new_env_var(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY_NEW", raising=False)
    monkeypatch.setenv("API_FOOTBALL_KEY", "veche-nu-trebuie-citita")
    assert mod._get_new_key() is None

    monkeypatch.setenv("API_FOOTBALL_KEY_NEW", "  noua-cheie  ")
    assert mod._get_new_key() == "noua-cheie"


# ── CallBudget ───────────────────────────────────────────────────────────

def test_call_budget_never_exceeds_hard_ceiling():
    budget = mod.CallBudget(max_calls=999)
    assert budget.max_calls == mod._HARD_CEILING


def test_call_budget_negative_clamped_to_zero():
    budget = mod.CallBudget(max_calls=-5)
    assert budget.max_calls == 0
    assert budget.can_call() is False


def test_call_budget_records_and_stops():
    budget = mod.CallBudget(max_calls=2)
    assert budget.can_call() is True
    budget.record("status", "test")
    assert budget.used == 1
    assert budget.can_call() is True
    budget.record("teams", "test2")
    assert budget.used == 2
    assert budget.can_call() is False
    assert len(budget.log) == 2
    assert "status" in budget.log[0] and "test" in budget.log[0]


def test_run_without_new_key_never_calls_network(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY_NEW", raising=False)

    def _boom(*a, **kw):
        raise AssertionError("nu ar trebui apelat requests fara cheie")
    monkeypatch.setattr(mod, "_make_session", _boom)

    report = mod.run("Arsenal", 5)
    assert report["ok"] is False
    assert "lipsă" in report["reason"]


# ── compare_status_shape ────────────────────────────────────────────────

def test_compare_status_shape_clean():
    payload = {"response": {"requests": {"current": 1, "limit_day": 100}, "subscription": {"plan": "Free"}}}
    assert mod.compare_status_shape(payload) == []


def test_compare_status_shape_missing_response():
    assert mod.compare_status_shape(None) != []
    assert mod.compare_status_shape({}) != []


def test_compare_status_shape_missing_requests_or_subscription():
    issues = mod.compare_status_shape({"response": {}})
    assert any("requests" in i for i in issues)
    assert any("subscription" in i for i in issues)


# ── compare_team_shape (oglindă resolve_team_id, football_providers.py) ──

def test_compare_team_shape_clean():
    payload = {"response": [{"team": {"id": 42, "name": "Arsenal"}}]}
    assert mod.compare_team_shape(payload) == []


def test_compare_team_shape_empty_response():
    assert mod.compare_team_shape({"response": []}) != []
    assert mod.compare_team_shape(None) != []


def test_compare_team_shape_missing_team_id():
    issues = mod.compare_team_shape({"response": [{"team": {"name": "Arsenal"}}]})
    assert any("team.id" in i for i in issues)


def test_compare_team_shape_non_dict_element():
    issues = mod.compare_team_shape({"response": ["not-a-dict"]})
    assert any("nu e dict" in i for i in issues)


# ── compare_injury_shape (oglindă _normalize_injury) ────────────────────

def test_compare_injury_shape_clean():
    payload = {"response": [{"player": {"name": "X", "id": 1}, "team": {"name": "Arsenal"},
                              "fixture": {"id": 9}, "type": "Injury", "reason": "Knee"}]}
    assert mod.compare_injury_shape(payload) == []


def test_compare_injury_shape_missing_response_key_with_errors():
    payload = {"errors": {"season": "The Season field is required."}}
    issues = mod.compare_injury_shape(payload)
    assert any("response" in i for i in issues)
    assert any("errors" in i for i in issues)


def test_compare_injury_shape_missing_type_and_reason():
    payload = {"response": [{"player": {"name": "X"}, "team": {}, "fixture": {}}]}
    issues = mod.compare_injury_shape(payload)
    assert any("type" in i and "reason" in i for i in issues)


def test_compare_injury_shape_type_under_player_is_accepted():
    """_normalize_injury citește si item.get('type') SAU player.get('type')."""
    payload = {"response": [{"player": {"name": "X", "type": "Suspension", "reason": "Red card"}}]}
    assert mod.compare_injury_shape(payload) == []


# ── compare_coach_shape (oglindă _normalize_coach) ──────────────────────

def test_compare_coach_shape_clean():
    payload = {"response": [{"id": 5, "name": "Mikel Arteta", "team": {"name": "Arsenal"},
                              "career": [{"start": "2019-12-20", "end": None}], "nationality": "Spain"}]}
    assert mod.compare_coach_shape(payload) == []


def test_compare_coach_shape_missing_id_and_name():
    issues = mod.compare_coach_shape({"response": [{}]})
    assert any("'id'" in i for i in issues)
    assert any("'name'" in i for i in issues)


def test_compare_coach_shape_career_not_a_list():
    issues = mod.compare_coach_shape({"response": [{"id": 1, "name": "X", "career": "not-a-list"}]})
    assert any("career" in i for i in issues)


# ── run() — orchestrare, fără rețea reală (mockuit) ─────────────────────

def test_run_stops_after_status_auth_failure(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY_NEW", "fake-key")
    monkeypatch.setattr(mod, "_make_session", lambda: object())

    calls = []
    def _fake_call(session, key, budget, path, params, reason):
        calls.append(path)
        return {"payload": None, "latency_ms": None}  # simuleaza esec HTTP/auth pe /status
    monkeypatch.setattr(mod, "_call", _fake_call)

    report = mod.run("Arsenal", 5)
    assert calls == ["status"]  # nu a mai incercat /teams
    assert report["ok"] is False
    assert report["endpoints_tested"] == ["status"]


def test_run_skips_injuries_coaches_when_team_id_unresolved(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY_NEW", "fake-key")
    monkeypatch.setattr(mod, "_make_session", lambda: object())

    calls = []
    def _fake_call(session, key, budget, path, params, reason):
        calls.append(path)
        if path == "status":
            return {"payload": {"response": {"requests": {}, "subscription": {}}}, "latency_ms": 12.3}
        if path == "teams":
            return {"payload": {"response": []}, "latency_ms": 15.0}  # echipa nu s-a gasit -> team_id ramane None
        raise AssertionError(f"nu ar trebui apelat {path}")
    monkeypatch.setattr(mod, "_call", _fake_call)

    report = mod.run("Arsenal", 5)
    assert calls == ["status", "teams"]
    assert "injuries" not in report["checks"]
    assert "coaches" not in report["checks"]
    assert report["endpoints_tested"] == ["status", "teams"]


def test_run_full_success_populates_all_report_sections(monkeypatch):
    monkeypatch.setenv("API_FOOTBALL_KEY_NEW", "fake-key")
    monkeypatch.setattr(mod, "_make_session", lambda: object())

    def _fake_call(session, key, budget, path, params, reason):
        if path == "status":
            return {"payload": {"response": {"requests": {"limit_day": 100}, "subscription": {"plan": "Free"}}},
                     "latency_ms": 10.0}
        if path == "teams":
            return {"payload": {"response": [{"team": {"id": 42, "name": "Arsenal"}}]}, "latency_ms": 11.0}
        if path == "injuries":
            return {"payload": {"response": []}, "latency_ms": 9.0}
        if path == "coachs":
            return {"payload": {"response": []}, "latency_ms": 8.0}
        raise AssertionError(f"endpoint neasteptat: {path}")
    monkeypatch.setattr(mod, "_call", _fake_call)

    report = mod.run("Arsenal", 5)
    assert report["ok"] is True
    assert report["endpoints_tested"] == ["status", "teams", "injuries", "coachs"]
    assert report["plan_comparison"]["comparable"] is True
    assert report["plan_comparison"]["differences"] == []
    assert "Team Health" in report["data_warehouse_impact_estimate"]
    assert "fixtures/statistics" in report["endpoints_catalog"]
    rendered = mod.render_report(report)
    assert "1. AUTENTIFICARE" in rendered
    assert "7. IMPACT ESTIMAT ASUPRA DATA WAREHOUSE" in rendered


# ── banner-uri de audit (item 2/3 din aprobarea rundei a doua) ──────────

def test_print_poc_mode_banner_contains_required_lines(capsys):
    mod.print_poc_mode_banner()
    out = capsys.readouterr().out
    assert "POC MODE" in out
    assert "NO PRODUCTION CODE TOUCHED" in out
    assert "OLD API KEY NOT READ" in out
    assert "NEW API KEY ONLY" in out


def test_print_audit_banner_contains_required_fields(capsys):
    mod.print_audit_banner()
    out = capsys.readouterr().out
    assert "API-Football NEW" in out
    assert "API_FOOTBALL_KEY_NEW" in out
    assert "UNTOUCHED" in out
    assert "NOT READ" in out


def test_run_prints_poc_banner_even_without_key(monkeypatch, capsys):
    monkeypatch.delenv("API_FOOTBALL_KEY_NEW", raising=False)
    mod.run("Arsenal", 5)
    out = capsys.readouterr().out
    assert "POC MODE" in out


def test_run_prints_audit_banner_before_first_call(monkeypatch):
    """Ordinea contează pentru audit (item 3) — banner-ul apare ÎNAINTE de
    primul apel real, nu doar existent undeva în output."""
    monkeypatch.setenv("API_FOOTBALL_KEY_NEW", "fake-key")
    monkeypatch.setattr(mod, "_make_session", lambda: object())

    order = []
    monkeypatch.setattr(mod, "print_audit_banner", lambda: order.append("audit_banner"))

    def _fake_call(session, key, budget, path, params, reason):
        order.append(f"call:{path}")
        return {"payload": None, "latency_ms": None}
    monkeypatch.setattr(mod, "_call", _fake_call)

    mod.run("Arsenal", 5)
    assert order[0] == "audit_banner"
    assert order[1] == "call:status"


# ── compare_plan_vs_old_key ──────────────────────────────────────────────

def test_compare_plan_vs_old_key_no_status():
    result = mod.compare_plan_vs_old_key(None)
    assert result["comparable"] is False


def test_compare_plan_vs_old_key_identical_limit():
    payload = {"response": {"requests": {"limit_day": 100}, "subscription": {"plan": "Free"}}}
    result = mod.compare_plan_vs_old_key(payload)
    assert result["comparable"] is True
    assert result["differences"] == []
    assert result["old_key_documented"]["daily_limit"] == 100


def test_compare_plan_vs_old_key_different_limit_flagged():
    payload = {"response": {"requests": {"limit_day": 7500}, "subscription": {"plan": "Pro"}}}
    result = mod.compare_plan_vs_old_key(payload)
    assert result["differences"] != []


# ── estimate_data_warehouse_impact ──────────────────────────────────────

def test_estimate_data_warehouse_impact_clean_checks():
    checks = {"status": {"issues": []}, "teams": {"issues": []}, "injuries": {"issues": []}, "coaches": {"issues": []}}
    text = mod.estimate_data_warehouse_impact(checks)
    assert "compatibil structural" in text
    assert "fixtures/statistics" in text


def test_estimate_data_warehouse_impact_with_issues():
    checks = {"status": {"issues": []}, "teams": {"issues": ["ceva lipsă"]}}
    text = mod.estimate_data_warehouse_impact(checks)
    assert "NU poate deveni" in text


# ── latență capturată în _call (fără rețea reală, requests mockuit) ────

def test_call_records_latency_on_success(monkeypatch):
    class _FakeResp:
        ok = True
        def json(self):
            return {"response": {}}

    class _FakeSession:
        def get(self, *a, **kw):
            return _FakeResp()

    budget = mod.CallBudget(max_calls=5)
    result = mod._call(_FakeSession(), "fake-key", budget, "status", {}, "test")
    assert result["payload"] == {"response": {}}
    assert isinstance(result["latency_ms"], float)
    assert result["latency_ms"] >= 0


def test_call_returns_none_payload_when_budget_exhausted():
    budget = mod.CallBudget(max_calls=0)
    result = mod._call(object(), "fake-key", budget, "status", {}, "test")
    assert result == {"payload": None, "latency_ms": None}
    assert budget.used == 0
