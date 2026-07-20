"""Teste pentru ADR-035 / D3 — H2H Database-First: _build_h2h() citește PRIMUL
din match_history (recalc din date brute), înaintea FreeLF/Odds API.

Deciziile D3 verificate aici:
- Decizia 1 (global): recalcul din perechea de cluburi, indiferent de ligă.
- Decizia 2 (brute): recalcul din actual_result/actual_home_goals/
  actual_away_goals, niciodată din coloanele precalculate.
- Decizia 3 (prag 3): sub 3 confruntări, DB e insuficient → cade pe cascada
  de provideri existentă (H2H influence rămâne 0 dacă nici providerii nu au).

Toate testele pică pe codul pre-D3 (fără nivel DB în _build_h2h) și trec după."""
from __future__ import annotations

from types import SimpleNamespace

import oracle_engine


def _engine(freelf_h2h=None, odds_scores=None):
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = SimpleNamespace(
        get_h2h=lambda eid, h, a: freelf_h2h,
        _fetch_scores_odds_api=lambda sk, days_back=3: list(odds_scores or []),
    )
    return eng


def _use_db(monkeypatch, rows):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_h2h_from_history",
                        lambda home, away, last_n=10: list(rows), raising=False)


# 4 confruntări TeamA(gazdă curentă) vs TeamB, ambele orientări, ordine desc.
DB_ROWS = [
    {"home_team": "TeamA", "away_team": "TeamB", "actual_home_goals": 2,
     "actual_away_goals": 0, "actual_result": "H", "kickoff_date": "2026-05-01"},  # A host, A win -> H
    {"home_team": "TeamB", "away_team": "TeamA", "actual_home_goals": 1,
     "actual_away_goals": 1, "actual_result": "D", "kickoff_date": "2026-03-01"},  # draw -> D
    {"home_team": "TeamB", "away_team": "TeamA", "actual_home_goals": 3,
     "actual_away_goals": 0, "actual_result": "H", "kickoff_date": "2025-11-01"},  # B host, B win -> A
    {"home_team": "TeamA", "away_team": "TeamB", "actual_home_goals": 0,
     "actual_away_goals": 2, "actual_result": "A", "kickoff_date": "2025-09-01"},  # A host, B win -> A
]
# Din perspectiva TeamA: 1W 1D 2L ; goluri TeamA=2+1+0+0=3 (avg .75),
# goluri TeamB=0+1+3+2=6 (avg 1.5) ; modifier=(1-2)/4*0.15=-0.0375


def _match():
    return {"home_team": "TeamA", "away_team": "TeamB", "league": "LigaX"}


def test_h2h_comes_from_db_when_enough_meetings(monkeypatch):
    _use_db(monkeypatch, DB_ROWS)
    eng = _engine()

    h = eng._build_h2h("TeamA", "TeamB", _match())

    assert h.meetings == 4
    assert (h.home_wins, h.draws, h.away_wins) == (1, 1, 2)
    assert h.last_5 == ["H", "D", "A", "A"]
    assert abs(h.home_goals_avg - 0.75) < 1e-9
    assert abs(h.away_goals_avg - 1.5) < 1e-9
    assert abs(h.h2h_modifier - (-0.0375)) < 1e-9
    assert "supabase" not in h.summary.lower()  # summary e H2H uman, nu sursă


def test_db_beats_freelf_provider(monkeypatch):
    """Principiul de proiectare: DB are prioritate — chiar dacă FreeLF ar
    întoarce un H2H, DB câștigă când are ≥3 confruntări."""
    _use_db(monkeypatch, DB_ROWS)
    freelf = {"meetings": 9, "home_wins": 9, "draws": 0, "away_wins": 0,
              "home_goals_avg": 3.0, "away_goals_avg": 0.0, "last_5": ["H"] * 5,
              "h2h_modifier": 0.15, "summary": "FREELF"}
    eng = _engine(freelf_h2h=freelf)

    h = eng._build_h2h("TeamA", "TeamB", {**_match(), "_freelf_event_id": 123})

    assert h.meetings == 4          # din DB, nu 9 din FreeLF
    assert h.summary != "FREELF"


def test_falls_back_when_db_below_threshold(monkeypatch):
    """Sub 3 confruntări, DB e insuficient (Decizia 3) → cascada veche.
    Fără event_id și ligă necunoscută la Odds → H2HRecord.empty (influence 0)."""
    _use_db(monkeypatch, DB_ROWS[:2])  # doar 2 confruntări
    eng = _engine()

    h = eng._build_h2h("TeamA", "TeamB", _match())

    assert h.meetings == 0
    assert h.h2h_modifier == 0.0


def test_falls_back_when_db_empty(monkeypatch):
    _use_db(monkeypatch, [])
    eng = _engine()

    h = eng._build_h2h("TeamA", "TeamB", _match())

    assert h.meetings == 0


def test_falls_back_when_db_read_raises(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)

    def _boom(home, away, last_n=10):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_h2h_from_history", _boom, raising=False)
    eng = _engine()

    h = eng._build_h2h("TeamA", "TeamB", _match())  # nu crapă

    assert h.meetings == 0


def test_falls_back_when_db_module_unavailable(monkeypatch):
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", False, raising=False)
    eng = _engine()

    h = eng._build_h2h("TeamA", "TeamB", _match())

    assert h.meetings == 0


def test_dirty_rows_ignored_not_approximated(monkeypatch):
    """Regula #8: rândurile cu goluri lipsă / rezultat invalid se ignoră.
    Rămân 2 valide < prag → fallback."""
    dirty = [
        {"home_team": "TeamA", "away_team": "TeamB", "actual_home_goals": None,
         "actual_away_goals": 1, "actual_result": "A", "kickoff_date": "2026-05-01"},
        {"home_team": "TeamA", "away_team": "TeamB", "actual_home_goals": 2,
         "actual_away_goals": 1, "actual_result": None, "kickoff_date": "2026-04-01"},
        {"home_team": "TeamA", "away_team": "TeamB", "actual_home_goals": 1,
         "actual_away_goals": 0, "actual_result": "H", "kickoff_date": "2026-03-01"},
        {"home_team": "TeamB", "away_team": "TeamA", "actual_home_goals": 2,
         "actual_away_goals": 2, "actual_result": "D", "kickoff_date": "2026-02-01"},
    ]
    _use_db(monkeypatch, dirty)
    eng = _engine()

    h = eng._build_h2h("TeamA", "TeamB", _match())

    assert h.meetings == 0  # doar 2 valide < 3 → fallback → empty


def test_recalc_ignores_precalculated_columns(monkeypatch):
    """Decizia 2: chiar dacă rândurile ar conține h2h_modifier/h2h_meetings
    (contaminate), recalculul le ignoră total — folosește doar rezultate."""
    rows = [dict(r, h2h_modifier=99.0, h2h_meetings=999) for r in DB_ROWS]
    _use_db(monkeypatch, rows)
    eng = _engine()

    h = eng._build_h2h("TeamA", "TeamB", _match())

    assert h.meetings == 4                     # nu 999
    assert abs(h.h2h_modifier - (-0.0375)) < 1e-9  # nu 99.0
