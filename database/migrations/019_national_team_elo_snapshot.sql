-- =============================================================================
-- Football Oracle — Migration 019: national_team_elo_snapshot (R-Sync-4, ADR-039)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--   - docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md §5/§6c
--
-- Scop STRICT: ELO CURENT cunoscut per echipa NATIONALA, sursa
-- eloratings.net (scrape HTML) — NU TheSportsDB, corectie de clasificare
-- explicita, vezi audit §6c. Scris EXCLUSIV de Sync Layer
-- (sync/sync_national_team_elo.py, prin EloRatingsAdapter). Oracle Engine
-- NU scrie niciodata aici — doar citeste, prin
-- database.queries.get_national_team_elo() (Regula #5 CLAUDE.md).
--
-- Cheie: team_name_canonical — identitate prin NUME NORMALIZAT (ADR-039
-- Principiul 7), NU prin ID numeric de provider (eloratings.net nu are
-- ID-uri stabile de echipa, doar nume in tabelul scrape-uit).
--
-- Nu se confunda cu ELO-ul de club (match_history.home_elo_after/
-- away_elo_after, Canonical Live ELO Snapshot, ADR-023/ADR-035 D2,
-- migrare 006) — acela ramane sursa primara, neatinsa, pentru orice
-- echipa cu meciuri de club sincronizate. Tabela de fata e strict
-- fallback-ul pentru echipele NATIONALE (fara meciuri de club in
-- match_history) — acelasi rol pe care oracle_api.get_elo_rating() il
-- avea live, inainte de aceasta migrare.
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..018. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS national_team_elo_snapshot (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    team_name_canonical    TEXT NOT NULL,
    elo_rating             INTEGER NOT NULL,

    source_provider        TEXT NOT NULL DEFAULT 'eloratings',
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT national_team_elo_snapshot_unique_team
        UNIQUE (team_name_canonical)
);

CREATE INDEX IF NOT EXISTS idx_national_team_elo_snapshot_synced_at
    ON national_team_elo_snapshot (synced_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..018.
ALTER TABLE national_team_elo_snapshot ENABLE ROW LEVEL SECURITY;
