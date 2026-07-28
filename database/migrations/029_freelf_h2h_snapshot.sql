-- =============================================================================
-- Football Oracle — Migration 029: freelf_h2h_snapshot (R-Sync-9, ADR-039)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--
-- Scop STRICT: confruntări directe (H2H) Free Live Football pentru o
-- pereche de echipe — înlocuiește ultimul apel live rămas, eliminabil, din
-- oracle_engine._build_h2h() (`self.api.get_h2h(event_id, home_name,
-- away_name)`) — citire STRICT din Supabase, populată de Sync Layer
-- (sync/sync_h2h_freelf.py, prin FreelfH2hAdapter). Oracle Engine NU scrie
-- niciodată aici.
--
-- Identitate canonica: (home_team_canonical, away_team_canonical) — ORIENTATA
-- (nu simetrica), la fel cum era orientat apelul live vechi (home_name/
-- away_name veneau din perspectiva meciului curent, "acasa" azi). Sync
-- Layer scrie DOAR orientarea reala a fixture-ului sincronizat
-- (scheduled_fixtures.freelf_event_id + home_team_canonical/
-- away_team_canonical) — nu se genereaza si randul inversat.
--
-- `last_5` (JSONB) — pastreaza forma exacta a listei intoarse azi de
-- oracle_api.get_h2h() (["H","D","A",...]) — "no defect, no rewrite"
-- (ADR-038).
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..028. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS freelf_h2h_snapshot (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    home_team_canonical    TEXT NOT NULL,
    away_team_canonical    TEXT NOT NULL,
    freelf_event_id        TEXT NOT NULL,

    meetings               INTEGER NOT NULL DEFAULT 0,
    home_wins              INTEGER NOT NULL DEFAULT 0,
    draws                  INTEGER NOT NULL DEFAULT 0,
    away_wins              INTEGER NOT NULL DEFAULT 0,
    home_goals_avg         NUMERIC NOT NULL DEFAULT 0,
    away_goals_avg         NUMERIC NOT NULL DEFAULT 0,
    last_5                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    h2h_modifier           NUMERIC NOT NULL DEFAULT 0,
    summary                TEXT NOT NULL DEFAULT '',

    source_provider        TEXT NOT NULL DEFAULT 'freelivefootball',
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT freelf_h2h_snapshot_unique_pair
        UNIQUE (home_team_canonical, away_team_canonical)
);

CREATE INDEX IF NOT EXISTS idx_freelf_h2h_snapshot_synced_at
    ON freelf_h2h_snapshot (synced_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..028.
ALTER TABLE freelf_h2h_snapshot ENABLE ROW LEVEL SECURITY;
