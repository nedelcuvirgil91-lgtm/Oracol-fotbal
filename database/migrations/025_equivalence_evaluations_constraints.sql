-- =============================================================================
-- Football Oracle — Migration 025: equivalence_evaluations integrity + gate
-- view tiebreak determinist (ADR-040)
-- =============================================================================
-- Repară două găsiri reale de la validarea live G2 (ADR-040, secțiunea
-- „Validare G1/G2 (evidență live)"), NEcorectate acolo pe loc, cu aprobare
-- explicită acum:
--
--   1. `current_health` (view-ul migration_gate_status) nu avea tiebreak
--      secundar pentru `evaluated_at` egal — demonstrat prin demonstrația
--      live (3 rânduri inserate în aceeași instrucțiune, timestamp identic).
--      `ORDER BY evaluated_at DESC, id DESC` acum — determinist, unic
--      (id e PK, întotdeauna distinct).
--
--   2. `equivalence_evaluations` accepta silențios date imposibile —
--      demonstrat explicit prin INSERT reușit cu live_count=10,
--      matched_count=300. Trei CHECK constraints adăugate acum: toate
--      câmpurile numerice de cardinalitate >= 0, matched_count nu poate
--      depăși live_count/scheduled_count, equivalence_score (când nu e
--      NULL) rămâne în [0, 1] — consecvent cu formula MIN din
--      equivalence_governance.classify_evaluation() (fiecare componentă a
--      scorului e deja o proporție în [0, 1]).
--
-- Idempotent: verificare `pg_constraint` înainte de fiecare ADD CONSTRAINT
-- (Postgres nu are `ADD CONSTRAINT IF NOT EXISTS` pentru CHECK) +
-- `CREATE OR REPLACE VIEW` (deja idempotent). Aplicat pe tabelă GOALĂ
-- (confirmat explicit, 0 rânduri, la momentul acestei migrări) — fără risc
-- de violare la adăugare. Pur aditiv — nu atinge nicio tabelă/coloană
-- existentă, doar adaugă constrângeri + înlocuiește definiția view-ului.
-- =============================================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'equivalence_evaluations_counts_nonnegative'
    ) THEN
        ALTER TABLE equivalence_evaluations
            ADD CONSTRAINT equivalence_evaluations_counts_nonnegative
            CHECK (
                live_count >= 0 AND scheduled_count >= 0 AND matched_count >= 0
                AND missing_scheduled_count >= 0 AND missing_live_count >= 0
                AND duplicate_key_count >= 0 AND field_difference_count >= 0
                AND provider_id_difference_count >= 0 AND accepted_exception_count >= 0
            );
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'equivalence_evaluations_matched_within_bounds'
    ) THEN
        ALTER TABLE equivalence_evaluations
            ADD CONSTRAINT equivalence_evaluations_matched_within_bounds
            CHECK (matched_count <= live_count AND matched_count <= scheduled_count);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'equivalence_evaluations_score_range'
    ) THEN
        ALTER TABLE equivalence_evaluations
            ADD CONSTRAINT equivalence_evaluations_score_range
            CHECK (equivalence_score IS NULL OR (equivalence_score >= 0 AND equivalence_score <= 1));
    END IF;
END $$;

-- ── View: migration_gate_status (retrimis, DOAR tiebreak-ul adăugat) ───────
CREATE OR REPLACE VIEW migration_gate_status AS
WITH eligible AS (
    SELECT *
    FROM equivalence_evaluations
    WHERE equivalence_state IN ('red', 'yellow', 'green')
),
totals AS (
    SELECT gate_key, entity,
           SUM(matched_count)  AS total_matched_eligible,
           COUNT(*)            AS eligible_row_count,
           MAX(evaluated_at)   AS latest_eligible_at
    FROM eligible
    GROUP BY gate_key, entity
),
provider_totals AS (
    SELECT e.gate_key, e.entity, pb.provider,
           SUM((pb.value->>'matched')::int) AS provider_matched
    FROM eligible e, jsonb_each(e.provider_breakdown) AS pb(provider, value)
    GROUP BY e.gate_key, e.entity, pb.provider
),
min_provider AS (
    SELECT gate_key, entity, MIN(provider_matched) AS min_provider_matched
    FROM provider_totals
    GROUP BY gate_key, entity
),
health_candidates AS (
    SELECT DISTINCT ON (gate_key, entity)
           gate_key, entity,
           equivalence_state AS current_health,
           evaluated_at      AS current_health_at
    FROM equivalence_evaluations
    WHERE equivalence_state <> 'insufficient_data'
    -- [REPARAT, migrarea 025] tiebreak secundar determinist (id, mereu unic)
    -- pentru evaluated_at egal — găsit la demonstrația live G2.
    ORDER BY gate_key, entity, evaluated_at DESC, id DESC
)
SELECT
    COALESCE(t.gate_key, h.gate_key)   AS gate_key,
    COALESCE(t.entity, h.entity)       AS entity,
    COALESCE(t.total_matched_eligible, 0) AS total_matched_eligible,
    COALESCE(t.eligible_row_count, 0)  AS eligible_row_count,
    t.latest_eligible_at,
    mp.min_provider_matched,
    h.current_health,
    h.current_health_at
FROM totals t
FULL OUTER JOIN health_candidates h USING (gate_key, entity)
LEFT JOIN min_provider mp
    ON mp.gate_key = COALESCE(t.gate_key, h.gate_key)
   AND mp.entity   = COALESCE(t.entity, h.entity);

-- ── Forțează PostgREST să reîncarce schema ──────────────────────────────────
NOTIFY pgrst, 'reload schema';
