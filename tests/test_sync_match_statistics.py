"""Teste pentru sync/sync_match_statistics.py (Sprint 1, ADR-039 / ADR-041
Faza 1). Fără rețea — database.queries.get_finished_matches_missing_stats(),
choose_provider()/fallback_chain() și adaptoarele sunt fake-uite. Verifică
inclusiv wiring-ul nou: alegerea providerului prin sync_provider_manager,
fallback runtime PER MECI către restul lanțului static, și "sportapi"
(fără adaptor implementat) sărit explicit, nu tratat ca eroare."""
from __future__ import annotations

import pytest

from sync import sync_match_statistics
from sync_orchestrator import SyncOrchestrator
from sync_provider_manager import ProviderChoice


class _AlwaysAllowRequestManager:
    def should_request(self, provider):
        return True


class _FakeAdapter:
    def __init__(self, provider_id, raw_by_match=None):
        self.provider_id = provider_id
        self._raw_by_match = raw_by_match or {}
        self.persisted: list = []
        self.fetch_calls: list = []

    def fetch(self, params):
        self.fetch_calls.append(params)
        key = (params["home_team"], params["away_team"], params["kickoff_date"])
        return self._raw_by_match.get(key)

    def normalize(self, raw):
        return [raw] if raw else []

    def validate(self, records):
        return records

    def persist(self, records):
        self.persisted.extend(records)
        return True


_MATCH = {"home_team": "Arsenal", "away_team": "Chelsea",
          "kickoff_date": "2026-01-01", "league": "Premier League"}


@pytest.fixture(autouse=True)
def _clear_adapter_cache():
    sync_match_statistics._adapter_cache.clear()
    yield
    sync_match_statistics._adapter_cache.clear()


def test_matches_missing_stats_delegates_to_query(monkeypatch):
    """[REPARAT Sprint 3, Prioritatea 1] `require_referee=True` — vezi
    docstring-ul `_matches_missing_stats()`: fără el, un meci deja completat
    de FreeLF cu possession+xG dispărea permanent din rezultat, iar Soccer
    Football Info nu mai apuca să încerce restul câmpurilor."""
    rows = [dict(_MATCH)]
    calls = []
    monkeypatch.setattr(
        "database.queries.get_finished_matches_missing_stats",
        lambda days_back, require_referee=False: (calls.append((days_back, require_referee)), rows)[1],
    )
    result = sync_match_statistics._matches_missing_stats(days_back=3)
    assert result == rows
    assert calls == [(3, True)]


def test_provider_order_uses_choice_then_rest_of_fallback_chain(monkeypatch):
    monkeypatch.setattr(sync_match_statistics, "choose_provider",
                         lambda domain, league, intent: ProviderChoice(
                             provider_id="freelivefootball", via_selection_engine=False,
                             weights_name=None, weights_version=None, reason="test"))
    monkeypatch.setattr(sync_match_statistics, "fallback_chain",
                         lambda domain: ("soccerfootballinfo", "freelivefootball", "sportapi"))
    order = sync_match_statistics._provider_order("Premier League")
    assert order == ["freelivefootball", "soccerfootballinfo", "sportapi"]


def test_provider_order_empty_when_no_choice_and_no_chain(monkeypatch):
    monkeypatch.setattr(sync_match_statistics, "choose_provider",
                         lambda domain, league, intent: ProviderChoice(
                             provider_id=None, via_selection_engine=False,
                             weights_name=None, weights_version=None, reason="test"))
    monkeypatch.setattr(sync_match_statistics, "fallback_chain", lambda domain: ())
    assert sync_match_statistics._provider_order("Premier League") == []


def test_task_runner_skips_when_no_provider_resolves():
    adapter = _FakeAdapter("freelivefootball", raw_by_match={})
    sync_match_statistics._adapter_cache["freelivefootball"] = adapter
    runner = sync_match_statistics._make_task_runner(_MATCH, ["freelivefootball"])
    runner()  # nu trebuie sa arunce exceptie
    assert adapter.persisted == []


def test_task_runner_persists_when_primary_provider_resolves():
    key = ("Arsenal", "Chelsea", "2026-01-01")
    adapter = _FakeAdapter("soccerfootballinfo", raw_by_match={key: {"home_possession": 58}})
    sync_match_statistics._adapter_cache["soccerfootballinfo"] = adapter
    runner = sync_match_statistics._make_task_runner(_MATCH, ["soccerfootballinfo"])
    runner()
    assert len(adapter.persisted) == 1


def test_task_runner_falls_back_to_second_provider_when_first_returns_none():
    key = ("Arsenal", "Chelsea", "2026-01-01")
    primary = _FakeAdapter("soccerfootballinfo", raw_by_match={})  # nu rezolvă (ligă neacoperită)
    fallback = _FakeAdapter("freelivefootball", raw_by_match={key: {"home_possession": 55.0}})
    sync_match_statistics._adapter_cache["soccerfootballinfo"] = primary
    sync_match_statistics._adapter_cache["freelivefootball"] = fallback

    runner = sync_match_statistics._make_task_runner(_MATCH, ["soccerfootballinfo", "freelivefootball"])
    runner()

    assert len(primary.fetch_calls) == 1
    assert len(fallback.fetch_calls) == 1
    assert len(primary.persisted) == 0
    assert len(fallback.persisted) == 1


def test_task_runner_stops_at_first_success_never_tries_later_providers():
    key = ("Arsenal", "Chelsea", "2026-01-01")
    primary = _FakeAdapter("soccerfootballinfo", raw_by_match={key: {"home_possession": 58}})
    fallback = _FakeAdapter("freelivefootball", raw_by_match={key: {"home_possession": 55.0}})
    sync_match_statistics._adapter_cache["soccerfootballinfo"] = primary
    sync_match_statistics._adapter_cache["freelivefootball"] = fallback

    runner = sync_match_statistics._make_task_runner(_MATCH, ["soccerfootballinfo", "freelivefootball"])
    runner()

    assert len(primary.persisted) == 1
    assert fallback.fetch_calls == []  # niciodată încercat — primul a reușit deja


def test_task_runner_skips_provider_without_adapter_implemented():
    """'sportapi' e în lanțul static (Sprint 1 v6, §3) dar fără adaptor
    concret azi — trebuie sărit, nu trebuie să oprească întregul task."""
    key = ("Arsenal", "Chelsea", "2026-01-01")
    fallback = _FakeAdapter("freelivefootball", raw_by_match={key: {"home_possession": 55.0}})
    sync_match_statistics._adapter_cache["freelivefootball"] = fallback

    runner = sync_match_statistics._make_task_runner(_MATCH, ["sportapi", "freelivefootball"])
    runner()  # nu trebuie sa arunce exceptie pentru 'sportapi'
    assert len(fallback.persisted) == 1


def test_run_registers_one_task_per_match_and_executes(monkeypatch):
    matches = [
        dict(_MATCH),
        {"home_team": "Liverpool", "away_team": "Everton",
         "kickoff_date": "2026-01-02", "league": "Premier League"},
    ]
    monkeypatch.setattr(sync_match_statistics, "_matches_missing_stats", lambda days_back: matches)
    monkeypatch.setattr(sync_match_statistics, "_provider_order", lambda league: ["freelivefootball"])

    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_match_statistics, "get_sync_orchestrator", lambda: fake_orchestrator)
    sync_match_statistics._adapter_cache["freelivefootball"] = _FakeAdapter("freelivefootball")

    results = sync_match_statistics.run(days_back=2)
    assert len(results) == 2
    assert all(r.ran for r in results)


def test_run_with_zero_matches_registers_nothing(monkeypatch):
    monkeypatch.setattr(sync_match_statistics, "_matches_missing_stats", lambda days_back: [])
    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_match_statistics, "get_sync_orchestrator", lambda: fake_orchestrator)

    results = sync_match_statistics.run(days_back=2)
    assert results == []


def test_run_skips_match_when_provider_order_is_empty(monkeypatch):
    monkeypatch.setattr(sync_match_statistics, "_matches_missing_stats", lambda days_back: [dict(_MATCH)])
    monkeypatch.setattr(sync_match_statistics, "_provider_order", lambda league: [])
    fake_orchestrator = SyncOrchestrator(request_manager=_AlwaysAllowRequestManager())
    monkeypatch.setattr(sync_match_statistics, "get_sync_orchestrator", lambda: fake_orchestrator)

    results = sync_match_statistics.run(days_back=2)
    assert results == []


def test_get_adapter_returns_none_for_unregistered_provider():
    assert sync_match_statistics._get_adapter("sportapi") is None


def test_get_adapter_caches_instance_per_provider(monkeypatch):
    created = []

    def _factory():
        created.append(1)
        return _FakeAdapter("freelivefootball")

    monkeypatch.setitem(sync_match_statistics._ADAPTER_FACTORIES, "freelivefootball", _factory)
    a1 = sync_match_statistics._get_adapter("freelivefootball")
    a2 = sync_match_statistics._get_adapter("freelivefootball")
    assert a1 is a2
    assert len(created) == 1
