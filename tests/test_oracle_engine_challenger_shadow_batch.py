"""Teste pentru ADR-056 — FootballOracleEngine.log_challenger_shadow_for_week().
Fără instanță reală a motorului (ar necesita Supabase/API live) — testăm
direct logica pe o instanță minimală simulată, la fel ca restul testelor
din test_oracle_engine_compat.py."""
from __future__ import annotations

import oracle_engine


class _FakeAPI:
    def __init__(self, matches):
        self._matches = matches
        self.calls: list[int] = []

    def get_matches_for_week(self, days_ahead=7):
        self.calls.append(days_ahead)
        return self._matches


class _FakeEngine:
    log_challenger_shadow_for_week = oracle_engine.FootballOracleEngine.log_challenger_shadow_for_week

    def __init__(self, matches, evaluate_fn):
        self.api = _FakeAPI(matches)
        self._evaluate_fn = evaluate_fn

    def evaluate_match(self, m):
        return self._evaluate_fn(m)


def _match(home, away):
    return {"home_team": home, "away_team": away, "fixture_id": f"{home}_{away}"}


def test_evaluates_every_discovered_match():
    matches = [_match("A", "B"), _match("C", "D"), _match("E", "F")]
    seen = []

    def fake_evaluate(m):
        seen.append(m["fixture_id"])
        return object()  # orice non-None simulează MatchPrediction

    engine = _FakeEngine(matches, fake_evaluate)
    result = engine.log_challenger_shadow_for_week(days_ahead=7)

    assert seen == ["A_B", "C_D", "E_F"]
    assert result == {"matches_checked": 3, "evaluated": 3}
    assert engine.api.calls == [7]


def test_passes_through_days_ahead():
    engine = _FakeEngine([], lambda m: object())
    engine.log_challenger_shadow_for_week(days_ahead=3)
    assert engine.api.calls == [3]


def test_none_result_not_counted_as_evaluated():
    matches = [_match("A", "B"), _match("C", "D")]

    def fake_evaluate(m):
        return None if m["fixture_id"] == "A_B" else object()

    engine = _FakeEngine(matches, fake_evaluate)
    result = engine.log_challenger_shadow_for_week()

    assert result == {"matches_checked": 2, "evaluated": 1}


def test_exception_on_one_match_does_not_stop_the_batch():
    matches = [_match("A", "B"), _match("C", "D"), _match("E", "F")]
    seen = []

    def fake_evaluate(m):
        seen.append(m["fixture_id"])
        if m["fixture_id"] == "C_D":
            raise RuntimeError("profil echipă indisponibil")
        return object()

    engine = _FakeEngine(matches, fake_evaluate)
    result = engine.log_challenger_shadow_for_week()

    assert seen == ["A_B", "C_D", "E_F"]  # bucla continuă după eșec
    assert result == {"matches_checked": 3, "evaluated": 2}


def test_empty_match_list_is_safe():
    engine = _FakeEngine([], lambda m: object())
    result = engine.log_challenger_shadow_for_week()
    assert result == {"matches_checked": 0, "evaluated": 0}
