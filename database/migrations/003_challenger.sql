-- =============================================================================
-- Football Oracle — Migration 003: challengers (Challenger FSM bookkeeping)
-- =============================================================================
-- Implementeaza Pasul 2 din Implementation Contract (Learning Core) — vezi
-- docs/00_GOVERNANCE/ADR-016-challenger-fsm-bookkeeping.md.
--
-- Scop STRICT: introduce starea si tranzitiile unui Challenger (un
-- training_run selectat pentru evaluare in vederea promovarii). NU
-- implementeaza Shadow Evaluation, Promotion, sau citirea Runtime — vezi
-- ADR-016, sectiunea "Ce NU face acest ADR".
--
-- Idempotent: poate fi rulat pe o baza de date goala sau re-rulat fara
-- eroare daca obiectele exista deja — acelasi tipar ca 001_odds_history.sql
-- si 002_learning_core.sql.
--
-- Nu atinge nicio tabela existenta (training_runs, model_champions,
-- match_history, shadow_predictions, experiment_registry) — pur aditiv.
-- =============================================================================

CREATE TABLE IF NOT EXISTS challengers (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    training_run_id     TEXT NOT NULL REFERENCES training_runs (training_run_id),
    algorithm_family    TEXT NOT NULL,
    league_scope        TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'CREATED',
    rejection_reason    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminal_at         TIMESTAMPTZ,
    CONSTRAINT challengers_training_run_id_key UNIQUE (training_run_id),
    CONSTRAINT challengers_state_check
        CHECK (state IN ('CREATED', 'WAITING', 'EVALUATING', 'SUCCEEDED', 'PROMOTED', 'REJECTED')),
    CONSTRAINT challengers_rejection_reason_check
        CHECK (
            (state = 'REJECTED' AND rejection_reason IN ('verdict_negative', 'expired', 'superseded', 'artifact_dead'))
            OR (state <> 'REJECTED' AND rejection_reason IS NULL)
        )
);

-- Invariant load-bearing: cel mult UN Challenger activ (stare non-terminala)
-- per (algorithm_family, league_scope) — impus la nivel de baza de date,
-- identic ca tipar cu idx_model_champions_active_unique din 002 (ADR-015).
-- "Activ" = state NOT IN ('PROMOTED', 'REJECTED').
CREATE UNIQUE INDEX IF NOT EXISTS idx_challengers_active_unique
    ON challengers (algorithm_family, league_scope)
    WHERE state NOT IN ('PROMOTED', 'REJECTED');

CREATE INDEX IF NOT EXISTS idx_challengers_training_run
    ON challengers (training_run_id);

CREATE INDEX IF NOT EXISTS idx_challengers_history
    ON challengers (algorithm_family, league_scope, created_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001/002.
ALTER TABLE challengers ENABLE ROW LEVEL SECURITY;
