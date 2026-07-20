"""Teste pentru ADR-035 D4 — Honest Data Quality Labeling.

`_classify_data_quality()` e PUNCTUL UNIC de decizie pentru nivelul
`data_quality`. LIVE reprezintă date din meciuri reale (`supabase-history`
cu eșantion suficient), NU „toate statisticile reale". Sursele agregat/
proxy/sintetice devin PARTIAL, onest. Garda AST impune că niciun alt loc
din producție nu atribuie DATA_QUALITY_LIVE.

Pică pe codul pre-D4 (6 atribuiri inline `data_quality = DATA_QUALITY_LIVE`
în `_build_profile`, fără nivel PARTIAL, text vechi „statistici reale")."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import oracle_engine
from oracle_engine import (
    _classify_data_quality,
    DATA_QUALITY_LIVE, DATA_QUALITY_PARTIAL, DATA_QUALITY_ELO, DATA_QUALITY_NEUTRAL,
    DATA_QUALITY_NOTES,
)

ROOT = Path(__file__).parent.parent


# ── Unitare: clasificarea per sursă ─────────────────────────────────────────

def test_supabase_history_with_enough_matches_is_live():
    assert _classify_data_quality("supabase-history", 3) == DATA_QUALITY_LIVE
    assert _classify_data_quality("supabase-history", 5) == DATA_QUALITY_LIVE


def test_supabase_history_below_threshold_is_partial():
    """Plasă de siguranță: sub prag (gate-ul D1 previne asta în practică),
    clasificatorul rămâne onest — nu LIVE."""
    assert _classify_data_quality("supabase-history", 2) == DATA_QUALITY_PARTIAL


def test_synthetic_and_aggregate_sources_are_partial():
    for src in ("national-stats-hardcoded", "freelf-standings", "scores-api",
                "standings-fd", "thesportsdb"):
        assert _classify_data_quality(src, 5) == DATA_QUALITY_PARTIAL, src


def test_elo_only_is_elo():
    assert _classify_data_quality("elo-only", 0) == DATA_QUALITY_ELO


def test_neutral_and_empty_are_neutral():
    assert _classify_data_quality("neutral-defaults", 0) == DATA_QUALITY_NEUTRAL
    assert _classify_data_quality("", 0) == DATA_QUALITY_NEUTRAL


def test_live_note_no_longer_overclaims():
    assert DATA_QUALITY_NOTES[DATA_QUALITY_LIVE] == "Date reale — meciuri terminate"
    assert "statistici reale" not in DATA_QUALITY_NOTES[DATA_QUALITY_LIVE]
    assert DATA_QUALITY_PARTIAL in DATA_QUALITY_NOTES
    assert "parțiale" in DATA_QUALITY_NOTES[DATA_QUALITY_PARTIAL]


def test_notes_contain_no_emoji():
    """ADR-035 D4 / Stage 2: `data_quality_note` conține DOAR text — emoji-ul
    e furnizat de maparea din _dq (app.py), nu de notă. Previne dublu-emoji."""
    for level, note in DATA_QUALITY_NOTES.items():
        for emoji in ("✅", "🟠", "🟡", "⚠️"):
            assert emoji not in note, f"{level}: nota conține emoji ({emoji!r}) — {note!r}"


# ── Gardă AST: DATA_QUALITY_LIVE atribuit dintr-un singur loc ────────────────

def test_ast_live_referenced_only_in_classifier():
    """Niciun cod de producție (nicio funcție) nu referențiază
    DATA_QUALITY_LIVE în afara `_classify_data_quality`. Definiția constantei
    și dict-ul DATA_QUALITY_NOTES sunt la nivel de modul (nu în funcție) și
    nu intră sub această regulă."""
    tree = ast.parse((ROOT / "oracle_engine.py").read_text(encoding="utf-8"))
    offenders: dict[str, list[int]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Name) and sub.id == "DATA_QUALITY_LIVE":
                    offenders.setdefault(node.name, []).append(sub.lineno)
    assert set(offenders) <= {"_classify_data_quality"}, (
        f"DATA_QUALITY_LIVE referențiat în afara _classify_data_quality: "
        f"{offenders} — încalcă ADR-035 D4 (punct unic de decizie)."
    )


# ── Integrare: _build_profile derivă data_quality prin clasificator ─────────

def _engine(monkeypatch, db_rows, tsdb_stats=None):
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = SimpleNamespace(
        get_elo_rating=lambda name: None,
        get_freelf_standings=lambda league: [],
        get_team_form_freelf=lambda tid, league, n: [],
        get_team_recent_form=lambda name, league, days_back=14: [],
        get_standings_form=lambda tid, league: None,
        get_team_stats=lambda tid, league: list(tsdb_stats or []),
    )
    fake_sb = SimpleNamespace(
        get_team_recent_results=lambda team, league, last_n=5, lookback_days=365: list(db_rows),
        get_team_recent_shots=lambda team, league, last_n=5: [],
        get_team_recent_match_events=lambda team, league, last_n=5: [],
    )
    monkeypatch.setattr(oracle_engine, "sb", fake_sb, raising=False)
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", False, raising=False)
    return eng


_DB_ROWS = [
    {"home_team": "TeamA", "away_team": "TeamB", "actual_home_goals": 2,
     "actual_away_goals": 0, "actual_result": "H", "kickoff_date": "2026-05-01"},
    {"home_team": "TeamB", "away_team": "TeamA", "actual_home_goals": 1,
     "actual_away_goals": 1, "actual_result": "D", "kickoff_date": "2026-04-01"},
    {"home_team": "TeamA", "away_team": "TeamC", "actual_home_goals": 0,
     "actual_away_goals": 1, "actual_result": "A", "kickoff_date": "2026-03-01"},
    {"home_team": "TeamD", "away_team": "TeamA", "actual_home_goals": 0,
     "actual_away_goals": 2, "actual_result": "A", "kickoff_date": "2026-02-01"},
]

_TSDB_ONE = [{"result": "W", "goals_for": 2, "goals_against": 1,
              "shots_on_goal": 7.0, "possession": 50.0}]


def test_build_profile_supabase_history_is_live(monkeypatch):
    eng = _engine(monkeypatch, _DB_ROWS)
    p = eng._build_profile("tsdb_x", "TeamA", "LigaX")
    assert p.data_source == "supabase-history"
    assert p.data_quality == DATA_QUALITY_LIVE
    assert p.data_quality_note == "Date reale — meciuri terminate"


def test_build_profile_tsdb_only_is_partial(monkeypatch):
    """Cazul central al auditului: profil dintr-1 meci TSDB (șuturi sintetice)
    NU mai e etichetat «statistici reale» — devine PARTIAL."""
    eng = _engine(monkeypatch, db_rows=[], tsdb_stats=_TSDB_ONE)
    p = eng._build_profile("tsdb_1", "TeamA", "LigaX")
    assert p.data_source == "thesportsdb"
    assert p.data_quality == DATA_QUALITY_PARTIAL
    assert "statistici reale" not in p.data_quality_note


# ── UI (Stage 2): _dq() randează un singur emoji + clasa corectă ────────────

def _load_dq_from_app():
    """Extrage funcția `_dq` din app.py prin AST și o execută izolat, FĂRĂ a
    importa app.py (care ar rula întreg scriptul Streamlit la import)."""
    src = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_dq":
            ns: dict = {}
            exec(ast.get_source_segment(src, node), ns)
            return ns["_dq"]
    raise AssertionError("_dq() nu a fost găsită în app.py")


def test_dq_renders_four_badges_single_emoji():
    """Forma finală D4: fiecare badge are EXACT un emoji (din maparea _dq),
    clasa CSS corectă, și textul complet al notei — fără dublu-emoji, fără
    fallback, fără text lipsă."""
    dq = _load_dq_from_app()
    cases = {
        "live":    ("dq-live",    "✅", DATA_QUALITY_NOTES[DATA_QUALITY_LIVE]),
        "partial": ("dq-partial", "🟠", DATA_QUALITY_NOTES[DATA_QUALITY_PARTIAL]),
        "elo":     ("dq-elo",     "🟡", DATA_QUALITY_NOTES[DATA_QUALITY_ELO]),
        "neutral": ("dq-neutral", "⚠️", DATA_QUALITY_NOTES[DATA_QUALITY_NEUTRAL]),
    }
    for level, (cls, icon, note) in cases.items():
        out = dq(level, note)
        assert out == f'<span class="{cls}">{icon} {note}</span>', (level, out)
        # exact un emoji: niciunul dintre celelalte icoane nu apare
        for other in ("✅", "🟠", "🟡", "⚠️"):
            if other != icon:
                assert other not in out, f"{level}: emoji străin {other!r} în {out!r}"


def test_dq_partial_not_default_fallback():
    """PARTIAL NU cade pe clasa/iconul default (dq-neutral/⚠️)."""
    dq = _load_dq_from_app()
    out = dq("partial", DATA_QUALITY_NOTES[DATA_QUALITY_PARTIAL])
    assert "dq-partial" in out and "🟠" in out
    assert "dq-neutral" not in out and "⚠️" not in out
