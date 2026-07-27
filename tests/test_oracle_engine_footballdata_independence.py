"""Gardă statică pentru ADR-039 (Universal Synchronization Architecture) —
R-Sync-3: Oracle Engine nu mai are voie să apeleze
`self.api.get_standings_form()`/`get_team_form_fd()` (football-data.org,
formă/standings) direct.

Impune mecanic invariantul, prin inspecție AST a codului de producție —
oglindă directă a `test_oracle_engine_provider_independence.py` (R-Sync-2),
scop separat conform notei explicite de acolo: fiecare provider migrat
capătă propria gardă, adăugată la momentul migrării lui, nu toate odată.

Notă de scope, explicită: acest test acoperă DOAR
`get_standings_form`/`get_team_form_fd` (formă/standings,
football-data.org). `_fetch_matches_fd` (fixtures) și restul providerilor
(FreeLF/Odds API/ESPN/TheSportsDB) rămân, deliberat, neatinse — migrarea
lor e R-Sync-4…7."""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _parse(path: pathlib.Path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_oracle_engine_never_calls_get_standings_form_or_get_team_form_fd():
    """R-Sync-3: singurul apelant de producție al
    `get_standings_form`/`get_team_form_fd` (oracle_api.py) rămâne Sync
    Layer (footballdata_form_adapter.py, prin get_competition_standings_raw),
    niciodată oracle_engine.py."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    forbidden = {"get_standings_form", "get_team_form_fd"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(
                f"oracle_engine.py:{node.lineno} referă încă `.{node.attr}` — "
                "eliminat în R-Sync-3, ADR-039 (citire STRICT din Supabase, "
                "database.queries.get_team_form_footballdata())."
            )


def test_oracle_engine_reads_footballdata_form_only_via_database_queries():
    """Pozitiv: confirmă că înlocuirea chiar există, nu doar că vechea
    cale a dispărut — get_team_form_footballdata trebuie importat din
    database.queries."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("database.queries"):
            if any(alias.name == "get_team_form_footballdata" for alias in node.names):
                found = True
    assert found, (
        "oracle_engine.py trebuie să importe get_team_form_footballdata din "
        "database.queries (R-Sync-3) — sursa canonică pentru forma/standings "
        "football-data.org a unei echipe."
    )
