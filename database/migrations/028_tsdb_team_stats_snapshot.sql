-- =============================================================================
-- Football Oracle — Migration 028: tsdb_team_stats_snapshot (R-Sync-8, ADR-039)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--   - tsdb_fixture_adapter.py (comentariu R-Sync-7a): "Singurul adaptor care
--     furnizeaza tsdb_home_team_id/tsdb_away_team_id — cheia care deblocheaza
--     TheSportsDB team stats la R-Sync-8"
--
-- Scop STRICT: ultimele evenimente (meciuri terminate) TheSportsDB per
-- echipa, folosite de servirea live (oracle_engine._build_profile(), Level
-- 4 — ultimul fallback inainte de ELO sigmoid). Inlocuieste apelul live
-- `self.api.get_team_stats(team_id, league)` — citire STRICT din Supabase,
-- populata de Sync Layer (sync/sync_team_stats_tsdb.py, prin
-- TsdbTeamStatsAdapter). Oracle Engine NU scrie niciodata aici.
--
-- Identitate canonica: team_name_canonical (ADR-039 Principiul 7) — NU
-- id-ul numeric TheSportsDB direct (pastrat totusi in tsdb_team_id, doar
-- ca metadata de trasabilitate/re-sincronizare, nu ca cheie). Sursa
-- id-ului numeric: scheduled_fixtures.tsdb_home_team_id/tsdb_away_team_id
-- (migrare 023, R-Sync-7a) — Sync Layer citeste de-acolo echipele de
-- sincronizat, nu mai apeleaza cautare live de echipa.
--
-- `events` (JSONB) — pastreaza EXACT forma listei intoarse azi de
-- oracle_api.get_team_last_events_tsdb() (date/result/goals_for/
-- goals_against/shots_on_goal/possession), asa incat migrarea sa fie
-- "no defect, no rewrite" (ADR-038) — inclusiv formulele proxy existente
-- (shots_on_goal = goals_for*3.5, possession = 50.0 constant), NESCHIMBATE
-- aici. Gasit la audit, documentat separat (nu reparat tacit in aceasta
-- migrare): aceste doua campuri sunt aproximate, nu reale — vezi
-- docs/00_GOVERNANCE (nota R-Sync-8, gol de date preexistent).
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..027. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS tsdb_team_stats_snapshot (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    team_name_canonical    TEXT NOT NULL,
    tsdb_team_id           TEXT NOT NULL,

    events                 JSONB NOT NULL DEFAULT '[]'::jsonb,

    source_provider        TEXT NOT NULL DEFAULT 'thesportsdb',
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT tsdb_team_stats_snapshot_unique_team
        UNIQUE (team_name_canonical)
);

CREATE INDEX IF NOT EXISTS idx_tsdb_team_stats_snapshot_synced_at
    ON tsdb_team_stats_snapshot (synced_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..027.
ALTER TABLE tsdb_team_stats_snapshot ENABLE ROW LEVEL SECURITY;
