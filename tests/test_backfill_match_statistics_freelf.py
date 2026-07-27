"""Teste pentru sync/backfill_match_statistics_freelf.py (Sprint 1). Fără
rețea — database.queries.get_finished_matches_missing_stats() și
MatchStatisticsAdapter fake-uite. Verifică separarea reală de
sincronizarea zilnică (fereastră explicită) și raportarea onestă (0
rezolvate ≠ eroare, per Regula #8)."""
from __future__ import annotations

from sync import backfill_match_statistics_freelf as mod


class _FakeAdapter:
    def __init__(self, raw_by_match=None, persist_ok=True):
        self._raw_by_match = raw_by_match or {}
        self._persist_ok = persist_ok
        self.persist_calls: list = []

    def fetch(self, params):
        key = (params["home_team"], params["away_team"], params["kickoff_date"])
        return self._raw_by_match.get(key)

    def normalize(self, raw):
        return [raw] if raw else []

    def validate(self, records):
        return records

    def persist(self, records):
        self.persist_calls.append(records)
        return self._persist_ok


_MATCHES = [
    {"home_team": "Arsenal", "away_team": "Chelsea", "kickoff_date": "2025-06-01", "league": "Premier League"},
    {"home_team": "Liverpool", "away_team": "Everton", "kickoff_date": "2025-06-02", "league": "Premier League"},
]


def test_reports_zero_resolved_when_freelf_has_no_historical_data(monkeypatch):
    """Cazul realist, neverificat: FreeLF nu (mai) are date pentru un
    interval vechi — raportat onest, NU tratat ca eroare."""
    monkeypatch.setattr("database.queries.get_finished_matches_missing_stats", lambda **kw: _MATCHES)
    monkeypatch.setattr(mod, "MatchStatisticsAdapter", lambda: _FakeAdapter(raw_by_match={}))

    result = mod.run_backfill("2025-05-26", "2025-06-25")
    assert result == {"candidates": 2, "resolved": 0, "written": 0, "unresolved": 2, "errors": 0}


def test_writes_resolved_matches(monkeypatch):
    key = ("Arsenal", "Chelsea", "2025-06-01")
    adapter = _FakeAdapter(raw_by_match={key: {"home_possession": 55.0}})
    monkeypatch.setattr("database.queries.get_finished_matches_missing_stats", lambda **kw: _MATCHES)
    monkeypatch.setattr(mod, "MatchStatisticsAdapter", lambda: adapter)

    result = mod.run_backfill("2025-05-26", "2025-06-25")
    assert result["candidates"] == 2
    assert result["resolved"] == 1
    assert result["unresolved"] == 1  # al doilea meci (Liverpool-Everton) neacoperit
    assert result["written"] == 1
    assert len(adapter.persist_calls) == 1


def test_dry_run_never_calls_persist(monkeypatch):
    key = ("Arsenal", "Chelsea", "2025-06-01")
    adapter = _FakeAdapter(raw_by_match={key: {"home_possession": 55.0}})
    monkeypatch.setattr("database.queries.get_finished_matches_missing_stats", lambda **kw: _MATCHES)
    monkeypatch.setattr(mod, "MatchStatisticsAdapter", lambda: adapter)

    result = mod.run_backfill("2025-05-26", "2025-06-25", dry_run=True)
    assert result["written"] == 1  # numarat, dar nescris
    assert adapter.persist_calls == []


def test_fetch_exception_counted_as_error_not_crash(monkeypatch):
    class _BoomAdapter(_FakeAdapter):
        def fetch(self, params):
            raise RuntimeError("boom")

    monkeypatch.setattr("database.queries.get_finished_matches_missing_stats", lambda **kw: _MATCHES)
    monkeypatch.setattr(mod, "MatchStatisticsAdapter", lambda: _BoomAdapter())

    result = mod.run_backfill("2025-05-26", "2025-06-25")
    assert result["errors"] == 2
    assert result["candidates"] == 2


def test_date_range_and_league_passed_through_to_query(monkeypatch):
    captured = {}

    def _fake_query(**kw):
        captured.update(kw)
        return []

    monkeypatch.setattr("database.queries.get_finished_matches_missing_stats", _fake_query)
    monkeypatch.setattr(mod, "MatchStatisticsAdapter", lambda: _FakeAdapter())

    mod.run_backfill("2025-05-26", "2025-06-25", league="Premier League")
    assert captured["date_from"] == "2025-05-26"
    assert captured["date_to"] == "2025-06-25"
    assert captured["league"] == "Premier League"
