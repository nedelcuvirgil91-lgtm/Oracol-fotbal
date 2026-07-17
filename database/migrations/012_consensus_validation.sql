-- =============================================================================
-- Football Oracle — Migration 012: Consensus Validation Protocol (ADR-033)
-- =============================================================================
-- Implementează contractul înghețat prin ADR-033:
--   docs/00_GOVERNANCE/ADR-033-consensus-validation-protocol.md
--
-- Două tabele noi, complet independente de shadow_predictions/challengers/
-- model_champions — infrastructură proprie, per decizia explicită din
-- ADR-033 (reutilizează tiparul Challenger capture->evaluate, NU
-- infrastructura lui):
--
--   1. consensus_capture_samples — Faza 1 (capture, serving-time). Perechea
--      de ieșiri brute (ADR-031) per fixture, capturată o singură dată.
--   2. consensus_validation_verdicts — Faza 2 (evaluare T1, periodică).
--      Verdictul unui studiu, imuabil per fereastră.
--
-- Ambele tabele sunt STRICT append-only — nu doar UNIQUE la insert, ci
-- interzicere structurală, necondiționată, a oricărui UPDATE/DELETE (cerință
-- explicită la aprobarea planului de implementare ADR-033, mai strictă decât
-- precedentul challenger_evaluations — 004_challenger_evaluations.sql —, care
-- se bazează doar pe UNIQUE + ON CONFLICT DO NOTHING). Tiparul de trigger
-- urmează stilul deja folosit (odds_history_immutability_guard,
-- model_champions_immutability_guard, automation_runs_guard), simplificat la
-- forma lui cea mai strictă: nicio mutație permisă, niciodată, pe niciun rând.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE OR REPLACE FUNCTION +
-- DROP TRIGGER IF EXISTS. Pur aditiv — nu atinge nicio tabelă existentă.
-- =============================================================================

-- ── consensus_capture_samples — Faza 1 (capture, serving-time) ──────────────
CREATE TABLE IF NOT EXISTS consensus_capture_samples (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fixture_id        TEXT NOT NULL,
    league            TEXT,
    home_team         TEXT,
    away_team         TEXT,
    kickoff_date      DATE,
    raw_predictions   JSONB NOT NULL,   -- lista build_raw_predictions() (ADR-031) — {family, engine, prob_home, prob_draw, prob_away}
    captured_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT consensus_capture_samples_fixture_id_key UNIQUE (fixture_id)
);

CREATE INDEX IF NOT EXISTS idx_consensus_capture_samples_captured_at
    ON consensus_capture_samples (captured_at);

ALTER TABLE consensus_capture_samples ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION consensus_capture_samples_append_only_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'consensus_capture_samples: DELETE interzis in productie. Pentru mentenanta administrativa, dezactivati temporar triggerul (ALTER TABLE consensus_capture_samples DISABLE TRIGGER consensus_capture_samples_guard).';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'consensus_capture_samples: UPDATE interzis — tabela e strict append-only (fixture_id=%). O captura gresita nu se corecteaza, ramane un fapt istoric; studiul T1 o poate exclude la nevoie.', OLD.fixture_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS consensus_capture_samples_guard ON consensus_capture_samples;
CREATE TRIGGER consensus_capture_samples_guard
    BEFORE UPDATE OR DELETE ON consensus_capture_samples
    FOR EACH ROW
    EXECUTE FUNCTION consensus_capture_samples_append_only_guard();

-- ── consensus_validation_verdicts — Faza 2 (evaluare T1, periodică) ─────────
CREATE TABLE IF NOT EXISTS consensus_validation_verdicts (
    id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    metric_name               TEXT NOT NULL,      -- 'agreement_score' | 'divergence_score' | 'prediction_distance'
    is_primary_metric         BOOLEAN NOT NULL,    -- fixat la pornirea studiului, niciodata retroactiv (ADR-033 §3)
    n_samples_evaluated       INTEGER NOT NULL,
    evaluation_window_start   DATE,
    evaluation_window_end     DATE,
    verdict                   TEXT NOT NULL,
    statistical_method        TEXT NOT NULL,
    metrics                   JSONB,               -- statistici calculate (formulele exacte = detaliu de implementare, ADR-033)
    evaluated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT consensus_validation_verdicts_verdict_check
        CHECK (verdict IN ('surface_worthy', 'rejected', 'insufficient_data')),
    -- Invariant load-bearing: aceeasi fereastra de evaluare (aceeasi metrica +
    -- acelasi n_samples_evaluated) nu poate produce decat UN singur verdict,
    -- pentru totdeauna — identic ca forma cu challenger_evaluations_unique_window.
    CONSTRAINT consensus_validation_verdicts_unique_window UNIQUE (metric_name, n_samples_evaluated)
);

CREATE INDEX IF NOT EXISTS idx_consensus_validation_verdicts_history
    ON consensus_validation_verdicts (metric_name, evaluated_at);

ALTER TABLE consensus_validation_verdicts ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION consensus_validation_verdicts_append_only_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'consensus_validation_verdicts: DELETE interzis in productie. Pentru mentenanta administrativa, dezactivati temporar triggerul (ALTER TABLE consensus_validation_verdicts DISABLE TRIGGER consensus_validation_verdicts_guard).';
    END IF;
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'consensus_validation_verdicts: UPDATE interzis — verdictul (metric_name=%, n_samples_evaluated=%) e imuabil odata publicat. O fereastra noua produce un rand nou, distinct.', OLD.metric_name, OLD.n_samples_evaluated;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS consensus_validation_verdicts_guard ON consensus_validation_verdicts;
CREATE TRIGGER consensus_validation_verdicts_guard
    BEFORE UPDATE OR DELETE ON consensus_validation_verdicts
    FOR EACH ROW
    EXECUTE FUNCTION consensus_validation_verdicts_append_only_guard();
