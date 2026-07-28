"""Teste pentru funcțiile UDAL Faza 0 din supabase_client.py (ADR-042) —
fără rețea, fake client dedicat (suportă `.order()`, absent din
`_ChainableQuery` folosit de testele record_provider_call existente)."""
from __future__ import annotations

import supabase_client as sb


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeUdalQuery:
    def __init__(self, table_name, log, select_response=None):
        self._table = table_name
        self._log = log
        self._select_response = select_response if select_response is not None else []

    def select(self, *a, **kw): return self
    def insert(self, payload):
        self._log.append((self._table, "insert", payload))
        return self
    def eq(self, *a, **kw): return self
    def order(self, *a, **kw): return self
    def limit(self, *a, **kw): return self
    def execute(self): return _FakeResult(self._select_response)


class _FakeUdalClient:
    def __init__(self, select_responses=None):
        self.log: list[tuple[str, str, dict | None]] = []
        self._select_responses = select_responses or {}

    def table(self, name):
        return _FakeUdalQuery(name, self.log, self._select_responses.get(name))


def _with_fake_client(client, fn):
    original_get_client = sb.get_client
    sb.get_client = lambda: client
    try:
        return fn()
    finally:
        sb.get_client = original_get_client


# ── record_acquisition_run ─────────────────────────────────────────────

def test_record_acquisition_run_inserts_row():
    client = _FakeUdalClient()
    ok = _with_fake_client(client, lambda: sb.record_acquisition_run(
        target_data_type="statistics", target_league="Romania SuperLiga",
        tier="http_scraper", mode="HISTORICAL", source_id="pilot-ro-superliga",
        target_season="2025-2026", records_fetched=10, records_validated=8,
        records_persisted=8, records_rejected=2, duration_ms=1234.5,
    ))
    assert ok is True
    inserts = [e for e in client.log if e[0] == "acquisition_run_log" and e[1] == "insert"]
    assert len(inserts) == 1
    payload = inserts[0][2]
    assert payload["target_league"] == "Romania SuperLiga"
    assert payload["tier"] == "http_scraper"
    assert payload["mode"] == "HISTORICAL"
    assert payload["records_persisted"] == 8
    assert payload["drift_flags_raised"] == []


def test_record_acquisition_run_graceful_without_supabase():
    assert sb.record_acquisition_run(
        target_data_type="statistics", target_league="Romania SuperLiga",
        tier="http_scraper", mode="HISTORICAL", source_id="pilot-ro-superliga",
    ) is False


# ── record_acquisition_dead_letter ─────────────────────────────────────

def test_record_acquisition_dead_letter_inserts_row():
    client = _FakeUdalClient()
    ok = _with_fake_client(client, lambda: sb.record_acquisition_dead_letter(
        target_data_type="statistics", target_league="Romania SuperLiga",
        tier="http_scraper", mode="HISTORICAL", source_id="pilot-ro-superliga",
        raw_record={"goals": -1}, rejection_reason="negative_goals",
    ))
    assert ok is True
    inserts = [e for e in client.log if e[0] == "acquisition_dead_letter" and e[1] == "insert"]
    assert len(inserts) == 1
    assert inserts[0][2]["rejection_reason"] == "negative_goals"


def test_record_acquisition_dead_letter_graceful_without_supabase():
    assert sb.record_acquisition_dead_letter(
        target_data_type="statistics", target_league="Romania SuperLiga",
        tier="http_scraper", mode="HISTORICAL", source_id="pilot-ro-superliga",
        raw_record={}, rejection_reason="test",
    ) is False


# ── scraper selector map (get/set) ─────────────────────────────────────

def test_get_scraper_selector_map_returns_none_when_absent():
    client = _FakeUdalClient(select_responses={"scraper_selector_registry": []})
    result = _with_fake_client(client, lambda: sb.get_scraper_selector_map("pilot"))
    assert result is None


def test_get_scraper_selector_map_returns_latest():
    rows = [{"selector_map": {"score": ".score"}, "version": 3}]
    client = _FakeUdalClient(select_responses={"scraper_selector_registry": rows})
    result = _with_fake_client(client, lambda: sb.get_scraper_selector_map("pilot"))
    assert result == {"score": ".score"}


def test_get_scraper_selector_map_graceful_without_supabase():
    assert sb.get_scraper_selector_map("pilot") is None


def test_set_scraper_selector_map_starts_at_version_1_when_none_exist():
    client = _FakeUdalClient(select_responses={"scraper_selector_registry": []})
    ok = _with_fake_client(client, lambda: sb.set_scraper_selector_map(
        "pilot", {"score": ".score"}, "product-owner",
    ))
    assert ok is True
    inserts = [e for e in client.log if e[0] == "scraper_selector_registry" and e[1] == "insert"]
    assert inserts[0][2]["version"] == 1


def test_set_scraper_selector_map_increments_version():
    rows = [{"version": 4}]
    client = _FakeUdalClient(select_responses={"scraper_selector_registry": rows})
    _with_fake_client(client, lambda: sb.set_scraper_selector_map(
        "pilot", {"score": ".new-score"}, "product-owner",
    ))
    inserts = [e for e in client.log if e[0] == "scraper_selector_registry" and e[1] == "insert"]
    assert inserts[0][2]["version"] == 5


def test_set_scraper_selector_map_graceful_without_supabase():
    assert sb.set_scraper_selector_map("pilot", {}, "product-owner") is False
