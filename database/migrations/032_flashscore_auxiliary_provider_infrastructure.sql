-- =============================================================================
-- Football Oracle — Migration 032: Flashscore Auxiliary Provider Infrastructure
-- =============================================================================
-- R-Sync-FLASH-01 (design: docs/06_UDAL/R-SYNC-FLASH-01_DESIGN.md, §3 + §10.6/10.7)
-- + ADR-043 (docs/00_GOVERNANCE/ADR-043-flashscore-odds-fallback.md).
--
-- Stage 1 din implementarea etapizata aprobata explicit de proprietarul
-- produsului ("daca designul este compatibil, incepe implementarea etapizat,
-- in commit-uri mici, cu teste dupa fiecare etapa") — SCHEMA ONLY, nicio
-- schimbare de comportament, nicio scriere reala de date, tos_reviewed
-- ramane False in scraper_registry.py (neatins de aceasta migrare).
--
-- Pur aditiv, idempotent (CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT
-- EXISTS), RLS activ fara policy (acces exclusiv service_role, tiparul
-- 001..031), scriere atomica (ON CONFLICT / FOR UPDATE SKIP LOCKED, niciodata
-- check-then-act) — regulile CLAUDE.md "Regulile bazelor de date".
--
-- 7 obiecte noi:
--   1. match_history: home/away_goalkeeper_saves (singurul camp din
--      capability matrix fara coloana canonica existenta - restul (posesie,
--      sut, cornere, cartonase, arbitru, stadion, lineup XI) au deja casa,
--      migratia 026, owner Sync Layer prin upsert_match_canonical, COALESCE).
--   2. player_match_stats — genuin nou (rating/minute/goluri per jucator,
--      fara casa canonica azi).
--   3. match_events — genuin nou (timeline gol/cartonas/schimbare cu minut).
--   4. upcoming_matches / 5. upcoming_lineups / 6. upcoming_match_features —
--      Pre-Match Sync, domeniu nou, Predictor NU citeste inca din ele
--      (task separat, neinceput aici).
--   7. flashscore_acquisition_queue — coada persistenta de bootstrap/checkpoint
--      (§10.6) — claim atomic FOR UPDATE SKIP LOCKED, status
--      pending/in_progress/done/failed, stale-reclaim dupa 2h.
--   8. odds_fallback_flashscore — ADR-043, tabela SEPARATA de odds_history
--      (Frozen, neatins) — Predictor citeste doar daca odds_history nu are
--      niciun rand pentru acel fixture_id, niciodata amestecate.
-- =============================================================================

-- 1. match_history — singura extindere aditiva de coloana (restul campurilor
--    au deja casa, migratia 026).
ALTER TABLE match_history
  ADD COLUMN IF NOT EXISTS home_goalkeeper_saves integer,
  ADD COLUMN IF NOT EXISTS away_goalkeeper_saves integer;


-- 2. player_match_stats — owner scriere: exclusiv Flashscore Night Sync
--    (singura sursa din capability matrix cu player_ratings=True azi).
CREATE TABLE IF NOT EXISTS player_match_stats (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id         BIGINT NOT NULL REFERENCES match_history(id),
    team             TEXT NOT NULL CHECK (team IN ('home', 'away')),
    player_name      TEXT NOT NULL,
    shirt_number     INTEGER,
    position         TEXT,
    is_starting      BOOLEAN NOT NULL DEFAULT true,
    minutes_played   INTEGER,
    rating           NUMERIC(3,1),
    goals            INTEGER NOT NULL DEFAULT 0,
    assists          INTEGER NOT NULL DEFAULT 0,
    yellow_cards     INTEGER NOT NULL DEFAULT 0,
    red_cards        INTEGER NOT NULL DEFAULT 0,
    source           TEXT NOT NULL DEFAULT 'flashscore',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (match_id, team, player_name)
);
ALTER TABLE player_match_stats ENABLE ROW LEVEL SECURITY;


-- 3. match_events — owner scriere: exclusiv Flashscore Night Sync.
CREATE TABLE IF NOT EXISTS match_events (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id              BIGINT NOT NULL REFERENCES match_history(id),
    team                  TEXT NOT NULL CHECK (team IN ('home', 'away')),
    minute                INTEGER NOT NULL,
    event_type            TEXT NOT NULL CHECK (event_type IN ('goal', 'yellow_card', 'red_card', 'substitution')),
    player_name           TEXT,
    related_player_name   TEXT,
    source                TEXT NOT NULL DEFAULT 'flashscore',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE match_events ENABLE ROW LEVEL SECURITY;


-- 4-6. Pre-Match Sync — Predictor NU citeste inca din aceste tabele (task
--      separat, neinceput). Scriere: exclusiv Flashscore Pre-Match Sync,
--      NICIODATA match_history (meciul inca nu s-a jucat).
CREATE TABLE IF NOT EXISTS upcoming_matches (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    home_team            TEXT NOT NULL,
    away_team            TEXT NOT NULL,
    competition          TEXT NOT NULL,
    kickoff_at           TIMESTAMPTZ NOT NULL,
    standings_snapshot   JSONB,
    recent_form_home     JSONB,
    recent_form_away     JSONB,
    source               TEXT NOT NULL DEFAULT 'flashscore',
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (home_team, away_team, kickoff_at)
);

CREATE TABLE IF NOT EXISTS upcoming_lineups (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    upcoming_match_id    BIGINT NOT NULL REFERENCES upcoming_matches(id),
    team                 TEXT NOT NULL CHECK (team IN ('home', 'away')),
    predicted_lineup     JSONB,
    confidence           TEXT,
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (upcoming_match_id, team)
);

CREATE TABLE IF NOT EXISTS upcoming_match_features (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    upcoming_match_id      BIGINT NOT NULL REFERENCES upcoming_matches(id) UNIQUE,
    h2h_summary            JSONB,
    odds_backup_snapshot   JSONB,
    extra_stats            JSONB,
    fetched_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE upcoming_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE upcoming_lineups ENABLE ROW LEVEL SECURITY;
ALTER TABLE upcoming_match_features ENABLE ROW LEVEL SECURITY;


-- 7. flashscore_acquisition_queue — coada persistenta de bootstrap, §10.6.
--    Claim atomic: UPDATE ... WHERE id = (SELECT id FROM ... WHERE
--    status='pending' ORDER BY bootstrap_order, id LIMIT 1 FOR UPDATE SKIP
--    LOCKED) RETURNING * — nicio fereastra de cursa, pattern standard
--    Postgres pentru cozi (nicio dependinta noua, Redis/coada externa).
CREATE TABLE IF NOT EXISTS flashscore_acquisition_queue (
    id               BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    competition      TEXT NOT NULL,
    bootstrap_order  INTEGER NOT NULL,
    season           TEXT NOT NULL,
    match_url        TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'in_progress', 'done', 'failed')),
    attempt_count    INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    claimed_at       TIMESTAMPTZ,
    completed_at     TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (competition, match_url)
);
CREATE INDEX IF NOT EXISTS flashscore_queue_pending_idx
    ON flashscore_acquisition_queue (bootstrap_order, id) WHERE status = 'pending';
ALTER TABLE flashscore_acquisition_queue ENABLE ROW LEVEL SECURITY;


-- 8. odds_fallback_flashscore — ADR-043 (PROPUS). odds_history (Frozen,
--    ADR-005/006/010) ramane complet neatins — tabela separata, cheie
--    UNIQUE(fixture_id, bookmaker) proprie, fara nicio suprapunere de scriere
--    cu odds_history. Predictor citeste DOAR daca odds_history nu are niciun
--    rand pentru acel fixture_id (regula de citire, database/queries.py,
--    neimplementata inca in acest stage).
CREATE TABLE IF NOT EXISTS odds_fallback_flashscore (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fixture_id    TEXT NOT NULL,
    bookmaker     TEXT NOT NULL,
    home          NUMERIC,
    draw          NUMERIC,
    away          NUMERIC,
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (fixture_id, bookmaker)
);
ALTER TABLE odds_fallback_flashscore ENABLE ROW LEVEL SECURITY;
