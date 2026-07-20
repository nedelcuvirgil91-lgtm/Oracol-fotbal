"""Teste pentru ADR-023 (Variant C) / ADR-035 D2 — ELO-ul de club se
citește PRIMUL din match_history.home_elo_after/away_elo_after (Canonical
Live ELO Snapshot), înaintea oricărui apel către provider extern
(oracle_api.get_elo_rating).

Cascada de ELO e independentă de cascada de statistici (D1) — testele de
aici dezactivează Level DB de statistici (listă goală din get_team_recent_
results) ca să izoleze exclusiv comportamentul ELO.

Toate testele pică pe codul pre-D2 (elo_raw = self.api.get_elo_rating(...)
necondiționat, la oracle_engine.py:677) și trec după."""
from __future__ import annotations

from types import SimpleNamespace

import oracle_engine


def _fake_api(elo_from_provider: int | None = None):
    return SimpleNamespace(
        get_elo_rating=lambda name: elo_from_provider,
        get_freelf_standings=lambda league: [],
        get_team_form_freelf=lambda tid, league, n: [],
        get_team_recent_form=lambda name, league, days_back=14: [],
        get_standings_form=lambda tid, league: None,
        get_team_stats=lambda tid, league: [],
    )


def _engine(elo_from_provider: int | None = None) -> oracle_engine.FootballOracleEngine:
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = _fake_api(elo_from_provider)
    return eng


def _fake_sb_no_history(monkeypatch):
    """Dezactivează Level DB de statistici (D1) — testele de aici verifică
    DOAR cascada ELO, independentă de cascada de forma/goluri."""
    fake = SimpleNamespace(
        get_team_recent_results=lambda team, league, last_n=5, lookback_days=365: [],
        get_team_recent_shots=lambda team, league, last_n=5: [],
        get_team_recent_match_events=lambda team, league, last_n=5: [],
    )
    monkeypatch.setattr(oracle_engine, "sb", fake, raising=False)
    monkeypatch.setattr(oracle_engine, "SUPABASE_MODULE_AVAILABLE", True, raising=False)


def test_elo_comes_from_db_when_available(monkeypatch):
    """DB are prioritate asupra providerului — chiar dacă providerul ar
    întoarce o valoare diferită, DB câștigă (principiul de proiectare
    ADR-035)."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_latest_team_elo", lambda team: 1611, raising=False)
    eng = _engine(elo_from_provider=1500)  # valoare diferită, NU trebuie folosită

    p = eng._build_profile("tsdb_x", "Dinamo București", "Romania SuperLiga")

    assert p.elo_rating == 1611


def test_falls_back_to_provider_when_db_returns_none(monkeypatch):
    """Echipă fără meciuri de club sincronizate (tipic: națională) — cade
    pe get_elo_rating(), neschimbat."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_latest_team_elo", lambda team: None, raising=False)
    eng = _engine(elo_from_provider=2085)

    p = eng._build_profile("odds_x", "France", "World Cup 2026")

    assert p.elo_rating == 2085


def test_falls_back_to_provider_when_db_read_raises(monkeypatch):
    """Excepție la citirea DB nu crapă motorul — fallback automat pe
    provider, identic patternului D1."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)

    def _boom(team):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_latest_team_elo", _boom, raising=False)
    eng = _engine(elo_from_provider=1700)

    p = eng._build_profile("tsdb_x", "Petrolul Ploiești", "Romania SuperLiga")

    assert p.elo_rating == 1700


def test_falls_back_to_provider_when_db_queries_module_unavailable(monkeypatch):
    """Fără modulul database.queries, comportamentul pre-D2 e identic —
    nicio dependință nouă obligatorie."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", False, raising=False)
    eng = _engine(elo_from_provider=1900)

    p = eng._build_profile("tsdb_x", "Petrolul Ploiești", "Romania SuperLiga")

    assert p.elo_rating == 1900


def test_db_elo_read_is_called_with_team_name_only_no_league():
    """Boundary + pct. 3: get_latest_team_elo(team) primește un singur
    argument pozițional (echipa) — dovadă la nivelul call-site-ului că
    interogarea ELO e globală per club, nu per competiție."""
    import inspect
    sig = inspect.signature(oracle_engine.get_latest_team_elo)
    params = list(sig.parameters)
    assert params[0] != "league" and "league" not in params[:1]


def test_db_elo_read_receives_the_same_canonical_name_as_profile(monkeypatch):
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    captured = {}

    def _capture(team):
        captured["team"] = team
        return 1611

    monkeypatch.setattr(oracle_engine, "get_latest_team_elo", _capture, raising=False)
    eng = _engine(elo_from_provider=1500)

    p = eng._build_profile("tsdb_x", "Dinamo București", "Romania SuperLiga")

    assert captured["team"] == p.team_name
