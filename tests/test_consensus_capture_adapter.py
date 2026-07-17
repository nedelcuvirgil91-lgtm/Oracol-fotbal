"""
Teste pentru learning_core.consensus_capture (adapter, ADR-033 Faza 1) —
comportamentul intern (fail-open, apel Supabase), fără rețea.
"""
from learning_core import consensus_capture as cc


def test_capture_delegates_to_supabase_client(monkeypatch):
    captured = {}

    def _fake_save(**kw):
        captured.update(kw)
        return True

    monkeypatch.setattr("supabase_client.save_consensus_capture_sample", _fake_save)

    result = cc.capture_raw_predictions(
        fixture_id="fx-1",
        raw_predictions=[{"family": "rule_based", "engine": "oracle_protocol",
                           "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}],
        league="Premier League", home_team="A", away_team="B", kickoff_date="2026-01-01",
    )

    assert result is True
    assert captured["fixture_id"] == "fx-1"
    assert captured["league"] == "Premier League"


def test_capture_returns_false_on_empty_raw_predictions():
    """raw_predictions gol = nimic de capturat - nu incearca Supabase deloc."""
    result = cc.capture_raw_predictions(
        fixture_id="fx-1", raw_predictions=[],
        league="Premier League", home_team="A", away_team="B", kickoff_date="2026-01-01",
    )
    assert result is False


def test_capture_fail_open_on_exception(monkeypatch):
    def _boom(**kw):
        raise RuntimeError("Supabase indisponibil")

    monkeypatch.setattr("supabase_client.save_consensus_capture_sample", _boom)

    result = cc.capture_raw_predictions(
        fixture_id="fx-1",
        raw_predictions=[{"family": "rule_based", "engine": "oracle_protocol",
                           "prob_home": 0.5, "prob_draw": 0.3, "prob_away": 0.2}],
        league="Premier League", home_team="A", away_team="B", kickoff_date="2026-01-01",
    )
    assert result is False
