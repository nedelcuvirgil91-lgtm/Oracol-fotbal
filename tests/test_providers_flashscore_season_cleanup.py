"""Teste pentru providers/flashscore/season_cleanup.py (regula 8, TASK
APROBAT M1 + "Raspuns oficial - Foundation Data Layer"). Verifica
explicit:
(1) discover_seasons() e pura, fara I/O, calculeaza corect candidatii
    de cleanup sub politica de retentie (6 sezoane: curent + 5 istorice);
(2) sezoanele necunoscute (None - providerul nu le-a oferit) NU intra
    niciodata in calculul de candidati, raportate separat;
(3) delete_executed e MEREU False - acest modul nu sterge nimic;
(4) build_cleanup_dry_run_report() degradeaza gratios fara Supabase.

Fara retea live."""
from __future__ import annotations

from providers.flashscore.season_cleanup import (
    FOUNDATION_DATA_LAYER_SEASON_TABLES,
    RETENTION_SEASON_COUNT,
    build_cleanup_dry_run_report,
    discover_seasons,
)


def test_retention_policy_is_6_seasons():
    assert RETENTION_SEASON_COUNT == 6


def test_scope_excludes_match_history_and_odds_history():
    """Scope EXCLUSIV Foundation Data Layer - match_history/match_events/
    player_match_stats de baza si odds_history (Frozen) NU sunt in scope
    (Raspuns oficial, pct. 2)."""
    assert "match_history" not in FOUNDATION_DATA_LAYER_SEASON_TABLES
    assert "match_events" not in FOUNDATION_DATA_LAYER_SEASON_TABLES
    assert "odds_history" not in FOUNDATION_DATA_LAYER_SEASON_TABLES
    assert "player_match_stats" not in FOUNDATION_DATA_LAYER_SEASON_TABLES


def test_discover_seasons_no_candidates_when_within_retention():
    table_counts = {
        "match_statistics_extended": {
            "2022-2023": 10, "2023-2024": 12, "2024-2025": 15,
        },
    }
    report = discover_seasons(table_counts)
    assert report["known_seasons_found"] == ["2022-2023", "2023-2024", "2024-2025"]
    assert report["cleanup_candidates"] == []
    assert report["seasons_to_keep"] == ["2022-2023", "2023-2024", "2024-2025"]
    assert report["delete_executed"] is False
    assert report["dry_run"] is True


def test_discover_seasons_flags_oldest_beyond_retention():
    table_counts = {
        "match_statistics_extended": {
            "2019-2020": 5, "2020-2021": 8, "2021-2022": 9, "2022-2023": 10,
            "2023-2024": 12, "2024-2025": 15, "2025-2026": 20, "2026-2027": 3,
        },
    }
    report = discover_seasons(table_counts)
    # 8 sezoane reale gasite, politica = 6 -> primele 2 (cele mai vechi) candidate.
    assert report["cleanup_candidates"] == ["2019-2020", "2020-2021"]
    assert report["seasons_to_keep"] == [
        "2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026", "2026-2027",
    ]


def test_discover_seasons_never_treats_unknown_as_real_season():
    """Randurile fara sezon (None) sunt raportate separat - NU intra in
    known_seasons_found, NU influenteaza cleanup_candidates."""
    table_counts = {
        "flashscore_raw_extraction": {None: 500, "2026-2027": 3},
    }
    report = discover_seasons(table_counts)
    assert report["known_seasons_found"] == ["2026-2027"]
    assert report["unknown_season_row_counts"] == {"flashscore_raw_extraction": 500}
    assert report["cleanup_candidates"] == []


def test_discover_seasons_delete_executed_always_false():
    report = discover_seasons({})
    assert report["delete_executed"] is False
    assert report["dry_run"] is True


def test_discover_seasons_empty_input():
    report = discover_seasons({})
    assert report["known_seasons_found"] == []
    assert report["cleanup_candidates"] == []
    assert report["unknown_season_row_counts"] == {}


def test_build_cleanup_dry_run_report_no_client(monkeypatch):
    monkeypatch.setattr("database.queries.get_client", lambda: None)
    report = build_cleanup_dry_run_report()
    assert report["error"] == "supabase_unavailable"
    assert report["delete_executed"] is False


class _FakeSelectQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **kw):
        return self

    def execute(self):
        class _Res:
            pass
        r = _Res()
        r.data = self._rows
        return r


class _FakeClient:
    def __init__(self, rows_by_table: dict[str, list[dict]]):
        self._rows_by_table = rows_by_table

    def table(self, name):
        return _FakeSelectQuery(self._rows_by_table.get(name, []))


def test_build_cleanup_dry_run_report_aggregates_real_rows(monkeypatch):
    rows_by_table = {
        "match_statistics_extended": [{"season": "2025-2026"}, {"season": "2025-2026"}, {"season": None}],
        "player_match_stats_extended": [{"season": "2025-2026"}],
        "flashscore_match_context": [],
        "flashscore_standings_snapshot": [{"season": None}],
        "flashscore_raw_extraction": [{"season": "2025-2026"}],
        "flashscore_data_completeness": [{"season": "2025-2026"}],
    }
    monkeypatch.setattr("database.queries.get_client", lambda: _FakeClient(rows_by_table))
    report = build_cleanup_dry_run_report()
    assert report["known_seasons_found"] == ["2025-2026"]
    assert report["cleanup_candidates"] == []
    assert report["delete_executed"] is False
    assert set(report["tables_scanned"]) == set(FOUNDATION_DATA_LAYER_SEASON_TABLES)


def test_build_cleanup_dry_run_report_survives_partial_table_failure(monkeypatch):
    class _BoomOnOneTable:
        def table(self, name):
            if name == "flashscore_raw_extraction":
                raise RuntimeError("simulated failure")
            return _FakeSelectQuery([])

    monkeypatch.setattr("database.queries.get_client", lambda: _BoomOnOneTable())
    report = build_cleanup_dry_run_report()
    assert "flashscore_raw_extraction" in report["tables_failed"]
    assert report["delete_executed"] is False
