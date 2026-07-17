-- =============================================================================
-- Football Oracle — Migration 011: automation_runs & decision_feed (ADR-026)
-- =============================================================================
-- Implementează contractul înghețat prin ADR-026 (Automation Substrate):
--   docs/00_GOVERNANCE/ADR-026-automation-runs-decision-feed.md
--
-- Generalizează tiparul deja dovedit `sync_status` la orice proces autonom
-- (nu doar sincronizarea zilnică) — substratul comun pe care ADR-027…034
-- raportează execuția și, dacă e cazul, propun decizii.
--
-- Două tabele, legate 1:0..1 prin run_id:
--   1. automation_runs   — state machine de EXECUȚIE (T1/T2/T3a/T3b, oricare)
--                           queued -> running -> {completed|failed|skipped}
--   2. decision_feed     — state machine de DECIZIE (doar T3a/T3b)
--                           proposed -> pending -> {approved|rejected|expired|withdrawn}
--                           approved -> {committed|commit_failed|orphaned}
--                           T3b: flagged -> {acknowledged->resolved | expired}
--
-- Tranzițiile interzise (ADR-026 §State Machines) sunt impuse la nivel de
-- trigger, nu doar prin disciplină de cod — exact tiparul deja folosit de
-- odds_history_immutability_guard / model_champions_immutability_guard.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE OR REPLACE FUNCTION +
-- DROP TRIGGER IF EXISTS. Pur aditiv — nu atinge nicio tabelă existentă.
-- =============================================================================

-- ── automation_runs — execuție ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS automation_runs (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    producer        TEXT NOT NULL,          -- identitatea ADR-ului producător, ex. 'ADR-027'
    process_type    TEXT NOT NULL,          -- ex. 'schema_drift_check', 'league_weights_adaptive_training'
    tier            TEXT NOT NULL CHECK (tier IN ('T1', 'T2', 'T3a', 'T3b')),
    target_key      TEXT,                   -- cheie de idempotency, ex. 'xgboost_v1|Premier League'
    status          TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued', 'running', 'completed', 'failed', 'skipped')),
    skip_reason     TEXT,
    error_detail    TEXT,
    summary         JSONB,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_automation_runs_producer_status
    ON automation_runs (producer, status);
CREATE INDEX IF NOT EXISTS idx_automation_runs_target_key
    ON automation_runs (target_key) WHERE target_key IS NOT NULL;

ALTER TABLE automation_runs ENABLE ROW LEVEL SECURITY;

-- ── decision_feed — decizie (T3a/T3b) ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS decision_feed (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              BIGINT NOT NULL REFERENCES automation_runs(id),
    tier                TEXT NOT NULL CHECK (tier IN ('T3a', 'T3b')),
    status              TEXT NOT NULL DEFAULT 'proposed'
                            CHECK (status IN (
                                'proposed', 'pending', 'approved', 'rejected',
                                'committed', 'commit_failed', 'expired', 'withdrawn',
                                'orphaned', 'flagged', 'acknowledged', 'resolved'
                            )),
    evidence            JSONB,
    rollback_plan       TEXT,
    correction_method   TEXT,               -- obligatoriu (la nivel de disciplină de producător,
                                             -- nu impus generic aici) pt. decizii bazate pe test
                                             -- statistic repetat — vezi ADR-026 §Public Interfaces
    commit_error        TEXT,               -- populat la approved->commit_failed
    ttl_at              TIMESTAMPTZ,
    resolved_by         TEXT,
    resolved_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Rollback ca precondiție structurală (Blueprint, principiul #9): o
    -- decizie T3a nu poate exista fără plan de rollback declarat.
    CONSTRAINT decision_feed_t3a_requires_rollback
        CHECK (tier <> 'T3a' OR rollback_plan IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS idx_decision_feed_status ON decision_feed (status);
CREATE INDEX IF NOT EXISTS idx_decision_feed_ttl ON decision_feed (ttl_at) WHERE ttl_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_decision_feed_run_id ON decision_feed (run_id);

ALTER TABLE decision_feed ENABLE ROW LEVEL SECURITY;

-- ── Trigger — tranziții interzise pe automation_runs ────────────────────────
-- (ADR-026 §State Machines: completed->running, failed->completed interzise;
-- DELETE interzis necondiționat, ca la odds_history/model_champions.)
CREATE OR REPLACE FUNCTION automation_runs_transition_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'automation_runs: DELETE interzis in productie. Pentru mentenanta administrativa, dezactivati temporar triggerul (ALTER TABLE automation_runs DISABLE TRIGGER automation_runs_guard).';
    END IF;

    IF OLD.status = 'completed' AND NEW.status = 'running' THEN
        RAISE EXCEPTION 'automation_runs: tranzitie interzisa completed->running (id=%). O reluare creeaza o rulare noua.', OLD.id;
    END IF;
    IF OLD.status = 'failed' AND NEW.status = 'completed' THEN
        RAISE EXCEPTION 'automation_runs: tranzitie interzisa failed->completed (id=%). Un retry creeaza o rulare noua.', OLD.id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS automation_runs_guard ON automation_runs;
CREATE TRIGGER automation_runs_guard
    BEFORE UPDATE OR DELETE ON automation_runs
    FOR EACH ROW
    EXECUTE FUNCTION automation_runs_transition_guard();

-- ── Trigger — tranziții interzise + imuabilitate pe decision_feed ──────────
-- (ADR-026 §State Machines: committed e terminal; rejected->approved si
-- proposed->approved [sarind peste pending] interzise — previne exact
-- auto-aprobarea si reversarea silentioasa.)
CREATE OR REPLACE FUNCTION decision_feed_transition_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'decision_feed: DELETE interzis in productie. Pentru mentenanta administrativa, dezactivati temporar triggerul (ALTER TABLE decision_feed DISABLE TRIGGER decision_feed_guard).';
    END IF;

    IF OLD.status = 'committed' THEN
        RAISE EXCEPTION 'decision_feed: decizia (id=%) este deja committed - imuabila definitiv.', OLD.id;
    END IF;
    IF OLD.status = 'rejected' AND NEW.status = 'approved' THEN
        RAISE EXCEPTION 'decision_feed: tranzitie interzisa rejected->approved (id=%). O schimbare de decizie umana creeaza un ciclu nou de propunere.', OLD.id;
    END IF;
    IF OLD.status = 'proposed' AND NEW.status = 'approved' THEN
        RAISE EXCEPTION 'decision_feed: tranzitie interzisa proposed->approved (id=%). O decizie trebuie sa treaca prin pending inainte de aprobare.', OLD.id;
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS decision_feed_guard ON decision_feed;
CREATE TRIGGER decision_feed_guard
    BEFORE UPDATE OR DELETE ON decision_feed
    FOR EACH ROW
    EXECUTE FUNCTION decision_feed_transition_guard();

-- ── Forțează PostgREST să reîncarce schema ──────────────────────────────────
NOTIFY pgrst, 'reload schema';
