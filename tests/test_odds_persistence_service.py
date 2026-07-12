import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/claude/stubs")

from services.odds_persistence_service import OddsPersistenceService, PersistenceResult, MARKET


def _service():
    return OddsPersistenceService(supabase_client=_FakeSupabaseModule())


class _FakeSupabaseModule:
    """Simulează modulul supabase_client - doar get_client(), pt teste de
    validare/eligibilitate care nu ating deloc Supabase."""
    @staticmethod
    def get_client():
        return None


# ── Scope (ADR-006 §3) ───────────────────────────────────────────────────

def test_market_is_1x2_only():
    assert MARKET == "1X2"


# ── Validare cote (ADR-006 §1) ───────────────────────────────────────────

def test_valid_price_accepts_normal_odds():
    assert OddsPersistenceService._is_valid_price(2.05) is True
    assert OddsPersistenceService._is_valid_price("3.20") is True


def test_valid_price_rejects_null():
    assert OddsPersistenceService._is_valid_price(None) is False


def test_valid_price_rejects_nan():
    assert OddsPersistenceService._is_valid_price(float("nan")) is False


def test_valid_price_rejects_infinity():
    assert OddsPersistenceService._is_valid_price(float("inf")) is False


def test_valid_price_rejects_less_or_equal_one():
    assert OddsPersistenceService._is_valid_price(1.0) is False
    assert OddsPersistenceService._is_valid_price(0.5) is False


def test_valid_price_rejects_negative():
    assert OddsPersistenceService._is_valid_price(-2.5) is False


def test_valid_price_rejects_invalid_type():
    assert OddsPersistenceService._is_valid_price("not_a_number") is False
    assert OddsPersistenceService._is_valid_price([2.0]) is False


def test_valid_odds_set_requires_all_three_valid():
    assert OddsPersistenceService._is_valid_odds_set(2.0, 3.2, 3.5) is True
    assert OddsPersistenceService._is_valid_odds_set(2.0, None, 3.5) is False
    assert OddsPersistenceService._is_valid_odds_set(2.0, 3.2, 0.9) is False


# ── Eligibilitate — UTC explicit (ADR-006 §2) ────────────────────────────

def test_eligible_when_kickoff_in_future():
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    match = {"kickoff_utc": future}
    assert OddsPersistenceService._is_eligible(match) is True


def test_not_eligible_when_kickoff_in_past():
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    match = {"kickoff_utc": past}
    assert OddsPersistenceService._is_eligible(match) is False


def test_not_eligible_when_kickoff_missing():
    assert OddsPersistenceService._is_eligible({}) is False


def test_not_eligible_when_kickoff_malformed():
    assert OddsPersistenceService._is_eligible({"kickoff_utc": "not-a-date"}) is False


# ── Logica persist_odds_snapshot — cazuri care NU ajung sa scrie in DB ──

def test_match_without_fixture_id_is_skipped_as_error():
    service = _service()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    matches = [{"home_team": "A", "away_team": "B", "kickoff_utc": future}]
    result = service.persist_odds_snapshot(matches)
    assert result.attempted == 1
    assert len(result.errors) == 1
    assert result.written == 0


def test_ineligible_match_is_skipped_not_written():
    service = _service()
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    matches = [{"fixture_id": "fx1", "kickoff_utc": past,
                "home_odds": 2.0, "draw_odds": 3.2, "away_odds": 3.5, "bookmaker": "bet365"}]
    result = service.persist_odds_snapshot(matches)
    assert result.skipped_ineligible == 1
    assert result.written == 0


def test_match_without_any_odds_is_skipped():
    service = _service()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    matches = [{"fixture_id": "fx1", "kickoff_utc": future}]
    result = service.persist_odds_snapshot(matches)
    assert result.skipped_no_odds == 1
    assert result.written == 0


def test_invalid_odds_set_rejected_entirely_not_partial():
    """ADR-006 §1: un set invalid e respins INTEGRAL, nu partial."""
    service = _service()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    matches = [{"fixture_id": "fx1", "kickoff_utc": future,
                "home_odds": 2.0, "draw_odds": None, "away_odds": 3.5, "bookmaker": "bet365"}]
    result = service.persist_odds_snapshot(matches)
    assert result.skipped_invalid == 1
    assert result.written == 0


def test_missing_bookmaker_rejected():
    service = _service()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    matches = [{"fixture_id": "fx1", "kickoff_utc": future,
                "home_odds": 2.0, "draw_odds": 3.2, "away_odds": 3.5, "bookmaker": ""}]
    result = service.persist_odds_snapshot(matches)
    assert result.skipped_invalid == 1


def test_one_bad_fixture_does_not_stop_the_batch():
    """Izolare per-fixture - un meci invalid nu opreste restul lotului."""
    service = _service()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    matches = [
        {"home_team": "NoId", "away_team": "X", "kickoff_utc": future},  # fara fixture_id
        {"fixture_id": "fx2", "kickoff_utc": future},  # fara cote
    ]
    result = service.persist_odds_snapshot(matches)
    assert result.attempted == 2
    assert len(result.errors) == 1
    assert result.skipped_no_odds == 1
