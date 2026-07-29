-- =============================================================================
-- Football Oracle — Migration 037: Flashscore Data Completeness Score
-- =============================================================================
-- "TASK APROBAT - Flashscore Foundation Data Layer (M1)", regula 7: scor de
-- completitudine per meci, pe cele 7 tab-uri reale confirmate in POC
-- (Summary/Statistics/Lineups/PlayerStats/Odds/H2H/Standings). Persistat
-- DOAR - NU consumat de Oracle Engine/ML azi (regula 7, explicit).
--
-- Scorul reflecta FETCH-ul (am reusit sa aducem/citim tab-ul), nu succesul
-- extractiei ulterioare - definitie simpla, robusta, verificabila direct
-- din `pages` (dict tab->html), fara ambiguitate de "cat de bine s-a
-- extras". Calculat si scris INDIFERENT de rezultatul validarii (Data
-- Trust Layer) - e o proprietate a colectarii, nu a validarii.
-- =============================================================================

CREATE TABLE IF NOT EXISTS flashscore_data_completeness (
    id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_ref          TEXT NOT NULL,
    match_id           BIGINT REFERENCES match_history(id),
    has_summary        BOOLEAN NOT NULL DEFAULT false,
    has_stats          BOOLEAN NOT NULL DEFAULT false,
    has_lineups        BOOLEAN NOT NULL DEFAULT false,
    has_player_stats   BOOLEAN NOT NULL DEFAULT false,
    has_odds           BOOLEAN NOT NULL DEFAULT false,
    has_h2h            BOOLEAN NOT NULL DEFAULT false,
    has_standings      BOOLEAN NOT NULL DEFAULT false,
    coverage_percent   NUMERIC(5,2) NOT NULL,
    source             TEXT NOT NULL DEFAULT 'flashscore',
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_ref)
);
ALTER TABLE flashscore_data_completeness ENABLE ROW LEVEL SECURITY;
