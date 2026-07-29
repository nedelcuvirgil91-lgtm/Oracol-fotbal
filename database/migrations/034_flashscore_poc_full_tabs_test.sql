-- =============================================================================
-- Football Oracle — Migration 034: Flashscore full-tabs POC (TEST ONLY)
-- =============================================================================
-- "TASK APROBAT - POC LIVE (1 singur meci)" - tabela STRICT de test, pentru
-- persistarea rezultatelor analizei celor 7 tab-uri Flashscore pe un singur
-- meci real (Dinamo Bucuresti 5-1 Univ. Craiova, 25.07.2026).
--
-- NU e o tabela de productie - NU e citita de UDAL/Night Sync/Predictor/ML,
-- NU inlocuieste/atinge match_history/player_match_stats/match_events/
-- odds_fallback_flashscore. Scop exclusiv: dovada persistata a ce s-a gasit
-- in fiecare tab, pentru decizia de schema/scope urmatoare (impreuna cu
-- utilizatorul, cf. cerinta explicita "Nu continua cu M0 pana nu analizam
-- impreuna rezultatul acestui POC").
-- =============================================================================

CREATE TABLE IF NOT EXISTS flashscore_poc_full_tabs_test (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_ref              TEXT NOT NULL,
    tab_name               TEXT NOT NULL,
    http_status            INTEGER,
    content_length         INTEGER,
    distinct_testid_count  INTEGER,
    extracted_summary      JSONB,
    fetched_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_ref, tab_name)
);
ALTER TABLE flashscore_poc_full_tabs_test ENABLE ROW LEVEL SECURITY;
