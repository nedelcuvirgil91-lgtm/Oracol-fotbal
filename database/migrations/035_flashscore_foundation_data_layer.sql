-- =============================================================================
-- Football Oracle — Migration 035: Flashscore Foundation Data Layer
-- =============================================================================
-- "TASK APROBAT - Foundation Data Layer (Flashscore) + Data Trust Layer".
-- Flashscore completeaza informatiile existente (NU inlocuieste providerii
-- API) - vezi docs/00_GOVERNANCE/ADR-044-flashscore-foundation-data-layer.md.
--
-- Principiu de schema: campurile deja acoperite de coloane match_history
-- (migratiile 008/026/032: possession/shots/shots_on_target/corners/fouls/
-- cards/offsides/goalkeeper_saves/referee/stadium/lineup) RAMAN acolo,
-- scrise prin acelasi RPC canonic (upsert_match_canonical, COALESCE) -
-- niciun duplicat de coloana. Doar 2 coloane noi, genuin lipsa (verificate
-- live, confirmate absente): attendance, capacity.
--
-- Pentru "toate statisticile stabile disponibile" (~27 categorii fara
-- coloana dedicata azi - xGOT, blocked shots, duels, tackles, etc.) si
-- pentru statisticile avansate per jucator (shots/xG/passes/touches/
-- dribbles/duels din tab-ul Player Stats) - schema EAV (Entity-Attribute-
-- Value), NU coloane fixe noi per statistica. Motiv explicit (cerinta
-- "Peste un an putem folosi 200 [statistici]... prefer sa colectam o
-- singura data, nu sa modificam continuu colectarea"): o schema EAV
-- absoarbe statistici noi Flashscore FARA migrare noua - schimbarea de
-- schema ar fi exact ce utilizatorul a cerut sa evitam.
--
-- H2H: segmentat corect pe cele 3 categorii reale gasite in tab (verificat
-- live, wcl-headerSection-text): "Head-to-head matches" (h2h_overall),
-- "Last matches: <echipa acasa>" (recent_form_home), "Last matches:
-- <echipa oaspete>" (recent_form_away) - NU amestecate intr-un singur flux.
--
-- Standings: snapshot curent (UNIQUE pe competitie+echipa, actualizat la
-- rerulare, nu istoric acumulat - nicio cerere explicita de istoric de
-- clasament pana acum).
-- =============================================================================

-- 1. match_history — 2 coloane noi, genuin lipsa (verificat live).
ALTER TABLE match_history
  ADD COLUMN IF NOT EXISTS attendance INTEGER,
  ADD COLUMN IF NOT EXISTS capacity INTEGER;


-- 2. match_statistics_extended — EAV, pentru cele ~27 statistici avansate
--    fara coloana dedicata (xGOT, blocked shots, duels won, tackles,
--    interceptions, clearances, crosses, throw ins, etc.).
CREATE TABLE IF NOT EXISTS match_statistics_extended (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id              BIGINT NOT NULL REFERENCES match_history(id),
    stat_key              TEXT NOT NULL,       -- normalizat, snake_case: 'xgot', 'duels_won'
    stat_label            TEXT NOT NULL,       -- eticheta reala Flashscore: 'Duels won'
    home_value_raw        TEXT,
    away_value_raw        TEXT,
    home_value_numeric    NUMERIC,
    away_value_numeric    NUMERIC,
    source                TEXT NOT NULL DEFAULT 'flashscore',
    captured_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, stat_key)
);
ALTER TABLE match_statistics_extended ENABLE ROW LEVEL SECURITY;


-- 3. player_match_stats_extended — EAV per jucator (shots/xG/accurate
--    passes/touches/touches in box/dribbles/duels, din tab-ul Player
--    Stats) - FK catre randul deja existent din player_match_stats
--    (nume/numar/rating/pozitie), nu duplica cheia naturala.
CREATE TABLE IF NOT EXISTS player_match_stats_extended (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    player_match_stats_id  BIGINT NOT NULL REFERENCES player_match_stats(id),
    stat_key               TEXT NOT NULL,
    stat_label             TEXT NOT NULL,
    value_raw              TEXT,
    value_numeric          NUMERIC,
    source                 TEXT NOT NULL DEFAULT 'flashscore',
    captured_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (player_match_stats_id, stat_key)
);
ALTER TABLE player_match_stats_extended ENABLE ROW LEVEL SECURITY;


-- 4. flashscore_match_context — H2H overall + forma recenta per echipa,
--    segmentate explicit (3 categorii reale, verificate live).
CREATE TABLE IF NOT EXISTS flashscore_match_context (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    context_match_id  BIGINT NOT NULL REFERENCES match_history(id),
    category          TEXT NOT NULL CHECK (category IN ('h2h_overall', 'recent_form_home', 'recent_form_away')),
    meeting_order     INTEGER NOT NULL,   -- 0 = cel mai recent
    meeting_date      DATE,
    competition_code  TEXT,
    home_team         TEXT NOT NULL,
    away_team         TEXT NOT NULL,
    home_score        INTEGER,
    away_score        INTEGER,
    source            TEXT NOT NULL DEFAULT 'flashscore',
    captured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (context_match_id, category, meeting_order)
);
ALTER TABLE flashscore_match_context ENABLE ROW LEVEL SECURITY;


-- 5. flashscore_standings_snapshot — snapshot curent per competitie+echipa
--    (actualizat la rerulare, nu istoric acumulat).
CREATE TABLE IF NOT EXISTS flashscore_standings_snapshot (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    competition    TEXT NOT NULL,
    team           TEXT NOT NULL,
    rank           INTEGER,
    played         INTEGER,
    won            INTEGER,
    drawn          INTEGER,
    lost           INTEGER,
    goals_for      INTEGER,
    goals_against  INTEGER,
    goal_diff      INTEGER,
    points         INTEGER,
    source         TEXT NOT NULL DEFAULT 'flashscore',
    captured_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (competition, team)
);
ALTER TABLE flashscore_standings_snapshot ENABLE ROW LEVEL SECURITY;


-- 6. flashscore_raw_extraction — stratul RAW al Data Trust Layer-ului
--    (RAW -> VALIDATED -> CANONICAL, ADR-044). Pastreaza exact ce s-a
--    extras, INAINTE de validare, per meci+tab - dovada de audit completa
--    (North Star #9), independenta de rezultatul validarii/persistarii.
CREATE TABLE IF NOT EXISTS flashscore_raw_extraction (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_ref         TEXT NOT NULL,       -- identitate stabila pre-canonical (ex. URL/mid Flashscore)
    tab_name          TEXT NOT NULL,
    raw_extracted     JSONB NOT NULL,      -- output normalize_*(), inainte de validare
    validation_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (validation_status IN ('pending', 'valid', 'rejected')),
    validation_errors JSONB,
    canonical_written BOOLEAN NOT NULL DEFAULT false,
    source            TEXT NOT NULL DEFAULT 'flashscore',
    captured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_ref, tab_name)
);
ALTER TABLE flashscore_raw_extraction ENABLE ROW LEVEL SECURITY;
