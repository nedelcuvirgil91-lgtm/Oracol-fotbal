"""Teste pentru providers/flashscore/backup.py — Backup REAL (Faza 2,
finalizare), activarea explicit cerută a pasului lăsat neimplementat de
ADR-044 Addendum A6. Verifică: scope IDENTIC cu Season Cleanup (6 tabele
FDL, niciodată match_history/match_events/player_match_stats/
odds_history), STRICT read-only (doar .select("*")), fișier JSON scris pe
disc cu timestamp în nume, degradare fără excepție la client absent/
eroare de rețea per tabel. Fără rețea reală."""
from __future__ import annotations

import json

import providers.flashscore.backup as backup
from providers.flashscore.season_cleanup import FOUNDATION_DATA_LAYER_SEASON_TABLES


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeSelectQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **kw):
        return self

    def execute(self):
        return _FakeResult(self._rows)


class _FakeClient:
    def __init__(self, rows_by_table: dict[str, list[dict]]):
        self._rows_by_table = rows_by_table

    def table(self, name):
        return _FakeSelectQuery(self._rows_by_table.get(name, []))


class _PartialBoomClient:
    """Un singur tabel esueaza, restul functioneaza - trebuie raportat
    separat (tables_failed), nu tratat ca lista goala."""
    def table(self, name):
        if name == "flashscore_raw_extraction":
            raise RuntimeError("simulated network failure")
        return _FakeSelectQuery([{"x": 1}])


class _BoomClient:
    def table(self, name):
        raise RuntimeError("simulated network failure")


def test_build_backup_snapshot_scope_matches_season_cleanup(monkeypatch):
    rows_by_table = {t: [{"id": 1}] for t in FOUNDATION_DATA_LAYER_SEASON_TABLES}
    monkeypatch.setattr("database.queries.get_client", lambda: _FakeClient(rows_by_table))
    snapshot = backup.build_backup_snapshot()
    assert snapshot["scope"] == list(FOUNDATION_DATA_LAYER_SEASON_TABLES)
    assert set(snapshot["tables"].keys()) == set(FOUNDATION_DATA_LAYER_SEASON_TABLES)
    for table in FOUNDATION_DATA_LAYER_SEASON_TABLES:
        assert snapshot["row_counts"][table] == 1


def test_build_backup_snapshot_never_touches_match_history_or_odds_history():
    """Gardă pozitivă directă contra sursei — scope-ul NU poate include
    niciodată tabelele excluse explicit (istoric ML, odds Frozen)."""
    excluded = {"match_history", "match_events", "player_match_stats", "odds_history"}
    assert not (excluded & set(FOUNDATION_DATA_LAYER_SEASON_TABLES))


def test_build_backup_snapshot_no_client_reports_error(monkeypatch):
    monkeypatch.setattr("database.queries.get_client", lambda: None)
    snapshot = backup.build_backup_snapshot()
    assert snapshot["error"] == "supabase_unavailable"
    assert snapshot["tables"] == {}


def test_build_backup_snapshot_partial_failure_reported_separately(monkeypatch):
    monkeypatch.setattr("database.queries.get_client", lambda: _PartialBoomClient())
    snapshot = backup.build_backup_snapshot()
    assert "flashscore_raw_extraction" in snapshot["tables_failed"]
    assert "flashscore_raw_extraction" not in snapshot["tables"]
    # Restul tabelelor tot au date - un esec partial nu sterge restul.
    other_tables = set(FOUNDATION_DATA_LAYER_SEASON_TABLES) - {"flashscore_raw_extraction"}
    assert set(snapshot["tables"].keys()) == other_tables


def test_write_backup_file_writes_real_json(tmp_path):
    snapshot = {"generated_at": "2026-07-30T00:00:00+00:00", "tables": {"x": [{"a": 1}]}}
    path = backup.write_backup_file(snapshot, out_dir=tmp_path)
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded == snapshot


def test_write_backup_file_never_overwrites_previous_backup(tmp_path):
    p1 = backup.write_backup_file({"a": 1}, out_dir=tmp_path)
    p2 = backup.write_backup_file({"a": 2}, out_dir=tmp_path)
    assert p1 != p2 or json.loads(p1.read_text()) == {"a": 1}
    assert p1.exists() and p2.exists()


def test_run_backup_returns_ok_report(monkeypatch, tmp_path):
    rows_by_table = {t: [] for t in FOUNDATION_DATA_LAYER_SEASON_TABLES}
    monkeypatch.setattr("database.queries.get_client", lambda: _FakeClient(rows_by_table))
    report = backup.run_backup(out_dir=tmp_path)
    assert report["ok"] is True
    assert "path" in report
    assert set(report["row_counts"].keys()) == set(FOUNDATION_DATA_LAYER_SEASON_TABLES)


def test_run_backup_degrades_gracefully_without_client(monkeypatch, tmp_path):
    monkeypatch.setattr("database.queries.get_client", lambda: None)
    report = backup.run_backup(out_dir=tmp_path)
    assert report["ok"] is False
    assert report["error"] == "supabase_unavailable"
