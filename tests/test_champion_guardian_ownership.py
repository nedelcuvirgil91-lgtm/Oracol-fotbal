"""
Gărzi AST de ownership pentru Champion Guardian (Stage R2.7, ADR-037).
Oglindesc test_rollback_ownership.py. Impun mecanic că Guardian doar
citește / clasifică / persistă sănătatea — atât.

Invarianți:
  1. champion_guardian NU importă promotion_service / rollback_service /
     oracle_engine / continuous_learning (nu promovează, nu face rollback, nu
     atinge servirea, nu orchestrează).
  2. champion_guardian NU referențiază apeluri de promovare/rollback/automation
     (rpc_promote_challenger, rpc_rollback_champion, promote_challenger,
     rollback_champion, automation_runs).
  3. `record_champion_health_evaluation` (singura scriere permisă) are un singur
     apelant de producție — champion_guardian.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
GUARDIAN = ROOT / "learning_core" / "champion_guardian.py"


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


_FORBIDDEN_IMPORTS = {"promotion_service", "rollback_service", "oracle_engine", "continuous_learning"}


def test_guardian_does_not_import_forbidden_modules():
    tree = _parse(GUARDIAN)
    assert tree is not None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                assert a.name.split(".")[-1] not in _FORBIDDEN_IMPORTS, \
                    f"champion_guardian importă {a.name!r} — interzis (nu promovează/rollback/servire/orchestrare)"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[-1]
            assert module not in _FORBIDDEN_IMPORTS, \
                f"champion_guardian importă din {node.module!r} — interzis"
            for a in node.names:
                assert a.name not in _FORBIDDEN_IMPORTS, \
                    f"champion_guardian importă {a.name!r} — interzis"


_FORBIDDEN_NAMES = {
    "rpc_promote_challenger", "rpc_rollback_champion",
    "promote_challenger", "rollback_champion", "automation_runs",
}


def test_guardian_does_not_reference_promote_rollback_or_automation():
    tree = _parse(GUARDIAN)
    assert tree is not None
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_NAMES:
            offenders.append((node.attr, node.lineno))
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            offenders.append((node.id, node.lineno))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
            for nm in names:
                if nm and nm.split(".")[-1] in _FORBIDDEN_NAMES:
                    offenders.append((nm, node.lineno))
    assert offenders == [], (
        f"champion_guardian referențiază promovare/rollback/automation: {offenders} — "
        "Guardian doar evaluează și persistă sănătatea, nu execută."
    )


def test_record_champion_health_has_single_production_caller():
    """`record_champion_health_evaluation` (singura scriere) e referențiat doar
    în: supabase_client.py (definiția) + champion_guardian.py (unicul apelant)
    + fișierele de test."""
    ALLOWED = {
        "supabase_client.py",
        "champion_guardian.py",
        "test_supabase_client_champion_health.py",
        "test_champion_guardian.py",
        "test_champion_guardian_ownership.py",
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
            if (isinstance(node, ast.Attribute) and node.attr == "record_champion_health_evaluation")
            or (isinstance(node, ast.Name) and node.id == "record_champion_health_evaluation")
        ]
        if hits:
            offenders[str(path.relative_to(ROOT))] = hits
    assert offenders == {}, (
        f"record_champion_health_evaluation apelat în afara owner-ului (champion_guardian): {offenders}"
    )


def test_guardian_has_only_known_importers():
    """Azi champion_guardian are ZERO importatori de producție (izolat;
    continuous_learning îl va adăuga la R3). Whitelist explicit."""
    SKIP = {"champion_guardian.py", "test_champion_guardian.py", "test_champion_guardian_ownership.py"}
    offenders = []
    for path in _iter_py_files():
        if path.name in SKIP:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[-1] == "champion_guardian" for a in node.names):
                    offenders.append(str(path.relative_to(ROOT)))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.split(".")[-1] == "champion_guardian" or any(
                    a.name == "champion_guardian" for a in node.names
                ):
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"champion_guardian importat în afara whitelist-ului: {offenders}"
