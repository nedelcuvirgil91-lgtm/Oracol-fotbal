"""
Teste pentru sync.backfill_features.CornerCardTracker — medii glisante
REALE de cornere/cartonașe galbene, calculate walk-forward (doar din
meciuri STRICT anterioare), sursă pentru home_corner_avg_recent/
away_corner_avg_recent/home_card_avg_recent/away_card_avg_recent
(ADR-012, promovate în ml_predictor.FEATURE_COLUMNS după ablație —
docs/03_ENGINE/CORNER_CARD_DOMINANCE_ABLATION_2026-07-13.md).
"""
import sync.backfill_features as bf


def test_no_history_returns_none_not_approximated():
    t = bf.CornerCardTracker()
    assert t.get_avg_corners("Echipa Necunoscuta") is None
    assert t.get_avg_cards("Echipa Necunoscuta") is None


def test_average_computed_only_from_real_values():
    t = bf.CornerCardTracker()
    t.process_match("Arsenal", "Chelsea", 6.0, 3.0, 2.0, 1.0)
    t.process_match("Liverpool", "Arsenal", 5.0, 4.0, 3.0, 2.0)
    assert t.get_avg_corners("Arsenal") == (6.0 + 4.0) / 2
    assert t.get_avg_cards("Arsenal") == (2.0 + 2.0) / 2


def test_none_values_not_recorded():
    """Un meci fara date reale (None) nu adauga nimic in istoric — nu se
    aproximeaza cu 0, independent pentru cornere si cartonase."""
    t = bf.CornerCardTracker()
    t.process_match("Arsenal", "Chelsea", None, 3.0, None, 1.0)
    assert t.get_avg_corners("Arsenal") is None
    assert t.get_avg_corners("Chelsea") == 3.0
    assert t.get_avg_cards("Arsenal") is None
    assert t.get_avg_cards("Chelsea") == 1.0


def test_pre_match_value_never_includes_current_match_zero_leakage():
    """Valoarea intoarsa inainte de un meci trebuie sa foloseasca DOAR
    meciuri anterioare — testat direct prin secventa de apeluri, ca in
    run_backfill()."""
    t = bf.CornerCardTracker()
    # Inainte de primul meci al Arsenal, nu exista istoric
    assert t.get_avg_corners("Arsenal") is None
    assert t.get_avg_cards("Arsenal") is None
    t.process_match("Arsenal", "Chelsea", 8.0, 2.0, 1.0, 3.0)
    # DUPA primul meci, valoarea intra in istoric pentru meciul urmator
    assert t.get_avg_corners("Arsenal") == 8.0
    assert t.get_avg_cards("Arsenal") == 1.0


def test_window_limits_history_like_form_tracker():
    t = bf.CornerCardTracker(window=3)
    for i in range(5):
        t.process_match("Arsenal", "Opponent", float(i), 1.0, float(i), 1.0)
    # doar ultimele 3 valori (2,3,4) intra in medie
    assert t.get_avg_corners("Arsenal") == (2.0 + 3.0 + 4.0) / 3
    assert t.get_avg_cards("Arsenal") == (2.0 + 3.0 + 4.0) / 3


def test_corners_and_cards_tracked_independently():
    """O echipa poate avea istoric de cornere fara sa aiba (inca) istoric
    de cartonase, sau invers — cele doua liste nu se amesteca."""
    t = bf.CornerCardTracker()
    t.process_match("Arsenal", "Chelsea", 6.0, 3.0, None, None)
    assert t.get_avg_corners("Arsenal") == 6.0
    assert t.get_avg_cards("Arsenal") is None
