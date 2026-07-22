"""
Gărzi AST de ownership pentru Rollback Engine (Stage R1.7, ADR-037).
Oglindesc gărzile din test_promotion_service.py / test_challenger_manager.py.

Invarianți impuși mecanic:
  1. `rpc_rollback_champion` (apelul RPC de rollback) e apelat DINtr-un singur
     modul de producție — `learning_core/rollback_service.py`. Un al doilea
     apelant ar putea executa un rollback în afara owner-ului evenimentului.
  2. `rollback_service` are doar importatori cunoscuți (azi: niciunul real —
     izolat, ca `promotion_service` la creare; whitelist explicit).
  3. „Rollback execută, nu decide" — `rollback_service` nu importă
     `shadow_testing` (nu evaluează sănătate/statistici), simetric cu
     invariantul din `promotion_service`.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _iter_py_files():
    for path in ROOT.rglob("*.py"):
        if ".git" in path.parts or "__pycache__" in path.parts:
            continue
        yield path


def _parse(path):
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
    except SyntaxError:
        return None


def test_rpc_rollback_champion_has_single_production_caller():
    """`rpc_rollback_champion` e referențiat (definiție/apel) doar în:
    supabase_client.py (definiție) + rollback_service.py (unicul apelant) +
    fișierele de test. Orice alt modul care-l referă e o încălcare de ownership."""
    ALLOWED = {
        "supabase_client.py",       # definiția
        "rollback_service.py",      # unicul apelant de producție
        "test_supabase_client_rollback.py",
        "test_rollback_ownership.py",
    }
    offenders = {}
    for path in _iter_py_files():
        if path.name in ALLOWED:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        hits = [
            node.lineno for node in ast.walk(tree)
            if (isinstance(node, ast.Attribute) and node.attr == "rpc_rollback_champion")
            or (isinstance(node, ast.Name) and node.id == "rpc_rollback_champion")
        ]
        if hits:
            offenders[str(path.relative_to(ROOT))] = hits
    assert offenders == {}, (
        f"rpc_rollback_champion referențiat în afara owner-ului (rollback_service.py): {offenders}"
    )


def test_rollback_service_has_only_known_importers():
    """Whitelist explicit al importatorilor de producție ai rollback_service.
    De la Stage R3.2A (ADR-037), continuous_learning.py e importatorul
    legitim — DOAR pentru is_rollback_promoted() (gardă anti-ping-pong) și
    VALID_ROLLBACK_REASONS (validarea motivului mapat); rollback_champion()
    (execuția) rămâne fără apelanți reali până la R3.2B, aprobată separat —
    vezi test_rpc_rollback_champion_has_single_production_caller (neschimbat)."""
    SKIP = {
        "rollback_service.py", "test_rollback_service.py", "test_rollback_ownership.py",
        "continuous_learning.py", "test_continuous_learning_rollback.py",
    }
    offenders = []
    for path in _iter_py_files():
        if path.name in SKIP:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[-1] == "rollback_service" for a in node.names):
                    offenders.append(str(path.relative_to(ROOT)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[-1] == "rollback_service" or any(
                    a.name == "rollback_service" for a in node.names
                ):
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"rollback_service importat în afara whitelist-ului: {offenders}"


def test_rollback_service_does_not_import_shadow_testing():
    """Rollback execută, nu decide — nu evaluează sănătate/statistici."""
    path = ROOT / "learning_core" / "rollback_service.py"
    tree = _parse(path)
    assert tree is not None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[-1] == "shadow_testing" for a in node.names), \
                "rollback_service.py nu are voie să importe shadow_testing — Rollback execută, nu decide"
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[-1] != "shadow_testing", \
                "rollback_service.py nu are voie să importe shadow_testing — Rollback execută, nu decide"
