"""Verificare explicită de idempotență (cerință M0, reafirmată la
Foundation Data Layer: "reruns produc no duplicates") — `persist_match_
foundation_data()` rulat de 1, 2 și 10 ori contra ACELUIAȘI payload
(fixture-ul real, flashscore_full_tabs_poc), pe un fake Supabase in-memory
care simulează SEMANTICA reală `INSERT ... ON CONFLICT (...) DO UPDATE`
(nu doar verifică cheia de conflict, ca în test_database_queries_
flashscore_foundation_data_layer.py) — numărul de rânduri per tabelă
trebuie să rămână IDENTIC după 1, 2 și 10 rulări.

Fără rețea live — `upsert_match_and_get_id` (RPC pe match_history) e
mock-uit cu un id fix, pentru izolarea testului la cele 4 tabele EAV/
snapshot noi (match_history are deja acoperire de idempotență separată,
prin `_upsert_match_canonical_locked`/ADR-025)."""
from __future__ import annotations

from pathlib import Path

import pytest

from providers.flashscore.persistence import persist_match_foundation_data

FIXTURE_DIR = Path(__file__).parent.parent / "docs" / "06_UDAL" / "poc_evidence" / "flashscore_full_tabs_poc"


@pytest.fixture(scope="module")
def full_tabs_pages() -> dict[str, str]:
    return {f.stem: f.read_text(encoding="utf-8") for f in FIXTURE_DIR.glob("*.html")}


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _InMemoryUpsertTable:
    """Simuleaza `INSERT ... ON CONFLICT (on_conflict) DO UPDATE SET ...`:
    un dict cheiat pe tuplul valorilor coloanelor din `on_conflict`, id
    auto-incrementat DOAR la prima inserare a acelei chei (ca la Postgres
    - un id stabil intre rerun-uri, nu unul nou de fiecare data)."""

    def __init__(self, id_seq):
        self.rows_by_key: dict[tuple, dict] = {}
        self.id_seq = id_seq

    def upsert(self, payload, on_conflict=None):
        rows = payload if isinstance(payload, list) else [payload]
        conflict_cols = on_conflict.split(",")
        out_rows = []
        for row in rows:
            key = tuple(row.get(c) for c in conflict_cols)
            existing = self.rows_by_key.get(key)
            if existing is None:
                new_row = {**row, "id": next(self.id_seq)}
                self.rows_by_key[key] = new_row
            else:
                existing.update(row)
                new_row = existing
            out_rows.append(new_row)
        return _FakeExecuted(out_rows)

    @property
    def row_count(self) -> int:
        return len(self.rows_by_key)


class _FakeExecuted:
    def __init__(self, rows):
        self._rows = rows

    def execute(self):
        return _FakeResult(self._rows)


class _InMemorySupabase:
    def __init__(self):
        self._id_seq = iter(range(1, 1_000_000))
        self.tables: dict[str, _InMemoryUpsertTable] = {}

    def table(self, name: str) -> _InMemoryUpsertTable:
        if name not in self.tables:
            self.tables[name] = _InMemoryUpsertTable(self._id_seq)
        return self.tables[name]


@pytest.mark.parametrize("n_reruns", [1, 2, 10])
def test_persist_match_foundation_data_idempotent_across_reruns(monkeypatch, full_tabs_pages, n_reruns):
    fake_db = _InMemorySupabase()
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", lambda *a, **kw: 777)
    monkeypatch.setattr("database.queries.get_client", lambda: fake_db)

    reports = [persist_match_foundation_data(full_tabs_pages, competition="SuperLiga") for _ in range(n_reruns)]

    assert all(r["ok"] for r in reports)
    assert all(r["match_id"] == 777 for r in reports)

    # 26 statistici extinse (categorii fara coloana dedicata, fixture real).
    assert fake_db.table("match_statistics_extended").row_count == 26
    # 46 jucatori (23+23) din roster - stabil indiferent de numarul de rulari.
    assert fake_db.table("player_match_stats").row_count == 46
    # 32 randuri din tab-ul Player Stats, fiecare cu 7 statistici extinse.
    assert fake_db.table("player_match_stats_extended").row_count == 32 * 7
    # 15 intalniri H2H/forma recenta (5+5+5, segmentate).
    assert fake_db.table("flashscore_match_context").row_count == 15
    # 16 echipe in clasament.
    assert fake_db.table("flashscore_standings_snapshot").row_count == 16
    # 21 evenimente reale (timeline complet Summary - goluri/cartonase/schimbari/VAR).
    assert fake_db.table("match_events").row_count == 21


def test_persist_match_foundation_data_ids_stable_across_reruns(monkeypatch, full_tabs_pages):
    """Nu doar numarul de randuri - id-urile rezolvate raman ACELEASI intre
    rulari (dovada ca e update pe rand existent, nu insert nou)."""
    fake_db = _InMemorySupabase()
    monkeypatch.setattr("providers.flashscore.persistence.upsert_match_and_get_id", lambda *a, **kw: 777)
    monkeypatch.setattr("database.queries.get_client", lambda: fake_db)

    persist_match_foundation_data(full_tabs_pages, competition="SuperLiga")
    ids_after_first = {k: v["id"] for k, v in fake_db.table("player_match_stats").rows_by_key.items()}

    for _ in range(9):
        persist_match_foundation_data(full_tabs_pages, competition="SuperLiga")
    ids_after_ten = {k: v["id"] for k, v in fake_db.table("player_match_stats").rows_by_key.items()}

    assert ids_after_first == ids_after_ten
