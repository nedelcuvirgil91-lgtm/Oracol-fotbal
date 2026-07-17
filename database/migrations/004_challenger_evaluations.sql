-- =============================================================================
-- Football Oracle — Migration 004: challenger_evaluations (Shadow Evaluation,
-- Pasul 4, Implementation Contract)
-- =============================================================================
-- Implementeaza Pasul 4 din Implementation Contract (Learning Core) — vezi
-- docs/00_GOVERNANCE/ADR-018-challenger-shadow-evaluation.md.
--
-- Scop STRICT: persista verdictul de evaluare al unui Challenger (calculat
-- de shadow_testing.evaluate_experiment(), infrastructura generica deja
-- existenta, neschimbata) ca FAPT ISTORIC IMUABIL. NU implementeaza
-- Promotion, NU scrie in challengers/model_champions, NU declanseaza nicio
-- tranzitie de stare — vezi ADR-018, sectiunea "Ce NU face acest ADR".
--
-- Imuabilitate impusa la nivel de baza de date (nu doar conventie de cod):
-- UNIQUE (training_run_id, n_matches_evaluated) — o rulare ulterioara a
-- job-ului de evaluare, cu ACEEASI fereastra (acelasi n_matches_evaluated),
-- nu poate scrie un rand nou sau modifica unul existent (INSERT cu
-- ignore_duplicates=True => ON CONFLICT DO NOTHING la nivel Postgres).
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001_odds_history.sql / 002_learning_core.sql / 003_challenger.sql.
-- =============================================================================

CREATE TABLE IF NOT EXISTS challenger_evaluations (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    training_run_id          TEXT NOT NULL REFERENCES training_runs (training_run_id),
    algorithm_family         TEXT NOT NULL,
    league_scope             TEXT NOT NULL,
    n_matches_evaluated      INTEGER NOT NULL,
    evaluation_window_start  DATE,
    evaluation_window_end    DATE,
    verdict                  TEXT NOT NULL,
    statistical_method       TEXT NOT NULL,
    brier_baseline           NUMERIC,
    brier_experiment         NUMERIC,
    delta_brier               NUMERIC,
    brier_significant         BOOLEAN,
    logloss_baseline          NUMERIC,
    logloss_experiment        NUMERIC,
    delta_logloss              NUMERIC,
    logloss_significant        BOOLEAN,
    accuracy_baseline           NUMERIC,
    accuracy_experiment         NUMERIC,
    delta_accuracy               NUMERIC,
    accuracy_significant         BOOLEAN,
    evaluated_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT challenger_evaluations_verdict_check
        CHECK (verdict IN ('candidate_for_promotion', 'rejected', 'monitoring', 'insufficient_data')),
    -- Invariant load-bearing: aceeasi fereastra de evaluare (acelasi
    -- training_run_id + acelasi n_matches_evaluated) nu poate produce decat
    -- UN singur verdict, pentru totdeauna. Vezi nota de mai sus.
    CONSTRAINT challenger_evaluations_unique_window UNIQUE (training_run_id, n_matches_evaluated)
);

CREATE INDEX IF NOT EXISTS idx_challenger_evaluations_training_run
    ON challenger_evaluations (training_run_id);

CREATE INDEX IF NOT EXISTS idx_challenger_evaluations_history
    ON challenger_evaluations (algorithm_family, league_scope, evaluated_at);

ALTER TABLE challenger_evaluations ENABLE ROW LEVEL SECURITY;
