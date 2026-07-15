"""
Teste pentru sync.backfill_features.ShotCountTracker — media de șuturi
TOTALE REALE (nu pe poartă — vezi ShotsTracker, neatins), calculată
walk-forward (doar din meciuri STRICT anterioare), sursă pentru
home_shot_avg_recent/away_shot_avg_recent (P7.1,
docs/03_ENGINE/P7_1_DESIGN_SHOT_DOMINANCE_2026-07-15.md), candidat la
ml_predictor.FEATURE_COLUMNS doar dacă ablația e Accepted —
docs/03_ENGINE/SHOT_DOMINANCE_ABLATION_2026-07-15.md.
"""
import sync.backfill_features as bf


def test_no_history_returns_none_not_approximated():
    t = bf.ShotCountTracker()
    assert t.get_avg_shots("Echipa Necunoscuta") is None


def test_average_computed_only_from_real_values():
    t = bf.ShotCountTracker()
    t.process_match("Arsenal", "Chelsea", 10.0, 12.0)
    t.process_match("Liverpool", "Arsenal", 8.0, 9.0)
    assert t.get_avg_shots("Arsenal") == (10.0 + 9.0) / 2


def test_none_values_not_recorded():
    """Un meci fara suturi reale (None) nu adauga nimic in istoric — nu
    se aproximeaza cu 0."""
    t = bf.ShotCountTracker()
    t.process_match("Arsenal", "Chelsea", None, 12.0)
    assert t.get_avg_shots("Arsenal") is None
    assert t.get_avg_shots("Chelsea") == 12.0


def test_pre_match_value_never_includes_current_match_zero_leakage():
    t = bf.ShotCountTracker()
    assert t.get_avg_shots("Arsenal") is None
    t.process_match("Arsenal", "Chelsea", 11.0, 9.0)
    assert t.get_avg_shots("Arsenal") == 11.0


def test_window_limits_history_like_form_tracker():
    t = bf.ShotCountTracker(window=3)
    for i in range(5):
        t.process_match("Arsenal", "Opponent", float(i), 1.0)
    assert t.get_avg_shots("Arsenal") == (2.0 + 3.0 + 4.0) / 3


def test_partial_window_never_requires_minimum_history():
    """Cerinta explicita din P7_1_IMPLEMENTATION_PLAN.md: media se
    calculeaza pe toate valorile disponibile (1..window), fara minim
    impus — identic cu FoulsTracker/CornerCardTracker."""
    t = bf.ShotCountTracker(window=10)
    t.process_match("Arsenal", "Opponent1", 5.0, 1.0)
    t.process_match("Arsenal", "Opponent2", 7.0, 1.0)
    assert t.get_avg_shots("Arsenal") == (5.0 + 7.0) / 2


def test_shots_on_target_tracker_untouched():
    """ShotCountTracker si ShotsTracker sunt clase distincte, independente
    — adaugarea celei dintai nu modifica in niciun fel comportamentul
    ShotsTracker (medie de shots_on_target, deja consumata de
    compute_team_offdef_rating)."""
    st = bf.ShotsTracker()
    sct = bf.ShotCountTracker()
    st.process_match("Arsenal", "Chelsea", 6.0, 4.0)
    sct.process_match("Arsenal", "Chelsea", 15.0, 10.0)
    assert st.get_avg_shots_on_target("Arsenal") == 6.0
    assert sct.get_avg_shots("Arsenal") == 15.0
