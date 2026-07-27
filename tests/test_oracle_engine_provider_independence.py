"""Gardă statică pentru ADR-039 (Universal Synchronization Architecture) —
R-Sync-2: Oracle Engine nu mai are voie să cunoască existența
providerului API-Football.

Impune mecanic invariantul, prin inspecție AST a codului de producție —
nu doar convenție de cod — ca nicio cale nouă să nu poată reintroduce
apelul direct la provider din Oracle Engine. Oglindă directă a tiparului
deja folosit pentru alte invarianți de ownership din proiect
(test_rollback_ownership.py, ADR-037; test_canonical_feature_ownership.py,
ADR-036).

Notă de scope, explicită: acest test acoperă DOAR API-Football
(providerul migrat în R-Sync-2). `self.api` (FreeLF/Odds API/football-data/
ESPN/TheSportsDB/Weather) rămâne, deliberat, neatins — migrarea lor e
R-Sync-3…7, fiecare cu propria gardă adăugată la momentul ei, nu toate
odată aici (ar fi o extindere de scope neaprobată)."""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _parse(path: pathlib.Path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_oracle_engine_never_imports_football_providers():
    """R-Sync-2: singurul apelant de producție al football_providers.py
    rămâne Sync Layer (apifootball_health_adapter.py) — niciodată
    oracle_engine.py."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert module.split(".")[-1] != "football_providers", (
                "oracle_engine.py nu are voie să importe football_providers — "
                "ADR-039, R-Sync-2: Oracle Engine citește exclusiv Supabase "
                "(database.queries.get_team_health()), niciodată direct de la provider."
            )
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[-1] != "football_providers", (
                    "oracle_engine.py nu are voie să importe football_providers — "
                    "vezi ADR-039, R-Sync-2."
                )


def test_oracle_engine_never_references_apifootball_attribute():
    """Regresie directă pe defectul eliminat: `self.apifootball` nu mai
    există ca atribut — verificat prin căutare textuală a numelui de
    atribut în AST (Attribute nodes), nu doar grep pe string."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "apifootball":
            raise AssertionError(
                f"oracle_engine.py:{node.lineno} referă încă `.apifootball` — "
                "eliminat în R-Sync-2, ADR-039."
            )


def test_oracle_engine_reads_team_health_only_via_database_queries():
    """Pozitiv: confirmă că înlocuirea chiar există, nu doar că vechea
    cale a dispărut — get_team_health trebuie importat din database.queries."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("database.queries"):
            if any(alias.name == "get_team_health" for alias in node.names):
                found = True
    assert found, (
        "oracle_engine.py trebuie să importe get_team_health din database.queries "
        "(R-Sync-2) — sursa canonică pentru starea de sănătate a unei echipe."
    )
