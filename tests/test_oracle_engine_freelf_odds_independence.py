"""Gardă statică pentru ADR-039 (Universal Synchronization Architecture) —
R-Sync-6: Oracle Engine nu mai are voie să apeleze
`self.api.get_freelf_standings()`/`get_team_form_freelf()`/
`get_team_recent_form()`/`_fetch_scores_odds_api()` direct.

Oglindă directă a gărzilor echivalente de la R-Sync-2/3/4/5.

Notă de scope, explicită: `self.api.get_h2h()` (FreeLF, event_id-based)
rămâne DELIBERAT neatinsă — cuplată structural la Match Discovery
(§6c/§6d, dovedit la audit R-Sync-6), migrarea ei e R-Sync-8, alături de
TheSportsDB team stats. Acest test NU o interzice."""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _parse(path: pathlib.Path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_oracle_engine_never_calls_migrated_freelf_odds_methods():
    """R-Sync-6: singurii apelanți de producție ai
    get_freelf_standings/get_team_form_freelf/get_team_recent_form/
    _fetch_scores_odds_api (oracle_api.py) rămân Sync Layer
    (freelf_form_adapter.py, odds_api_recent_results_adapter.py),
    niciodată oracle_engine.py."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    forbidden = {
        "get_freelf_standings", "get_team_form_freelf",
        "get_team_recent_form", "_fetch_scores_odds_api",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden:
            raise AssertionError(
                f"oracle_engine.py:{node.lineno} referă încă `.{node.attr}` — "
                "eliminat în R-Sync-6, ADR-039 (citire STRICT din Supabase)."
            )


def test_oracle_engine_still_calls_freelf_h2h_deliberately():
    """Pozitiv, opusul testului de mai sus: `get_h2h` (FreeLF, event_id)
    TREBUIE să rămână apelată — dovadă că nu a fost eliminată accidental,
    nu doar că restul a fost migrat corect. Deferred explicit la R-Sync-8."""
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    found = any(
        isinstance(node, ast.Attribute) and node.attr == "get_h2h"
        for node in ast.walk(tree)
    )
    assert found, (
        "oracle_engine.py trebuie să apeleze încă self.api.get_h2h() "
        "(FreeLF H2H, event_id-based) — migrarea ei e R-Sync-8, nu R-Sync-6."
    )


def test_oracle_engine_reads_freelf_form_only_via_database_queries():
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("database.queries"):
            if any(alias.name == "get_team_form_freelf_snapshot" for alias in node.names):
                found = True
    assert found, (
        "oracle_engine.py trebuie să importe get_team_form_freelf_snapshot "
        "din database.queries (R-Sync-6)."
    )


def test_oracle_engine_reads_odds_form_and_h2h_only_via_database_queries():
    path = ROOT / "oracle_engine.py"
    tree = _parse(path)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("database.queries"):
            imported |= {alias.name for alias in node.names}
    assert "get_team_recent_form_oddsapi" in imported, (
        "oracle_engine.py trebuie să importe get_team_recent_form_oddsapi "
        "din database.queries (R-Sync-6)."
    )
    assert "get_h2h_from_odds_recent" in imported, (
        "oracle_engine.py trebuie să importe get_h2h_from_odds_recent "
        "din database.queries (R-Sync-6)."
    )
