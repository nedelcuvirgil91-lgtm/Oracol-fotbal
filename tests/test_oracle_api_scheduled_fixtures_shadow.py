"""Teste pentru hook-ul de shadow (R-Sync-7b, ADR-039/ADR-040, G2) din
oracle_api.get_matches_for_week() — fără rețea, urmând tiparul din
test_oracle_api_selection_engine_shadow.py (FootballOracleAPI.__new__).

G2: hook-ul e FOARTE SUBȚIRE (verifică flag, citește scheduled_fixtures,
apelează evaluatorul, persistă) — teste verifică exact acest contract,
plus integrarea automation_runs (fail-safe, principiul 6)."""
from __future__ import annotations

import logging
from datetime import date

import oracle_api

_TODAY = date.today().isoformat()


def _api_no_network() -> oracle_api.FootballOracleAPI:
    api = oracle_api.FootballOracleAPI.__new__(oracle_api.FootballOracleAPI)
    api._mem = {}
    api._ttl = 30
    api._cache_mgr = None
    api._dead_keys = set()
    api._freelf_exhausted = False
    api._active_sport_keys = set()
    api._api_football = None
    api._key_manager = None

    def _fixed_match(league: str, source: str, target_date: str) -> dict:
        return {
            "fixture_id": f"{source}_{league}_{target_date}", "home_team": "A", "away_team": "B",
            "kickoff_date": target_date, "kickoff_utc": f"{target_date}T18:00:00Z",
            "league": league, "source": source,
        }

    api._fetch_events_odds_api = lambda sport_key, days_ahead=7: []
    api._fetch_freelf_matches = lambda target, league: []
    api._fetch_matches_fd = lambda date_from, date_to, comp_codes=None: []
    api._fetch_matches_espn = lambda league, target_date: (
        [_fixed_match(league, "espn", target_date)]
        if league == "Romania SuperLiga" and target_date == _TODAY else []
    )
    api._fetch_matches_tsdb = lambda league_id, league_name: []
    api._fetch_matches_api_football = lambda league, date_from, date_to: []
    api._generate_demo_matches = lambda competitions: []
    api._attach_odds = lambda matches: matches
    return api


def _disable_selection_engine_shadow(monkeypatch):
    import shadow_config
    monkeypatch.setattr(shadow_config, "is_enabled", lambda: False)


def _enable_flag_stub_automation_runs(monkeypatch, run_id=1):
    import scheduled_fixtures_shadow_config
    monkeypatch.setattr(scheduled_fixtures_shadow_config, "is_enabled", lambda: True)

    import automation_runs as ar
    calls = {"write_run": [], "start_run": [], "complete_run": [], "fail_run": []}
    monkeypatch.setattr(ar, "write_run", lambda **kw: (calls["write_run"].append(kw), run_id)[1])
    monkeypatch.setattr(ar, "start_run", lambda rid: calls["start_run"].append(rid) or True)
    monkeypatch.setattr(ar, "complete_run", lambda rid, summary=None: calls["complete_run"].append((rid, summary)) or True)
    monkeypatch.setattr(ar, "fail_run", lambda rid, error_detail: calls["fail_run"].append((rid, error_detail)) or True)
    return calls


def test_shadow_hook_never_called_when_flag_disabled(monkeypatch):
    _disable_selection_engine_shadow(monkeypatch)

    import scheduled_fixtures_shadow_config
    monkeypatch.setattr(scheduled_fixtures_shadow_config, "is_enabled", lambda: False)

    import automation_runs as ar
    def _spy_write_run(**kw):
        raise AssertionError("write_run nu trebuie apelat cu flag OFF")
    monkeypatch.setattr(ar, "write_run", _spy_write_run)

    import database.queries as queries
    def _spy_list(*a, **kw):
        raise AssertionError("list_scheduled_fixtures nu trebuie apelat cu flag OFF")
    monkeypatch.setattr(queries, "list_scheduled_fixtures", _spy_list)

    api = _api_no_network()
    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert len(matches) == 1


def test_shadow_hook_return_value_identical_regardless_of_flag(monkeypatch):
    """Dovada structurala a Regulii de Aur #2: hook-ul citeste `matches`
    deja finalizat, nu-l modifica niciodata — indiferent daca shadow-ul
    reuseste, esueaza, sau nu ruleaza deloc, returul e identic."""
    _disable_selection_engine_shadow(monkeypatch)
    import scheduled_fixtures_shadow_config

    monkeypatch.setattr(scheduled_fixtures_shadow_config, "is_enabled", lambda: False)
    api_off = _api_no_network()
    matches_off = api_off.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    _enable_flag_stub_automation_runs(monkeypatch)
    import database.queries as queries
    monkeypatch.setattr(queries, "list_scheduled_fixtures",
                         lambda d_from, d_to: (_ for _ in ()).throw(RuntimeError("boom")))
    api_on = _api_no_network()
    matches_on = api_on.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert matches_off == matches_on


def test_shadow_hook_is_thin_calls_evaluate_and_persist_in_order(monkeypatch):
    """G2, principiul 2: hook-ul doar verifică flag -> citește
    scheduled_fixtures -> apelează evaluatorul -> persistă. Zero logică
    proprie de clasificare."""
    _disable_selection_engine_shadow(monkeypatch)
    ar_calls = _enable_flag_stub_automation_runs(monkeypatch, run_id=99)

    import database.queries as queries
    list_calls = []
    def _fake_list(d_from, d_to):
        list_calls.append((d_from, d_to))
        return [{"marker": "row"}]
    monkeypatch.setattr(queries, "list_scheduled_fixtures", _fake_list)

    import scheduled_fixtures_shadow

    class _FakeReport:
        live_count = 1
        scheduled_count = 1

    evaluate_calls = []
    _sentinel_report = _FakeReport()
    def _fake_evaluate(matches, scheduled_rows):
        evaluate_calls.append((matches, scheduled_rows))
        return _sentinel_report
    monkeypatch.setattr(scheduled_fixtures_shadow, "evaluate", _fake_evaluate)

    import equivalence_governance
    persist_calls = []
    def _fake_persist(**kw):
        persist_calls.append(kw)
        return True
    monkeypatch.setattr(equivalence_governance, "persist_equivalence_evaluation", _fake_persist)

    api = _api_no_network()
    api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert len(list_calls) == 1
    assert len(evaluate_calls) == 1
    assert evaluate_calls[0][1] == [{"marker": "row"}]
    assert len(persist_calls) == 1
    assert persist_calls[0]["gate_key"] == "R-Sync-7b"
    assert persist_calls[0]["entity"] == "scheduled_fixtures"
    assert persist_calls[0]["report"] is _sentinel_report
    assert persist_calls[0]["run_id"] == 99

    assert len(ar_calls["write_run"]) == 1
    assert ar_calls["write_run"][0]["producer"] == "ADR-040"
    assert ar_calls["write_run"][0]["process_type"] == "equivalence_evaluation"
    assert ar_calls["write_run"][0]["tier"] == "T1"
    assert len(ar_calls["start_run"]) == 1
    assert ar_calls["start_run"][0] == 99
    assert len(ar_calls["complete_run"]) == 1
    assert ar_calls["complete_run"][0][0] == 99
    assert ar_calls["fail_run"] == []


def test_shadow_hook_exception_never_propagates(monkeypatch):
    _disable_selection_engine_shadow(monkeypatch)
    _enable_flag_stub_automation_runs(monkeypatch)

    import database.queries as queries
    monkeypatch.setattr(queries, "list_scheduled_fixtures",
                         lambda d_from, d_to: (_ for _ in ()).throw(RuntimeError("boom")))

    api = _api_no_network()
    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])
    assert len(matches) == 1


def test_shadow_hook_failure_recorded_in_automation_runs_not_just_logged(monkeypatch):
    """G2, principiul 6: eșecul procesului se înregistrează în
    automation_runs (ADR-026), nu doar în log."""
    _disable_selection_engine_shadow(monkeypatch)
    ar_calls = _enable_flag_stub_automation_runs(monkeypatch, run_id=7)

    import database.queries as queries
    monkeypatch.setattr(queries, "list_scheduled_fixtures",
                         lambda d_from, d_to: (_ for _ in ()).throw(RuntimeError("boom")))

    api = _api_no_network()
    api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert len(ar_calls["fail_run"]) == 1
    assert ar_calls["fail_run"][0][0] == 7
    assert "boom" in ar_calls["fail_run"][0][1]
    assert ar_calls["complete_run"] == []


def test_shadow_hook_logs_error_when_shadow_itself_fails(monkeypatch, caplog):
    _disable_selection_engine_shadow(monkeypatch)
    _enable_flag_stub_automation_runs(monkeypatch)

    import database.queries as queries
    monkeypatch.setattr(queries, "list_scheduled_fixtures",
                         lambda d_from, d_to: (_ for _ in ()).throw(RuntimeError("boom")))

    api = _api_no_network()
    with caplog.at_level(logging.ERROR, logger="FootballOracle"):
        api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert any(r.levelno == logging.ERROR and "ScheduledFixturesShadow" in r.getMessage()
               for r in caplog.records)
