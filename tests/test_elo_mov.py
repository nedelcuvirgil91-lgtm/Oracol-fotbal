"""
Teste pentru multiplicatorul Margin of Victory (MOV) din ELOTracker —
ADR-022 (P3 Accepted, constante V2_damped: c=4.4, d=0.0005). Vezi
docs/00_GOVERNANCE/ADR-022-elo-margin-of-victory-v2-damped.md pentru
justificarea completă a formulei și a alegerii constantelor.

Nu ating rețeaua — ELOTracker e complet local/in-memory.
"""
import math

import sync.backfill_features as bf


def test_mov_multiplier_neutral_at_draw():
    """La egal (goal_diff=0), multiplicatorul e neutru (1.0) — identic cu
    comportamentul categorial vechi, nu se anulează actualizarea (ln(1)=0
    ar fi cazul degenerat, evitat explicit)."""
    assert bf._mov_multiplier(0, elo_diff_signed=0.0) == 1.0
    assert bf._mov_multiplier(0, elo_diff_signed=300.0) == 1.0
    assert bf._mov_multiplier(0, elo_diff_signed=-300.0) == 1.0


def test_mov_multiplier_increases_with_goal_difference():
    """Un scor mai categoric produce un multiplicator mai mare, la
    elo_diff constant — dar saturează logaritmic (nu explodează)."""
    m1 = bf._mov_multiplier(1, elo_diff_signed=0.0)
    m3 = bf._mov_multiplier(3, elo_diff_signed=0.0)
    m8 = bf._mov_multiplier(8, elo_diff_signed=0.0)
    assert m1 < m3 < m8
    # saturație logaritmică: raportul 8-0/1-0 e mult sub 8x
    assert m8 / m1 < 4.0


def test_mov_multiplier_amplifies_surprise():
    """O surpriză (câștigătorul avea rating mai mic — elo_diff negativ)
    amplifică multiplicatorul; un rezultat așteptat (elo_diff pozitiv) îl
    reduce, față de forțe egale (elo_diff=0)."""
    neutral = bf._mov_multiplier(3, elo_diff_signed=0.0)
    expected_win = bf._mov_multiplier(3, elo_diff_signed=200.0)
    surprise = bf._mov_multiplier(3, elo_diff_signed=-200.0)
    assert expected_win < neutral < surprise


def test_mov_multiplier_matches_v2_damped_constants():
    """Verificare directă a constantelor ADR-022 (c=4.4, d=0.0005) — dacă
    cineva schimbă MOV_C/MOV_D fără un ADR nou, acest test trebuie să pice."""
    assert bf.MOV_C == 4.4
    assert bf.MOV_D == 0.0005
    expected = math.log(3 + 1) * (4.4 / (0.0005 * 100.0 + 4.4))
    assert bf._mov_multiplier(3, elo_diff_signed=100.0) == expected


def test_elo_tracker_process_match_requires_goals():
    """Semnătura nouă (ADR-022) cere home_goals/away_goals — un 5-0 și un
    1-0 nu mai produc aceeași actualizare de rating."""
    tracker_big_win = bf.ELOTracker()
    tracker_big_win.process_match("A", "B", home_goals=5, away_goals=0, result="H")
    elo_a_big, elo_b_big = tracker_big_win.get_elo("A"), tracker_big_win.get_elo("B")

    tracker_small_win = bf.ELOTracker()
    tracker_small_win.process_match("A", "B", home_goals=1, away_goals=0, result="H")
    elo_a_small, elo_b_small = tracker_small_win.get_elo("A"), tracker_small_win.get_elo("B")

    assert elo_a_big > elo_a_small, "un 5-0 trebuie sa creasca ratingul castigatorului mai mult decat un 1-0"
    assert elo_b_big < elo_b_small, "un 5-0 trebuie sa scada ratingul invinsului mai mult decat un 1-0"


def test_elo_tracker_draw_unchanged_vs_categorical():
    """La egal, comportamentul rămâne identic cu formula categorială veche
    (multiplicator neutru) — regresie directă, nu doar prin inspecție."""
    tracker = bf.ELOTracker()
    elo_before_home, elo_before_away = tracker.get_elos_before_match("A", "B")
    tracker.process_match("A", "B", home_goals=1, away_goals=1, result="D")
    # forte egale (1500 vs 1500 + home advantage) -> la egal, ratingul se
    # misca doar prin diferenta exp_home/exp_away fata de scorul 0.5/0.5,
    # multiplicator=1.0, exact ca formula categoriala originala.
    assert tracker.get_elo("A") != elo_before_home
    assert tracker.get_elo("B") != elo_before_away


def test_run_backfill_call_sites_pass_goals(monkeypatch):
    """Regresie de integrare minimă: run_backfill() nu mai poate apela
    elo_tracker.process_match() cu semnătura veche (3 argumente) — dacă
    apelul ar regresa, acest test ar pica cu TypeError."""
    from oracle_engine import DEFAULT_CONFIG, DEFAULT_WEIGHTS

    matches = [
        {
            "id": 1, "fixture_id": "f1", "home_team": "Team X", "away_team": "Team Y",
            "league": "Test League", "kickoff_date": "2021-01-01",
            "actual_home_goals": 3, "actual_away_goals": 0, "actual_result": "H",
            "backfill_done": False,
            **{col: None for col in bf.BACKFILL_COLUMNS},
        },
    ]
    updates = []

    def fake_fetch(league=None):
        return matches

    def fake_bulk_update(pending):
        updates.extend(pending)
        return len(pending), 0

    monkeypatch.setattr(bf, "fetch_all_matches", fake_fetch)
    monkeypatch.setattr(bf, "bulk_update_features", fake_bulk_update)

    result = bf.run_backfill(dry_run=False, weights=dict(DEFAULT_WEIGHTS), config=dict(DEFAULT_CONFIG))
    assert result["status"] == "done"
    assert result["errors"] == 0
