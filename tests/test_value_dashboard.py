"""Teste pentru value_dashboard.py — pură agregare, fără rețea, fără Supabase."""
from dataclasses import dataclass, field

from value_dashboard import collect_value_bets


@dataclass
class _FakePred:
    """Doar câmpurile pe care collect_value_bets() chiar le citește."""
    fixture_id: str
    home_team: str
    away_team: str
    league: str
    kickoff_utc: str
    value_bets: list = field(default_factory=list)
    special_value_bets: list = field(default_factory=list)
    kelly_stakes: dict = field(default_factory=dict)


def test_collect_value_bets_merges_1x2_and_special_markets():
    pred = _FakePred(
        fixture_id="fx1", home_team="A", away_team="B", league="Premier League", kickoff_utc="2026-07-14T15:00:00Z",
        value_bets=[{"market": "1X2", "selection": "Home Win", "edge_pct": 8.5, "model_prob_pct": 55.0,
                     "bk_odds": 1.9, "rating": "🔥 HIGH"}],
        special_value_bets=[{"market": "Over 2.5", "model_prob_pct": 60.0, "bk_odds": 1.8, "edge_pct": 6.2,
                              "rating": "✅ MEDIUM"}],
        kelly_stakes={"Home Win": 12.5},
    )

    rows = collect_value_bets([pred])

    assert len(rows) == 2
    assert rows[0].market == "1X2" and rows[0].selection == "Home Win" and rows[0].kelly_stake == 12.5
    assert rows[1].market == "Over 2.5" and rows[1].kelly_stake is None


def test_collect_value_bets_sorted_by_edge_descending_across_matches():
    pred_a = _FakePred(fixture_id="fx1", home_team="A", away_team="B", league="L1", kickoff_utc="",
                        value_bets=[{"market": "1X2", "selection": "Home Win", "edge_pct": 5.0}])
    pred_b = _FakePred(fixture_id="fx2", home_team="C", away_team="D", league="L1", kickoff_utc="",
                        value_bets=[{"market": "1X2", "selection": "Away Win", "edge_pct": 15.0}])

    rows = collect_value_bets([pred_a, pred_b])

    assert [r.fixture_id for r in rows] == ["fx2", "fx1"]
    assert rows[0].edge_pct == 15.0


def test_collect_value_bets_ignores_none_predictions():
    pred = _FakePred(fixture_id="fx1", home_team="A", away_team="B", league="L1", kickoff_utc="",
                      value_bets=[{"market": "1X2", "selection": "Draw", "edge_pct": 9.0}])

    rows = collect_value_bets([None, pred, None])

    assert len(rows) == 1
    assert rows[0].selection == "Draw"


def test_collect_value_bets_empty_input_returns_empty_list():
    assert collect_value_bets([]) == []


def test_collect_value_bets_match_with_no_value_bets_contributes_nothing():
    pred = _FakePred(fixture_id="fx1", home_team="A", away_team="B", league="L1", kickoff_utc="")
    assert collect_value_bets([pred]) == []
