"""Gardă statică, cerută explicit la review PR #30: _build_profile() trebuie
să rămână SINGURUL punct din codul de producție care construiește un
TeamProfile sau care apelează direct TSDB pentru statistici de echipă.

Dacă apare vreodată o cale paralelă (ex. cineva adaugă un apel direct la
get_team_stats()/get_team_last_events_tsdb() în afara _build_profile, sau
un al doilea loc care instanțiază TeamProfile), acest test trebuie să pice
— altfel Level DB (D1) poate fi ocolit tăcut de o cale nouă, exact genul de
deconectare pe care ADR-035 îl repară."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Fișiere de producție care ar putea plauzibil construi/citi un profil de
# echipă — excludem teste, scripturi discovery (sync/poc_*) și fișierele
# offline de antrenare (bootstrap/backfill), care folosesc proxy-uri proprii
# documentate explicit ca "identic cu _build_profile", nu calea live.
PRODUCTION_FILES = [
    "app.py", "oracle_api.py", "oracle_engine.py", "feature_engine.py",
    "football_providers.py", "supabase_client.py", "database/queries.py",
]


def _calls_matching(tree: ast.AST, names: set[str]) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in names:
                lines.append(node.lineno)
    return lines


def test_teamprofile_constructed_in_exactly_one_place():
    hits: dict[str, list[int]] = {}
    for fname in PRODUCTION_FILES:
        path = ROOT / fname
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=fname)
        lines = _calls_matching(tree, {"TeamProfile"})
        if lines:
            hits[fname] = lines

    total = sum(len(v) for v in hits.values())
    assert total == 1, (
        f"TeamProfile(...) trebuie construit EXACT o dată, în _build_profile() — "
        f"găsit {total} apel(uri): {hits}. O a doua cale de construcție ar putea "
        f"ocoli Level DB (ADR-035/D1)."
    )
    assert list(hits.keys()) == ["oracle_engine.py"]


def test_tsdb_team_stats_only_called_from_build_profile():
    path = ROOT / "oracle_engine.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename="oracle_engine.py")

    calls_by_function: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            lines = _calls_matching(node, {"get_team_stats", "get_team_last_events_tsdb"})
            if lines:
                calls_by_function[node.name] = lines

    assert calls_by_function == {"_build_profile": calls_by_function.get("_build_profile", [])}, (
        f"get_team_stats/get_team_last_events_tsdb apelate din afara "
        f"_build_profile(): {calls_by_function} — cale paralelă către TSDB, "
        f"ocolește Level DB (ADR-035/D1)."
    )
    assert "_build_profile" in calls_by_function

    # Verificare separată: nicio altă locație din PRODUCTION_FILES (in afara
    # oracle_api.py, unde functiile sunt DEFINITE, nu apelate) nu le apelează.
    for fname in PRODUCTION_FILES:
        if fname in ("oracle_engine.py", "oracle_api.py"):
            continue
        p = ROOT / fname
        if not p.exists():
            continue
        t = ast.parse(p.read_text(encoding="utf-8"), filename=fname)
        lines = _calls_matching(t, {"get_team_stats", "get_team_last_events_tsdb"})
        assert not lines, f"{fname} apelează direct TSDB team-stats la liniile {lines}"


def test_elo_read_only_called_from_build_profile():
    """ADR-023 (Variant C) / ADR-035 D2: get_elo_rating() (provider extern)
    și get_latest_team_elo() (sursa canonică, match_history) trebuie
    apelate DINTR-UN SINGUR loc de producție — _build_profile(). O a doua
    cale ar putea citi ELO fără să respecte ordinea Database-First (DB
    întâi, provider doar ca fallback condiționat pe elo_raw is None)."""
    names = {"get_elo_rating", "get_latest_team_elo"}
    path = ROOT / "oracle_engine.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename="oracle_engine.py")

    calls_by_function: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            lines = _calls_matching(node, names)
            if lines:
                calls_by_function[node.name] = lines

    assert calls_by_function == {"_build_profile": calls_by_function.get("_build_profile", [])}, (
        f"get_elo_rating/get_latest_team_elo apelate din afara "
        f"_build_profile(): {calls_by_function} — cale paralelă către sursa "
        f"ELO, ocolește ordinea Database-First (ADR-023/ADR-035 D2)."
    )
    assert "_build_profile" in calls_by_function
    assert len(calls_by_function["_build_profile"]) == 2, (
        f"Așteptam exact 2 apeluri în _build_profile() — get_latest_team_elo "
        f"(primar) și get_elo_rating (fallback) — găsit "
        f"{calls_by_function['_build_profile']}."
    )

    # Nicio altă locație din PRODUCTION_FILES (în afara oracle_api.py și
    # database/queries.py, unde funcțiile sunt DEFINITE, nu apelate) nu le
    # apelează direct.
    for fname in PRODUCTION_FILES:
        if fname in ("oracle_engine.py", "oracle_api.py", "database/queries.py"):
            continue
        p = ROOT / fname
        if not p.exists():
            continue
        t = ast.parse(p.read_text(encoding="utf-8"), filename=fname)
        lines = _calls_matching(t, names)
        assert not lines, f"{fname} apelează direct sursa ELO la liniile {lines}"
