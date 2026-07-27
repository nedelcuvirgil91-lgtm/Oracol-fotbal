-- =============================================================================
-- Football Oracle — Migration 018: footballdata_team_form_snapshot (R-Sync-3, ADR-039)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--   - docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md §5/§6b
--
-- Scop STRICT: forma/standings CURENTA cunoscuta per echipa, sursa
-- football-data.org, scrisa EXCLUSIV de Sync Layer
-- (sync/sync_team_form_footballdata.py, prin FootballDataFormAdapter).
-- Oracle Engine NU scrie niciodata aici — doar citeste, prin
-- database.queries.get_team_form_footballdata() (Regula #5 CLAUDE.md).
--
-- Cheie: team_name_canonical — identitate prin NUME NORMALIZAT (ADR-039
-- Principiul 7), NU prin ID-ul numeric de provider football-data.org.
-- Sincronizarea se face PE LIGA (intregul tabel de clasament al unei
-- competitii, o cerere), nu per echipa — vezi
-- oracle_api.get_competition_standings_raw() — dar rezultatul e stocat tot
-- per echipa (aceeasi granularitate ca team_health_snapshot, migrare 017),
-- fiindca forma e o proprietate a echipei in acel moment, nu a ligii.
--
-- Explicit NU include fixtures (descoperire meciuri) — acelea raman
-- R-Sync-7, Universal Match Discovery Layer, cf. corectiei de roadmap
-- ADR-039.
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..017. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS footballdata_team_form_snapshot (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    team_name_canonical    TEXT NOT NULL,

    played                 INTEGER NOT NULL DEFAULT 0,
    goals_for              INTEGER NOT NULL DEFAULT 0,
    goals_against          INTEGER NOT NULL DEFAULT 0,
    form                   TEXT NOT NULL DEFAULT '',

    source_provider        TEXT NOT NULL DEFAULT 'footballdata',
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT footballdata_team_form_snapshot_unique_team
        UNIQUE (team_name_canonical)
);

CREATE INDEX IF NOT EXISTS idx_footballdata_team_form_snapshot_synced_at
    ON footballdata_team_form_snapshot (synced_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..017.
ALTER TABLE footballdata_team_form_snapshot ENABLE ROW LEVEL SECURITY;
