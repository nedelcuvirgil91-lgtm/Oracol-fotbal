"""Teste pentru ADR-023 (Variant C) / ADR-035 D2 — ELO-ul de club se
citește PRIMUL din match_history.home_elo_after/away_elo_after (Canonical
Live ELO Snapshot), înaintea oricărui fallback pentru echipele naționale.

Cascada de ELO e independentă de cascada de statistici (D1) — testele de
aici dezactivează Level DB de statistici (listă goală din get_team_recent_
results) ca să izoleze exclusiv comportamentul ELO.

[ACTUALIZAT — ADR-039 R-Sync-4] Fallback-ul pentru naționale nu mai e
`self.api.get_elo_rating()` (apel live către eloratings.net) — e
`database.queries.get_national_team_elo()`, citire STRICT din Supabase
(`national_team_elo_snapshot`, populată de Sync Layer,
sync/sync_national_team_elo.py). Oracle Engine nu mai citește niciodată
live de la eloratings.net, sub nicio circumstanță — inclusiv când
`database.queries` nu e disponibil (test explicit mai jos)."""
from __future__ import annotations

from types import SimpleNamespace

import oracle_engine


def _fake_api():
    """`self.api` nu mai expune ELO/FreeLF/Odds formă — toate fallback-urile
    de mai jos vin strict din Supabase (get_national_team_elo,
    get_team_form_freelf_snapshot, get_team_recent_form_oddsapi),
    niciodată de la provider."""
    return SimpleNamespace(
        get_team_stats=lambda tid, league: [],
    )


def _engine() -> oracle_engine.FootballOracleEngine:
    eng = oracle_engine.FootballOracleEngine.__new__(oracle_engine.FootballOracleEngine)
    eng.weights = {}
    eng.config = {}
    eng.api = _fake_api()
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
    """DB (club) are prioritate asupra snapshot-ului național — chiar dacă
    acesta ar avea o valoare diferită, DB câștigă (principiul de
    proiectare ADR-035)."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_latest_team_elo", lambda team: 1611, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo",
                         lambda team: {"elo_rating": 1500}, raising=False)  # NU trebuie folosit
    eng = _engine()

    p = eng._build_profile("tsdb_x", "Dinamo București", "Romania SuperLiga")

    assert p.elo_rating == 1611


def test_falls_back_to_national_snapshot_when_db_returns_none(monkeypatch):
    """Echipă fără meciuri de club sincronizate (tipic: națională) — cade
    pe get_national_team_elo() (Supabase), niciodată pe apel live."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_latest_team_elo", lambda team: None, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo",
                         lambda team: {"elo_rating": 2085}, raising=False)
    eng = _engine()

    p = eng._build_profile("odds_x", "France", "World Cup 2026")

    assert p.elo_rating == 2085


def test_falls_back_to_national_snapshot_when_db_read_raises(monkeypatch):
    """Excepție la citirea DB de club nu crapă motorul — fallback automat
    pe snapshot-ul național, identic patternului D1."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)

    def _boom(team):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_latest_team_elo", _boom, raising=False)
    monkeypatch.setattr(oracle_engine, "get_national_team_elo",
                         lambda team: {"elo_rating": 1700}, raising=False)
    eng = _engine()

    p = eng._build_profile("tsdb_x", "Petrolul Ploiești", "Romania SuperLiga")

    assert p.elo_rating == 1700


def test_returns_none_when_national_snapshot_read_also_raises(monkeypatch):
    """Excepție și la citirea snapshot-ului național nu crapă motorul —
    elo_rating rămâne None (Regula #8: necunoscut, niciodată aproximat)."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", True, raising=False)
    monkeypatch.setattr(oracle_engine, "get_latest_team_elo", lambda team: None, raising=False)

    def _boom(team):
        raise RuntimeError("Supabase down")

    monkeypatch.setattr(oracle_engine, "get_national_team_elo", _boom, raising=False)
    eng = _engine()

    p = eng._build_profile("odds_x", "France", "World Cup 2026")

    assert p.elo_rating is None


def test_no_elo_when_db_queries_module_unavailable(monkeypatch):
    """[ACTUALIZAT R-Sync-4] Fără modulul database.queries, NU mai există
    niciun fallback (nici DB, nici snapshot național) — comportamentul
    pre-R-Sync-4 (fallback live la eloratings.net necondiționat de
    DB_QUERIES_MODULE_AVAILABLE) a fost eliminat deliberat: Oracle Engine
    nu mai citește niciodată live de la eloratings.net, sub nicio
    circumstanță (Decizia 5, ADR-039 R-Sync-4)."""
    _fake_sb_no_history(monkeypatch)
    monkeypatch.setattr(oracle_engine, "DB_QUERIES_MODULE_AVAILABLE", False, raising=False)
    eng = _engine()

    p = eng._build_profile("tsdb_x", "Petrolul Ploiești", "Romania SuperLiga")

    assert p.elo_rating is None


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
    eng = _engine()

    p = eng._build_profile("tsdb_x", "Dinamo București", "Romania SuperLiga")

    assert captured["team"] == p.team_name
