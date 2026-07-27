-- =============================================================================
-- Football Oracle — Migration 022: odds_api_recent_results (R-Sync-6, ADR-039)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--   - docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md
--
-- Scop STRICT: meciuri TERMINATE recente (Odds API /scores) — sursa
-- CANONICA UNICA din care deriva ATAT forma per echipa CAT SI H2H per
-- pereche de echipe (decizie explicita, proprietar produs, optiunea A din
-- auditul R-Sync-6: un singur fetch/adaptor, nu doua implementari
-- separate ale aceleiasi date brute). Scrisa EXCLUSIV de Sync Layer
-- (sync/sync_odds_recent_results.py, prin OddsApiRecentResultsAdapter).
-- Oracle Engine NU scrie niciodata aici — doar citeste, prin
-- database.queries.get_team_recent_form_oddsapi()/get_h2h_from_odds_recent()
-- (Regula #5 CLAUDE.md).
--
-- Cheie: (home_team_canonical, away_team_canonical, kickoff_date) —
-- reutilizeaza EXACT forma cheii naturale de identitate canonica a unui
-- Meci deja decisa si Frozen (ADR-024/ADR-025: echipe normalizate + data,
-- FARA liga in cheie) — nicio identitate paralela noua (ADR-039
-- Principiul 7).
--
-- NU se confunda cu match_history (sursa PRIMARA, Database-First,
-- ADR-035 D1-D3) — tabela de fata e strict un fallback tertiar (Level 2
-- forma / Level 3 H2H in cascada existenta), populat DOAR din raspunsul
-- Odds API /scores (fereastra scurta, days_back=3, aceeasi limitare ca
-- azi in productie).
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..021. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS odds_api_recent_results (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    home_team_canonical    TEXT NOT NULL,
    away_team_canonical    TEXT NOT NULL,
    kickoff_date           DATE NOT NULL,
    league                 TEXT,

    home_score             INTEGER,
    away_score             INTEGER,

    source_provider        TEXT NOT NULL DEFAULT 'oddsapi',
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT odds_api_recent_results_unique_match
        UNIQUE (home_team_canonical, away_team_canonical, kickoff_date)
);

CREATE INDEX IF NOT EXISTS idx_odds_api_recent_results_synced_at
    ON odds_api_recent_results (synced_at);

-- Index suplimentar — interogarile de forma/H2H filtreaza dupa echipe,
-- nu dupa cheia primara.
CREATE INDEX IF NOT EXISTS idx_odds_api_recent_results_teams
    ON odds_api_recent_results (home_team_canonical, away_team_canonical);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..021.
ALTER TABLE odds_api_recent_results ENABLE ROW LEVEL SECURITY;
