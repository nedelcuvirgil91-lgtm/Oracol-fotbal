"""
Teste pentru sync.backfill_features.ShotsTracker — media de șuturi pe
poartă REALE, calculată walk-forward (doar din meciuri STRICT anterioare),
folosită de team_pre_match_rating() în locul proxy-ului sintetic avg_gf*0.45.
"""
import sync.backfill_features as bf


def test_no_history_returns_none_not_approximated():
    t = bf.ShotsTracker()
    assert t.get_avg_shots_on_target("Echipa Necunoscuta") is None


def test_average_computed_only_from_real_values():
    t = bf.ShotsTracker()
    t.process_match("Arsenal", "Chelsea", 6.0, 3.0)
    t.process_match("Liverpool", "Arsenal", 5.0, 4.0)
    assert t.get_avg_shots_on_target("Arsenal") == (6.0 + 4.0) / 2


def test_none_values_not_recorded():
    """Un meci fara sot real (None) nu adauga nimic in istoric — nu se
    aproximeaza cu 0."""
    t = bf.ShotsTracker()
    t.process_match("Arsenal", "Chelsea", None, 3.0)
    assert t.get_avg_shots_on_target("Arsenal") is None
    assert t.get_avg_shots_on_target("Chelsea") == 3.0


def test_pre_match_value_never_includes_current_match_zero_leakage():
    """team_pre_match_rating trebuie sa foloseasca DOAR meciuri anterioare —
    testat direct prin secventa de apeluri, ca in run_backfill()."""
    t = bf.ShotsTracker()
    # Inainte de primul meci al Arsenal, nu exista istoric
    assert t.get_avg_shots_on_target("Arsenal") is None
    t.process_match("Arsenal", "Chelsea", 8.0, 2.0)
    # DUPA primul meci, valoarea intra in istoric pentru meciul urmator
    assert t.get_avg_shots_on_target("Arsenal") == 8.0


def test_window_limits_history_like_form_tracker():
    t = bf.ShotsTracker(window=3)
    for i in range(5):
        t.process_match("Arsenal", "Opponent", float(i), 1.0)
    # doar ultimele 3 valori (2,3,4) intra in medie
    assert t.get_avg_shots_on_target("Arsenal") == (2.0 + 3.0 + 4.0) / 3


def test_team_pre_match_rating_uses_real_shots_when_available():
    from oracle_engine import DEFAULT_CONFIG, DEFAULT_WEIGHTS

    elo_tracker = bf.ELOTracker()
    form_tracker = bf.FormTracker()
    shots_tracker = bf.ShotsTracker()

    # Populam forma si soturile pentru Arsenal cu un meci anterior
    form_tracker.process_match("Arsenal", "Chelsea", 2, 0, "H")
    shots_tracker.process_match("Arsenal", "Chelsea", 9.0, 1.0)

    off_with_real, def_with_real, _, _ = bf.team_pre_match_rating(
        "Arsenal", "Test League", elo_tracker, form_tracker,
        dict(DEFAULT_WEIGHTS), dict(DEFAULT_CONFIG), shots_tracker,
    )
    off_with_proxy, def_with_proxy, _, _ = bf.team_pre_match_rating(
        "Arsenal", "Test League", elo_tracker, form_tracker,
        dict(DEFAULT_WEIGHTS), dict(DEFAULT_CONFIG), None,
    )
    # 9.0 soturi reale (fata de proxy gf*0.45=0.9) trebuie sa dea un offensive_rating diferit
    assert off_with_real != off_with_proxy
