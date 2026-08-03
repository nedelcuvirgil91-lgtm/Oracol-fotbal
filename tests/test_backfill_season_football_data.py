"""Teste pentru sync/backfill_season_football_data.py — backfill dedicat
season pe rânduri deja existente din football-data.org, ocolind
deliberat deduplicarea client-side din sync.sync_matches. Fără rețea,
fără Supabase live — fetch_all_leagues() și upsert_matches_bulk() sunt
mockate direct."""
from __future__ import annotations

import sync.backfill_season_football_data as backfill


def _fake_matches(league: str, season: int, n: int, with_season: bool = True):
    return [
        {
            "fixture_id": f"fd_{league}_{season}_{i}",
            "home_team": "A", "away_team": "B", "league": league,
            "kickoff_date": "2024-01-01", "actual_result": "H",
            "season": f"{season}-{season + 1}" if with_season else None,
        }
        for i in range(n)
    ]


def test_run_calls_upsert_with_all_fetched_matches_no_dedup(monkeypatch):
    """Nu trebuie sa apara nicio filtrare pe fixture_id existent — scriptul
    nu importa sync.sync_matches si nu apeleaza get_existing_fixture_ids()."""
    fetched = [("Premier League", 2023, _fake_matches("Premier League", 2023, 3))]
    monkeypatch.setattr(
        "sync.sources.football_data.fetch_all_leagues",
        lambda: iter(fetched),
    )
    upsert_calls = []
    monkeypatch.setattr(
        "database.queries.upsert_matches_bulk",
        lambda rows: (upsert_calls.append(rows) or (len(rows), 0)),
    )

    result = backfill.run(dry_run=False)

    assert len(upsert_calls) == 1
    assert len(upsert_calls[0]) == 3
    assert result["fetched"] == 3
    assert result["with_season"] == 3
    assert result["without_season"] == 0
    assert result["written_ok"] == 3
    assert result["errors"] == 0


def test_run_dry_run_skips_write(monkeypatch):
    fetched = [("La Liga", 2022, _fake_matches("La Liga", 2022, 2))]
    monkeypatch.setattr("sync.sources.football_data.fetch_all_leagues", lambda: iter(fetched))
    upsert_calls = []
    monkeypatch.setattr(
        "database.queries.upsert_matches_bulk",
        lambda rows: upsert_calls.append(rows),
    )

    result = backfill.run(dry_run=True)

    assert upsert_calls == []
    assert result["dry_run"] is True
    assert result["fetched"] == 2
    assert result["written_ok"] == 0


def test_run_reports_matches_without_season_separately(monkeypatch):
    """Meciurile pentru care providerul nu ofera season raman cu season=None
    in payload — nicio aproximare, dar tot ajung la upsert (celelalte
    coloane tot trebuie sincronizate)."""
    fetched = [("Serie A", 2021, _fake_matches("Serie A", 2021, 2, with_season=False))]
    monkeypatch.setattr("sync.sources.football_data.fetch_all_leagues", lambda: iter(fetched))
    monkeypatch.setattr("database.queries.upsert_matches_bulk", lambda rows: (len(rows), 0))

    result = backfill.run(dry_run=False)

    assert result["with_season"] == 0
    assert result["without_season"] == 2
    assert result["written_ok"] == 2


def test_run_no_matches_fetched_skips_upsert(monkeypatch):
    monkeypatch.setattr("sync.sources.football_data.fetch_all_leagues", lambda: iter([]))
    upsert_calls = []
    monkeypatch.setattr(
        "database.queries.upsert_matches_bulk",
        lambda rows: upsert_calls.append(rows),
    )

    result = backfill.run(dry_run=False)

    assert upsert_calls == []
    assert result["fetched"] == 0
    assert result["written_ok"] == 0
