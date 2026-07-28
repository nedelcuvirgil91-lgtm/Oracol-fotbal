"""Teste pentru udal_validation.py (UDAL Faza 1, ADR-042) — fără rețea."""
from __future__ import annotations

from udal_validation import validate_records, validate_identity_only, check_conflicts_with_match_history


def _valid_record(**overrides):
    base = {
        "home_team": "FC Pilot Nord", "away_team": "FC Pilot Sud",
        "kickoff_date": "2026-03-01",
        "home_corners": 6, "away_corners": 4,
        "home_cards": 2, "away_cards": 3,
        "home_fouls": 11, "away_fouls": 14,
    }
    base.update(overrides)
    return base


def test_valid_record_passes():
    result = validate_records([_valid_record()], source_tier="http_scraper", source_id="pilot")
    assert len(result.valid) == 1
    assert len(result.rejected) == 0
    assert result.validation_rate == 1.0


def test_missing_required_field_rejected():
    record = _valid_record()
    del record["away_corners"]
    result = validate_records([record], source_tier="http_scraper", source_id="pilot")
    assert len(result.valid) == 0
    assert result.rejected[0].reason.startswith("missing_required_fields")
    assert "away_corners" in result.rejected[0].reason


def test_negative_value_rejected():
    result = validate_records(
        [_valid_record(home_corners=-1)], source_tier="http_scraper", source_id="pilot",
    )
    assert len(result.valid) == 0
    assert result.rejected[0].reason == "negative_value:home_corners"


def test_non_numeric_field_rejected():
    result = validate_records(
        [_valid_record(home_corners="not-a-number")], source_tier="http_scraper", source_id="pilot",
    )
    assert len(result.valid) == 0
    assert result.rejected[0].reason == "non_numeric_field:home_corners"


def test_duplicate_natural_key_in_batch_rejected():
    records = [_valid_record(), _valid_record()]
    result = validate_records(records, source_tier="http_scraper", source_id="pilot")
    assert len(result.valid) == 1
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "duplicate_natural_key_in_batch"


def test_valid_record_gets_provenance_stamped():
    result = validate_records(
        [_valid_record()], source_tier="http_scraper", source_id="pilot-source",
        confidence="SCRAPED_UNVERIFIED",
    )
    prov = result.valid[0]["_provenance"]
    assert prov["source_tier"] == "http_scraper"
    assert prov["source_id"] == "pilot-source"
    assert prov["confidence"] == "SCRAPED_UNVERIFIED"
    assert "fetched_at" in prov


def test_validation_rate_computed_correctly():
    records = [_valid_record(), _valid_record(home_corners=-1), _valid_record(away_team="Alta Echipa")]
    result = validate_records(records, source_tier="http_scraper", source_id="pilot")
    assert len(result.valid) == 2  # primul valid + al treilea (nume diferit => cheie diferita)
    assert len(result.rejected) == 1
    assert result.validation_rate == 2 / 3


def test_validation_rate_zero_for_empty_input():
    result = validate_records([], source_tier="http_scraper", source_id="pilot")
    assert result.validation_rate == 0.0


def test_validate_identity_only_accepts_record_with_both_teams():
    record = {"teams": {"home_team": "Echipa A", "away_team": "Echipa B"}, "score": {"ft_home": "1"}}
    result = validate_identity_only([record], source_tier="http_scraper", source_id="site-x")
    assert len(result.valid) == 1
    assert result.valid[0]["_provenance"]["source_id"] == "site-x"
    assert result.valid[0]["score"] == {"ft_home": "1"}  # restul recordului ramane neatins


def test_validate_identity_only_rejects_missing_home_team():
    record = {"teams": {"home_team": None, "away_team": "Echipa B"}}
    result = validate_identity_only([record], source_tier="http_scraper", source_id="site-x")
    assert len(result.valid) == 0
    assert result.rejected[0].reason == "missing_team_identity"


def test_validate_identity_only_rejects_missing_teams_group_entirely():
    result = validate_identity_only([{}], source_tier="http_scraper", source_id="site-x")
    assert len(result.valid) == 0
    assert result.rejected[0].reason == "missing_team_identity"


def test_check_conflicts_graceful_without_supabase():
    assert check_conflicts_with_match_history([_valid_record()]) == []


def test_check_conflicts_empty_for_empty_input():
    assert check_conflicts_with_match_history([]) == []
