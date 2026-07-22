-- =============================================================================
-- Football Oracle — Migration 017: team_health_snapshot (R-Sync-2, ADR-039)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--   - docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md §5
--
-- Scop STRICT: starea CURENTA cunoscuta de injuries+coaches per echipa,
-- scrisa EXCLUSIV de Sync Layer (sync/sync_team_health.py, prin
-- ApiFootballHealthAdapter). Oracle Engine NU scrie niciodata aici — doar
-- citeste, prin database.queries.get_team_health() (Regula #5 CLAUDE.md).
--
-- Cheie: team_name_canonical — identitate prin NUME NORMALIZAT (ADR-039
-- Principiul 7), NU prin ID-ul numeric de provider API-Football. O echipa
-- nu e scoped pe liga (isi pastreaza numele canonic indiferent de
-- competitie, confirmat deja de TEAM_ALIASES/TEAM_IDENTITY_AUDIT.md) —
-- injuries+coaches sunt o proprietate a echipei, nu a perechii (echipa,liga).
--
-- injuries/coaches sunt JSONB — liste de inregistrari normalizate
-- (Injury/CoachInfo din football_providers.py), consistent cu precedentul
-- deja stabilit (coverage_raw JSONB, migrare 016) pentru date structurate,
-- variabile ca forma, care nu se interogheaza pe sub-camp in SQL.
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..016. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS team_health_snapshot (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    team_name_canonical    TEXT NOT NULL,

    injuries               JSONB NOT NULL DEFAULT '[]'::jsonb,
    coaches                JSONB NOT NULL DEFAULT '[]'::jsonb,

    source_provider        TEXT NOT NULL DEFAULT 'apifootball',
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT team_health_snapshot_unique_team
        UNIQUE (team_name_canonical)
);

CREATE INDEX IF NOT EXISTS idx_team_health_snapshot_synced_at
    ON team_health_snapshot (synced_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..016.
ALTER TABLE team_health_snapshot ENABLE ROW LEVEL SECURITY;
