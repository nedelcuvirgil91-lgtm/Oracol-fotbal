"""Gărzi statice pentru ADR-036 (Canonical Feature Ownership / D3.5).

Impun modelul de ownership aprobat prin inspecție AST a codului de producție,
ca nicio cale nouă să nu poată reintroduce contaminarea coloanelor canonice:

- Stage 1: Prediction Engine (_save_prediction) NU scrie cele 10 FEATURE_COLUMNS
  owner-ate de backfill.
- Stage 3: actual_* scrise DOAR de sync_results; update_weights_from_result NU
  mai scrie actual_*.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Cele 10 coloane de feature owner-ate de backfill (walk-forward) care erau
# scrise concurent și de _save_prediction (cauza rădăcină D3.5). Prediction
# Engine nu are voie să le scrie.
BACKFILL_OWNED_CONFLICT = {
    "home_offensive_rating", "home_defensive_rating",
    "away_offensive_rating", "away_defensive_rating",
    "home_form_score", "away_form_score",
    "home_elo", "away_elo",
    "h2h_modifier", "h2h_meetings",
}

RESULT_COLUMNS = {"actual_home_goals", "actual_away_goals", "actual_result"}


def _function_def(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _dict_keys_written_to(func: ast.AST, method_names: set[str]) -> set[str]:
    """Cheile-string ale dict-urilor pasate ca argument oricărui apel
    `<...>.<method>({...})` cu method ∈ method_names, în interiorul `func`."""
    keys: set[str] = set()
    for node in ast.walk(func):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name not in method_names:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Dict):
                for k in arg.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        keys.add(k.value)
    return keys


MATCH_HISTORY_WRITE_FUNCS = {"upsert_match_history", "upsert_match", "upsert_matches_bulk"}


def test_prediction_write_does_not_include_backfill_owned_features():
    """ADR-036 Stage 1: calea de scriere a predicției (_cache_prediction)
    scrie DOAR ieșiri de predicție — niciuna din cele 10 FEATURE_COLUMNS
    owner-ate de backfill. Pică pe codul pre-Stage-1 (care le trimitea toate)."""
    tree = ast.parse((ROOT / "oracle_engine.py").read_text(encoding="utf-8"))
    func = _function_def(tree, "_cache_prediction")
    assert func is not None, "_cache_prediction() nu a fost găsită în oracle_engine.py"

    written = _dict_keys_written_to(func, {"upsert_match_history"})
    leaked = written & BACKFILL_OWNED_CONFLICT
    assert not leaked, (
        f"_cache_prediction() scrie coloane owner-ate de backfill: {sorted(leaked)} "
        f"— încalcă ADR-036 (contaminare canonică). Prediction Engine nu are voie "
        f"să scrie FEATURE_COLUMNS; le completează exclusiv run_backfill()."
    )


def test_prediction_engine_writes_neither_features_nor_actual_results():
    """ADR-036 Stage 1+3: Prediction Engine (`oracle_engine.py`), pe ORICE
    cale de scriere în match_history, nu scrie nici cele 10 FEATURE_COLUMNS
    (owner: backfill), nici `actual_*` (owner: sync_results). Acoperă atât
    `_cache_prediction` (feature-uri, Stage 1) cât și
    `update_weights_from_result` (rezultat, Stage 3, scriere eliminată)."""
    tree = ast.parse((ROOT / "oracle_engine.py").read_text(encoding="utf-8"))
    written = _dict_keys_written_to(tree, MATCH_HISTORY_WRITE_FUNCS)

    forbidden = BACKFILL_OWNED_CONFLICT | RESULT_COLUMNS
    leaked = written & forbidden
    assert not leaked, (
        f"oracle_engine.py scrie în match_history coloane care nu-i aparțin: "
        f"{sorted(leaked)} — încalcă ADR-036. Prediction Engine scrie DOAR "
        f"ieșiri de predicție; feature-urile sunt owner-ate de run_backfill(), "
        f"iar actual_* de sync_results.py."
    )


MATCH_STATISTICS_OWNED_COLUMNS = {
    "home_possession", "away_possession", "home_xg_actual", "away_xg_actual",
    # [EXTINS Sprint 3, Prioritatea 1] FreeLF completează acum și
    # shots_on_target (COALESCE-only, fallback — owner PRIMAR rămâne
    # football_data_co_uk pentru istoric, SFI pentru live) — vezi
    # match_statistics_adapter.py.
    "home_shots_on_target", "away_shots_on_target",
}

# [ADAUGAT ADR-041 Faza 1] Coloane scrise EXCLUSIV de
# SoccerFootballInfoMatchStatisticsAdapter — niciun alt adaptor (FreeLF,
# Oracle Engine) nu are voie să le scrie vreodată. Cele din
# MATCH_STATISTICS_OWNED_COLUMNS rămân distincte — acelea SUNT împărțite
# intenționat între FreeLF și Soccer Football Info (COALESCE-only, primul
# scriitor câștigă, ADR-036), nu exclusive unui singur adaptor.
SOCCERFOOTBALLINFO_ONLY_COLUMNS = {
    "home_shots", "away_shots",
    "home_shots_off_target", "away_shots_off_target",
    "home_corners", "away_corners",
    "home_fouls", "away_fouls",
    "home_offsides", "away_offsides",
    "home_yellow_cards", "away_yellow_cards",
    "home_red_cards", "away_red_cards",
    "home_penalties", "away_penalties",
    "home_substitutions", "away_substitutions",
    "home_lineup", "away_lineup",
    "home_manager", "away_manager",
    "referee", "stadium", "provider_raw_json",
}


def test_oracle_engine_never_writes_match_statistics_columns():
    """Sprint 1 (ADR-039) — owner nou (FreeLF, `MatchStatisticsAdapter`),
    aceeași disciplină ADR-036: Prediction Engine nu scrie niciodată
    `home/away_possession`/`home/away_xg_actual`, pe nicio cale de scriere
    în match_history."""
    tree = ast.parse((ROOT / "oracle_engine.py").read_text(encoding="utf-8"))
    written = _dict_keys_written_to(tree, MATCH_HISTORY_WRITE_FUNCS)
    leaked = written & MATCH_STATISTICS_OWNED_COLUMNS
    assert not leaked, (
        f"oracle_engine.py scrie coloane owner-ate de MatchStatisticsAdapter: "
        f"{sorted(leaked)} — încalcă ownership-ul nou stabilit (Sprint 1)."
    )


def test_oracle_engine_never_writes_soccerfootballinfo_columns():
    """[ADAUGAT ADR-041 Faza 1] Aceeași disciplină, extinsă la setul mult mai
    larg owner-at de Soccer Football Info (shots/corners/fouls/lineup/
    manageri/arbitru/stadion/provider_raw_json) — Prediction Engine nu scrie
    niciodată niciuna dintre ele, pe nicio cale de scriere în match_history."""
    tree = ast.parse((ROOT / "oracle_engine.py").read_text(encoding="utf-8"))
    written = _dict_keys_written_to(tree, MATCH_HISTORY_WRITE_FUNCS)
    leaked = written & SOCCERFOOTBALLINFO_ONLY_COLUMNS
    assert not leaked, (
        f"oracle_engine.py scrie coloane owner-ate exclusiv de "
        f"SoccerFootballInfoMatchStatisticsAdapter: {sorted(leaked)} — "
        f"încalcă ownership-ul stabilit (ADR-041 Faza 1)."
    )


def test_match_statistics_adapter_normalize_stays_within_approved_scope():
    """Gardă pozitivă + scope: `normalize()` scrie exact coloanele aprobate
    (`MATCH_STATISTICS_OWNED_COLUMNS` + `stats_source`) — niciodată
    `big_chance` (coloană inexistentă), și niciodată vreo coloană exclusivă
    Soccer Football Info (ADR-041)."""
    tree = ast.parse((ROOT / "match_statistics_adapter.py").read_text(encoding="utf-8"))
    func = _function_def(tree, "normalize")
    assert func is not None, "normalize() nu a fost găsită în match_statistics_adapter.py"

    keys: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)

    out_of_scope = ({"home_big_chance", "away_big_chance", "big_chance"}
                     | SOCCERFOOTBALLINFO_ONLY_COLUMNS)
    assert not (keys & out_of_scope), (
        f"MatchStatisticsAdapter.normalize() scrie coloane în afara scope-ului "
        f"aprobat: {sorted(keys & out_of_scope)}"
    )
    assert MATCH_STATISTICS_OWNED_COLUMNS <= keys, (
        f"MatchStatisticsAdapter.normalize() nu scrie toate coloanele owner-ate: "
        f"lipsesc {sorted(MATCH_STATISTICS_OWNED_COLUMNS - keys)}"
    )


def test_soccerfootballinfo_adapter_normalize_stays_within_approved_scope():
    """[ADAUGAT ADR-041 Faza 1] Gardă pozitivă + scope, oglindă a testului
    FreeLF de mai sus: `normalize()` scrie exact cele 4 coloane împărțite
    (owner comun cu FreeLF, COALESCE-only) + setul exclusiv Soccer Football
    Info + `stats_source` — niciodată vreo coloană owner-ată de backfill
    (FEATURE_COLUMNS walk-forward) sau `actual_*` (owner: sync_results)."""
    tree = ast.parse((ROOT / "soccerfootballinfo_match_statistics_adapter.py").read_text(encoding="utf-8"))
    func = _function_def(tree, "normalize")
    assert func is not None, "normalize() nu a fost găsită în soccerfootballinfo_match_statistics_adapter.py"

    keys: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)

    out_of_scope = BACKFILL_OWNED_CONFLICT | RESULT_COLUMNS
    assert not (keys & out_of_scope), (
        f"SoccerFootballInfoMatchStatisticsAdapter.normalize() scrie coloane "
        f"în afara scope-ului aprobat (ADR-041): {sorted(keys & out_of_scope)}"
    )
    expected = MATCH_STATISTICS_OWNED_COLUMNS | SOCCERFOOTBALLINFO_ONLY_COLUMNS
    assert expected <= keys, (
        f"SoccerFootballInfoMatchStatisticsAdapter.normalize() nu scrie toate "
        f"coloanele owner-ate: lipsesc {sorted(expected - keys)}"
    )


def test_sync_results_remains_owner_of_actual_columns():
    """ADR-036 Stage 3 (gardă pozitivă): owner-ul canonic al `actual_*` există
    și scrie efectiv — `sync/sync_results.py` conține scrierea acestor coloane
    în match_history. Previne eliminarea accidentală a owner-ului real odată cu
    curățarea căii legacy."""
    src = (ROOT / "sync" / "sync_results.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    # sync_results scrie prin `.table("match_history").update({...})` — culegem
    # cheile din orice dict pasat unui `.update(...)`.
    keys = _dict_keys_written_to(tree, {"update"})
    assert RESULT_COLUMNS <= keys, (
        f"sync/sync_results.py nu mai scrie toate coloanele actual_* "
        f"({sorted(RESULT_COLUMNS)}) — owner-ul canonic al rezultatului real "
        f"lipsește. Găsit: {sorted(keys & RESULT_COLUMNS)}."
    )


def test_flashscore_normalizer_is_authorized_secondary_writer_of_actual_columns():
    """ADR-044 Addendum 4 (rezolvă Addendum 3, TODO deschis), REVIZUIT prin
    Addendum 5 — Flashscore e un writer SECUNDAR autorizat explicit pentru
    `actual_home_goals`/`actual_away_goals`/`actual_result`. Addendum 4
    restrânsese `actual_result` exclusiv la sync_results.py, dar audit-ul
    live (Faza 2) a găsit `actual_result` NULL pe 17/17 meciuri Flashscore
    colectate real — gate-ul `actual_result IS NOT NULL`, folosit de FIECARE
    query Team DNA, nu se satisface niciodată pentru meciurile Flashscore
    (Romania SuperLiga/calificări UEFA — exact ligile fără acoperire
    sync_results.py). Derivarea e identică, deterministă (formula
    sync_results.py, fără ambiguitate), scrisă doar dacă ambele goluri sunt
    prezente. `sync/sync_results.py` rămâne owner-ul PRIMAR (testul de mai
    sus); scrierea Flashscore trece prin RPC COALESCE-safe + hard-conflict
    (`upsert_match_canonical`, migrația 036 — deja acoperă `actual_result`
    explicit), deci nu suprascrie niciodată silențios un rezultat deja scris
    de sync_results.py."""
    tree = ast.parse((ROOT / "providers" / "flashscore" / "normalizer.py").read_text(encoding="utf-8"))
    func = _function_def(tree, "normalize_match_statistics")
    assert func is not None, "normalize_match_statistics() nu a fost găsită în normalizer.py"

    keys: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    keys.add(k.value)

    expected = {"actual_home_goals", "actual_away_goals", "actual_result"}
    assert expected <= keys, (
        f"providers/flashscore/normalizer.py.normalize_match_statistics() nu mai scrie "
        f"{sorted(expected)} — ar rupe decizia documentată în ADR-044 Addendum 5 "
        f"(writer secundar autorizat, inclusiv actual_result)."
    )
