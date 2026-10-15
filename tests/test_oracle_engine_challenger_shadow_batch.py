"""Teste pentru ADR-056 — FootballOracleEngine.log_challenger_shadow_for_week().
Fără instanță reală a motorului (ar necesita Supabase/API live) — testăm
direct logica pe o instanță minimală simulată, la fel ca restul testelor
din test_oracle_engine_compat.py."""
from __future__ import annotations

import oracle_engine


class _FakeAPI:
    """Oglindește semnătura reală, inclusiv `competitions`.

    [ACTUALIZAT 2026-10-15] Înainte, falsul accepta DOAR `days_ahead`, iar
    batch-ul chema fără competiții. Semnătura incompletă nu era doar o
    scăpare: făcea imposibil de testat exact defectul care a stat un sezon
    în producție — batch-ul vedea 16 din 18 competiții, fiindcă
    `get_matches_for_week()` cădea pe `ODDS_SPORT_KEYS`. Falsul înregistrează
    acum și competițiile primite, ca garda să poată verifica CE s-a cerut,
    nu doar că s-a cerut ceva."""

    def __init__(self, matches):
        self._matches = matches
        self.calls: list[int] = []
        self.competitii_primite: list[list[str] | None] = []

    def get_matches_for_week(self, days_ahead=7, competitions=None):
        self.calls.append(days_ahead)
        self.competitii_primite.append(competitions)
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
