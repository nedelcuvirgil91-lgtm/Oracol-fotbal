"""
Teste pentru sync.backfill_features.FoulsTracker — media de faulturi
REALE, calculată walk-forward (doar din meciuri STRICT anterioare), sursă
pentru home_foul_avg_recent/away_foul_avg_recent (ADR-013, promovate în
ml_predictor.FEATURE_COLUMNS după ablație —
docs/03_ENGINE/FOULS_DOMINANCE_ABLATION_2026-07-14.md).
"""
import sync.backfill_features as bf


def test_no_history_returns_none_not_approximated():
    t = bf.FoulsTracker()
    assert t.get_avg_fouls("Echipa Necunoscuta") is None


def test_average_computed_only_from_real_values():
    t = bf.FoulsTracker()
    t.process_match("Arsenal", "Chelsea", 10.0, 12.0)
    t.process_match("Liverpool", "Arsenal", 8.0, 9.0)
    assert t.get_avg_fouls("Arsenal") == (10.0 + 9.0) / 2


def test_none_values_not_recorded():
    """Un meci fara faulturi reale (None) nu adauga nimic in istoric — nu
    se aproximeaza cu 0."""
    t = bf.FoulsTracker()
    t.process_match("Arsenal", "Chelsea", None, 12.0)
    assert t.get_avg_fouls("Arsenal") is None
    assert t.get_avg_fouls("Chelsea") == 12.0


def test_pre_match_value_never_includes_current_match_zero_leakage():
    t = bf.FoulsTracker()
    assert t.get_avg_fouls("Arsenal") is None
    t.process_match("Arsenal", "Chelsea", 11.0, 9.0)
    assert t.get_avg_fouls("Arsenal") == 11.0


def test_window_limits_history_like_form_tracker():
    t = bf.FoulsTracker(window=3)
    for i in range(5):
        t.process_match("Arsenal", "Opponent", float(i), 1.0)
    assert t.get_avg_fouls("Arsenal") == (2.0 + 3.0 + 4.0) / 3
