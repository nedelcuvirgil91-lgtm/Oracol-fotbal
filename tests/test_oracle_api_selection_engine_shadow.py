"""Teste pentru hook-ul de shadow logging (ADR-034 PR5) din
oracle_api.get_matches_for_week() — fără rețea, urmând tiparul din
test_oracle_api_apifootball_fallback.py (FootballOracleAPI.__new__).

Regula de Aur #2 — dovadă structurală, nu doar asertată: cu
selection_engine_shadow_enabled=False (implicit), get_matches_for_week()
întoarce EXACT aceeași listă indiferent de flag, iar Selection Engine nu e
apelat niciodată."""
from __future__ import annotations

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
    # ESPN e sursa reala pentru Romania SuperLiga in fallback-ul actual
    # (Romania SuperLiga nu e in FREE_LF_LEAGUE_IDS) — un singur meci, in
    # prima zi a ferestrei, ca sa nu se deduplice cu el insusi.
    api._fetch_matches_espn = lambda league, target_date: (
        [_fixed_match(league, "espn", target_date)]
        if league == "Romania SuperLiga" and target_date == _TODAY else []
    )
    api._fetch_matches_tsdb = lambda league_id, league_name: []
    api._fetch_matches_api_football = lambda league, date_from, date_to: []
    api._generate_demo_matches = lambda competitions: []
    api._attach_odds = lambda matches: matches
    return api


def test_shadow_hook_never_called_when_flag_disabled(monkeypatch):
    calls = {"recommend": 0, "record": 0}

    import shadow_config
    monkeypatch.setattr(shadow_config, "is_enabled", lambda: False)

    import provider_selector
    def _spy_recommend(*a, **kw):
        calls["recommend"] += 1
        raise AssertionError("recommend_provider nu trebuie apelat cu flag OFF")
    monkeypatch.setattr(provider_selector, "recommend_provider", _spy_recommend)

    import shadow_recorder
    def _spy_record(*a, **kw):
        calls["record"] += 1
        raise AssertionError("record_shadow_recommendation nu trebuie apelat cu flag OFF")
    monkeypatch.setattr(shadow_recorder, "record_shadow_recommendation", _spy_record)

    api = _api_no_network()
    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert calls == {"recommend": 0, "record": 0}
    assert len(matches) == 1


def test_shadow_hook_return_value_identical_regardless_of_flag(monkeypatch):
    """Dovada structurala a Regulii de Aur #2: hook-ul citeste `matches`
    deja finalizat, nu-l modifica niciodata — indiferent daca Selection
    Engine reuseste, esueaza, sau nu ruleaza deloc, returul e identic."""
    import shadow_config
    import provider_selector

    matches_off = _api_no_network_with_flag(monkeypatch, shadow_config, enabled=False)

    monkeypatch.setattr(provider_selector, "recommend_provider",
                         lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("eroare simulata")))
    matches_on = _api_no_network_with_flag(monkeypatch, shadow_config, enabled=True)

    assert matches_off == matches_on


def _api_no_network_with_flag(monkeypatch, shadow_config_module, enabled: bool) -> list[dict]:
    monkeypatch.setattr(shadow_config_module, "is_enabled", lambda: enabled)
    api = _api_no_network()
    return api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])


def test_shadow_hook_invokes_selection_engine_when_flag_enabled(monkeypatch):
    import shadow_config
    monkeypatch.setattr(shadow_config, "is_enabled", lambda: True)

    import provider_selector
    recommend_calls = []

    def _fake_recommend(league, data_type, current_provider, **kw):
        recommend_calls.append((league, data_type, current_provider))
        return provider_selector.ProviderRecommendation(
            league=league, data_type=data_type, current_provider=current_provider,
            current_score=None, recommended_provider=None, recommended_score=None,
            reason=None, decision_changed=False,
        )
    monkeypatch.setattr(provider_selector, "recommend_provider", _fake_recommend)

    import shadow_recorder
    record_calls = []
    monkeypatch.setattr(shadow_recorder, "new_shadow_run_id", lambda: "fake-run-id")
    monkeypatch.setattr(shadow_recorder, "record_shadow_recommendation",
                         lambda rec, run_id: record_calls.append((rec, run_id)) or True)

    api = _api_no_network()
    api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])

    assert len(recommend_calls) == 1
    assert recommend_calls[0][0] == "Romania SuperLiga"
    assert recommend_calls[0][2] == "espn"  # singura sursa reala pentru aceasta liga
    assert len(record_calls) == 1
    assert record_calls[0][1] == "fake-run-id"


def test_shadow_hook_exception_never_propagates(monkeypatch):
    import shadow_config
    monkeypatch.setattr(shadow_config, "is_enabled", lambda: True)

    import provider_selector
    monkeypatch.setattr(provider_selector, "recommend_provider",
                         lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))

    api = _api_no_network()
    # Nu trebuie sa arunce - degradare gratioasa (Regula #8).
    matches = api.get_matches_for_week(days_ahead=7, competitions=["Romania SuperLiga"])
    assert len(matches) == 1
