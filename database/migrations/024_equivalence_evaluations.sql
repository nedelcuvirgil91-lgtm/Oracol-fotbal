-- =============================================================================
-- Football Oracle — Migration 024: equivalence_evaluations (ADR-040)
-- =============================================================================
-- Implementeaza contractul din:
--   docs/00_GOVERNANCE/ADR-040-automated-migration-gate-and-equivalence-governance.md
--
-- Scop STRICT: infrastructura generica de guvernanta pentru orice "migration
-- gate" viitor, nu doar R-Sync-7b. Un rand = o rulare de comparatie shadow
-- intre calea live si o entitate canonica din Supabase (ex. scheduled_fixtures)
-- pentru un gate_key dat (ex. 'R-Sync-7b'). Istoric IMUABIL, append-only,
-- exact tiparul deja Frozen din champion_health_evaluations (migrarea 015).
--
-- Doua niveluri distincte de prag (ADR-040, Principiul 6), NU unul:
--   Nivel A (validitatea unui rand): equivalence_state='insufficient_data'
--     cand live_count < MIN_LIVE_FOR_EVALUATION (implicit 30, aplicat in
--     Python, nu in schema) -- randul se scrie oricum, dar nu participa la
--     Nivelul B.
--   Nivel B (maturitatea portii): calculat de view-ul migration_gate_status
--     de mai jos -- agregate brute (SUM/MIN pe randuri eligibile). Comparatia
--     efectiva cu pragurile configurabile (model_config,
--     'migration_gate_thresholds') ramane in migration_gate.py (G3), NU aici
--     -- view-ul nu cunoaste pragurile, doar le pregateste ingredientele.
--
-- provider_breakdown (JSONB): {"freelf": {"matched": N, "field_diff": N,
--   "id_diff": N, "missing_scheduled": N}, ...} -- derivat din campul
--   "source" deja folosit de scheduled_fixtures_shadow.evaluate().
--
-- sample_* (JSONB, liste): plafonate la 20 elemente de catre aplicatie
-- (scheduled_fixtures_shadow.MAX_EXAMPLES), nu impus in schema.
--
-- Idempotent, RLS activ, scriere doar prin service_role -- tiparul 001..023.
-- Pur aditiv -- nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS equivalence_evaluations (
    id                             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id                         BIGINT REFERENCES automation_runs (id),

    -- Identitate: ce etapa a produs evaluarea (gate_key) + ce se compara (entity).
    -- Generic prin constructie (ADR-040, Principiul 2) -- NU legat doar de
    -- scheduled_fixtures; orice tabela critica viitoare (team_form,
    -- odds_recent, injuries, ...) foloseste aceeasi tabela, doar cu alt entity.
    gate_key                       TEXT NOT NULL,
    entity                         TEXT NOT NULL,

    window_from                    DATE NOT NULL,
    window_to                      DATE NOT NULL,

    -- Cardinalitate (ADR-040 / §6f audit).
    live_count                     INTEGER NOT NULL,
    scheduled_count                INTEGER NOT NULL,
    matched_count                  INTEGER NOT NULL,
    missing_scheduled_count        INTEGER NOT NULL,
    missing_live_count             INTEGER NOT NULL,
    duplicate_key_count            INTEGER NOT NULL DEFAULT 0,

    -- Diferente.
    field_difference_count         INTEGER NOT NULL,
    provider_id_difference_count   INTEGER NOT NULL,
    accepted_exception_count       INTEGER NOT NULL DEFAULT 0,

    -- Scor (MIN, niciodata medie -- ADR-040 Principiul 3) + stare derivata,
    -- pe cinci valori: insufficient_data (Nivel A, live_count sub prag),
    -- broken (evaluarea shadow a esuat structural), red/yellow/green
    -- (ADR-040 Principiul 4). equivalence_score NULL cand insufficient_data
    -- sau broken -- nu se aproximeaza (Regula #8).
    equivalence_score              NUMERIC,
    equivalence_state              TEXT NOT NULL,

    -- provider_breakdown (Principiul 5) + root_cause_summary (categorie ->
    -- numar aparitii, din tabelul de clasificare euristica, Principiul 5).
    provider_breakdown             JSONB NOT NULL DEFAULT '{}'::jsonb,
    root_cause_summary             JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Dovezi plafonate (max 20 exemple fiecare, impus de aplicatie).
    sample_missing_scheduled       JSONB NOT NULL DEFAULT '[]'::jsonb,
    sample_missing_live            JSONB NOT NULL DEFAULT '[]'::jsonb,
    sample_field_differences       JSONB NOT NULL DEFAULT '[]'::jsonb,
    sample_provider_id_diffs       JSONB NOT NULL DEFAULT '[]'::jsonb,

    evaluated_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT equivalence_evaluations_state_check
        CHECK (equivalence_state IN ('insufficient_data', 'broken', 'red', 'yellow', 'green')),

    -- Imuabilitate prin UNIQUE + ON CONFLICT DO NOTHING la scriere (aplicatie)
    -- -- EXACT precedentul champion_health_evaluations (015). Cheia de
    -- unicitate e (gate_key, entity, window_to, matched_count): o rulare cu
    -- aceeasi fereastra si acelasi numar de meciuri potrivite = no-op garantat.
    CONSTRAINT equivalence_evaluations_unique_window
        UNIQUE (gate_key, entity, window_to, matched_count)
);

CREATE INDEX IF NOT EXISTS idx_equivalence_evaluations_gate_entity_time
    ON equivalence_evaluations (gate_key, entity, evaluated_at);

CREATE INDEX IF NOT EXISTS idx_equivalence_evaluations_gate_entity_state
    ON equivalence_evaluations (gate_key, entity, equivalence_state);

-- RLS activ, fara policy -- accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..023.
ALTER TABLE equivalence_evaluations ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- View: migration_gate_status
-- =============================================================================
-- Agregate BRUTE per (gate_key, entity) -- NU decide singur PASS/FAIL/GRAY.
-- Pragurile (model_config, 'migration_gate_thresholds') si decizia finala
-- raman in migration_gate.py (G3), deliberat -- view-ul pregateste
-- ingredientele, nu cunoaste politica de configurare.
--
--   total_matched_eligible / min_provider_matched -- Nivel B (ADR-040):
--     sumate DOAR peste randuri eligibile (equivalence_state IN
--     ('red','yellow','green')) -- exclude explicit insufficient_data
--     (dovada insuficienta) SI broken (numere nesigure, nu trebuie sa
--     umfle volumul cumulat).
--   current_health -- starea celei mai recente evaluari eligibile pentru
--     sanatate: sare peste insufficient_data, dar NU peste broken (un crash
--     structural E un semnal, mapeaza la RED prin Principiul 4 -- decizia
--     ramane in Python, view-ul doar expune starea bruta).
-- =============================================================================
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
    ORDER BY gate_key, entity, evaluated_at DESC
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
