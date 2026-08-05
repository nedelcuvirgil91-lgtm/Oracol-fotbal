-- =============================================================================
-- Football Oracle — Migration 006: engine_comparison_snapshots
-- =============================================================================
-- Implementează infrastructura de colectare cerută de ADR-052 (Validation &
-- Continuous Evaluation Framework, derivat din ADR-051) — un instantaneu per
-- meci al ieșirilor disponibile ale celor trei motoare (Oracle/ML/Blend),
-- pentru analize periodice (zilnice/săptămânale/lunare) ulterioare.
--
-- Scop exclusiv de colectare/organizare — acest tabel NU decide, NU
-- optimizează, NU promovează nimic (ADR-052 §2.3).
--
-- Rezultatul real al meciului NU se scrie aici — rămâne exclusiv în
-- match_history.actual_result (Canonical Feature Ownership, ADR-036/D3.5,
-- sync_results.py e singurul scriitor). Orice analiză care are nevoie de
-- rezultatul real face JOIN pe fixture_id, nu duplică scrierea.
--
-- Idempotent: poate fi rulat pe o bază de date goală sau re-rulat fără
-- eroare dacă obiectele există deja.
-- =============================================================================

CREATE TABLE IF NOT EXISTS engine_comparison_snapshots (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fixture_id          TEXT NOT NULL,
    league              TEXT,
    kickoff_date        TEXT,
    captured_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Oracle — întotdeauna prezent (motorul principal, servește mereu).
    oracle_prob_home    DOUBLE PRECISION NOT NULL,
    oracle_prob_draw    DOUBLE PRECISION NOT NULL,
    oracle_prob_away    DOUBLE PRECISION NOT NULL,
    -- ML — prezent doar dacă ml_engine_display_enabled=True ȘI modelul a
    -- produs o predicție validă pentru acest meci (vezi
    -- oracle_engine._get_ml_engine_prediction(), Phase 1/ADR-051).
    ml_available        BOOLEAN NOT NULL DEFAULT false,
    ml_prob_home        DOUBLE PRECISION,
    ml_prob_draw        DOUBLE PRECISION,
    ml_prob_away        DOUBLE PRECISION,
    -- Blend — prezent doar dacă blend_engine_display_enabled=True (vezi
    -- oracle_engine._get_blend_engine_prediction()).
    blend_available     BOOLEAN NOT NULL DEFAULT false,
    blend_prob_home     DOUBLE PRECISION,
    blend_prob_draw     DOUBLE PRECISION,
    blend_prob_away     DOUBLE PRECISION,
    CONSTRAINT engine_comparison_snapshots_fixture_id_key UNIQUE (fixture_id)
);

-- Upsert pe fixture_id (constraint de mai sus) — o reanalizare a aceluiași
-- meci actualizează rândul existent, nu creează duplicate. Instantaneu
-- canonic per meci, nu jurnal append-only.

-- RLS activ, fără policy — accesul se face exclusiv prin cheia service_role
-- (bypass RLS prin design), exact tiparul deja aplicat în 001_odds_history.sql.
ALTER TABLE engine_comparison_snapshots ENABLE ROW LEVEL SECURITY;
