"""Teste pentru elo_ratings_adapter.py (R-Sync-4, ADR-039).

A treia implementare reală a SyncAdapter — un singur fetch() produce
ratinguri pentru TOATE echipele naționale cunoscute (tipar identic
R-Sync-3, football-data.org). fetch() delegă la
FootballOracleAPI.get_national_elo_ratings_raw() (Provider fals,
injectat, fără rețea reală)."""
from __future__ import annotations

from elo_ratings_adapter import EloRatingsAdapter


_RAW_RATINGS = {
    "France": 2085,
    "Brazil": 2050,
    "Unranked FC": 0,   # invalid — exclus de validate()
}


class _FakeOracleApi:
    def __init__(self, ratings=None):
        self._ratings = ratings if ratings is not None else dict(_RAW_RATINGS)
        self.calls: list = []

    def get_national_elo_ratings_raw(self):
        self.calls.append("get_national_elo_ratings_raw")
        return self._ratings


def test_fetch_delegates_to_api():
    fake = _FakeOracleApi()
    adapter = EloRatingsAdapter(api=fake)
    raw = adapter.fetch({})
    assert raw == _RAW_RATINGS
    assert fake.calls == ["get_national_elo_ratings_raw"]


def test_normalize_handles_none_payload():
    adapter = EloRatingsAdapter(api=_FakeOracleApi())
    assert adapter.normalize(None) == []


def test_normalize_handles_empty_payload():
    adapter = EloRatingsAdapter(api=_FakeOracleApi())
    assert adapter.normalize({}) == []


def test_normalize_produces_multiple_records_per_call():
    adapter = EloRatingsAdapter(api=_FakeOracleApi())
    raw = adapter.fetch({})
    records = adapter.normalize(raw)
    assert len(records) == 3
    by_name = {r["team_name"]: r["elo_rating"] for r in records}
    assert by_name["France"] == 2085
    assert by_name["Brazil"] == 2050


def test_normalize_calls_canonical_normalize_team_name_explicitly(monkeypatch):
    """Regresie directă, oglindă a verificării cerute la R-Sync-2/R-Sync-3:
    normalize() apelează EXPLICIT mecanismul canonic existent
    (mappings.normalize_team_name), chiar dacă sursa (get_national_elo_
    ratings_raw) întoarce deja chei canonice."""
    import mappings

    calls = []

    def _fake_normalize(name):
        calls.append(name)
        return f"CANONICAL[{name}]"

    monkeypatch.setattr(mappings, "normalize_team_name", _fake_normalize)
    adapter = EloRatingsAdapter(api=_FakeOracleApi(ratings={"France": 2085}))
    raw = adapter.fetch({})
    records = adapter.normalize(raw)

    assert calls == ["France"]
    assert records[0]["team_name"] == "CANONICAL[France]"


def test_validate_excludes_records_without_team_name():
    adapter = EloRatingsAdapter(api=_FakeOracleApi())
    records = [{"team_name": "France", "elo_rating": 2085}, {"elo_rating": 2050}]
    out = adapter.validate(records)
    assert out == [{"team_name": "France", "elo_rating": 2085}]


def test_validate_excludes_records_with_non_positive_elo():
    adapter = EloRatingsAdapter(api=_FakeOracleApi())
    records = [
        {"team_name": "France", "elo_rating": 2085},
        {"team_name": "Unranked FC", "elo_rating": 0},
        {"team_name": "Negative FC", "elo_rating": -5},
    ]
    out = adapter.validate(records)
    assert len(out) == 1
    assert out[0]["team_name"] == "France"


def test_persist_calls_upsert_national_team_elo_per_record(monkeypatch):
    calls = []

    def _fake_upsert(team, elo_rating):
        calls.append((team, elo_rating))
        return True

    monkeypatch.setattr("database.queries.upsert_national_team_elo", _fake_upsert)
    adapter = EloRatingsAdapter(api=_FakeOracleApi())
    ok = adapter.persist([{"team_name": "France", "elo_rating": 2085}])
    assert ok is True
    assert calls == [("France", 2085)]


def test_persist_returns_false_if_any_write_fails(monkeypatch):
    def _fake_upsert(team, elo_rating):
        return team == "France"

    monkeypatch.setattr("database.queries.upsert_national_team_elo", _fake_upsert)
    adapter = EloRatingsAdapter(api=_FakeOracleApi())
    ok = adapter.persist([
        {"team_name": "France", "elo_rating": 2085},
        {"team_name": "Brazil", "elo_rating": 2050},
    ])
    assert ok is False


def test_full_pipeline_fetch_normalize_validate_persist(monkeypatch):
    """End-to-end pe adaptorul complet, fara retea reala si fara Supabase real."""
    calls = []

    def _fake_upsert(team, elo_rating):
        calls.append(team)
        return True

    monkeypatch.setattr("database.queries.upsert_national_team_elo", _fake_upsert)
    fake_api = _FakeOracleApi()
    adapter = EloRatingsAdapter(api=fake_api)

    raw = adapter.fetch({})
    records = adapter.normalize(raw)
    records = adapter.validate(records)
    ok = adapter.persist(records)

    assert ok is True
    # "Unranked FC" (elo=0) e exclus de validate() — doar 2 randuri persistate
    assert sorted(calls) == ["Brazil", "France"]


def test_coverage_check_returns_true_deliberately():
    """Documentează comportamentul cerut explicit, oglindă a
    footballdata_form_adapter.coverage_check(): suprascris EXPLICIT (nu
    moștenit implicit din SyncAdapter), True fix, deliberat — fără concept
    de coverage pentru eloratings.net."""
    adapter = EloRatingsAdapter(api=_FakeOracleApi())
    assert adapter.coverage_check({"league": "orice"}) is True
    assert "coverage_check" in EloRatingsAdapter.__dict__
