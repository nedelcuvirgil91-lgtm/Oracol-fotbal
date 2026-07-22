-- =============================================================================
-- Football Oracle — Migration 015: champion_health_evaluations (R2, Champion Guardian)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-037-learning-core-rollback-and-champion-guardian.md (§7/D5)
--   - docs/04_LEARNING_CORE/CHAMPION_GUARDIAN_IMPLEMENTATION.md (§3, §14 R2)
--
-- Scop STRICT: istoric IMUABIL, per fereastra, al sanatatii campionului ACTIV —
-- metrici live + stare de sanatate + baseline_source. Scris EXCLUSIV de
-- Champion Guardian (learning_core/champion_guardian.py, R2.4). Substrat pentru
-- regula "ferestre consecutive" si pentru un dashboard viitor (Monitoring Layer).
--
-- Champion Guardian e READ-ONLY fata de model_champions — aceasta tabela e
-- SINGURA lui scriere. NU promoveaza, NU face rollback, NU scrie automation_runs
-- (propunerea T3a e R3). Doar produce evaluari si recomandari (starea de sanatate).
--
-- Imuabilitate impusa prin UNIQUE(training_run_id, n_matches_evaluated) +
-- scriere append-only cu ON CONFLICT DO NOTHING (o rulare cu aceeasi fereastra =
-- no-op garantat) — EXACT precedentul challenger_evaluations (004), FARA trigger
-- nou (decizie explicita R2: se urmeaza tiparul 004, nu odds_history/model_champions).
-- Cheia de unicitate e n_matches_evaluated (dimensiunea cumulativa a ferestrei,
-- monotona), NU window_end: identitatea unei evaluari e cate meciuri au intrat in
-- scor, nu o proprietate incidentala (ultima zi). Doua evaluari cu acelasi
-- window_end (mai multe meciuri in aceeasi zi) sunt evenimente DIFERITE si nu
-- trebuie colapsate. window_end ramane coloana informativa (afisare/istoric).
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..005. Nu atinge nicio tabela existenta (doar FK catre training_runs).
-- =============================================================================

CREATE TABLE IF NOT EXISTS champion_health_evaluations (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    training_run_id          TEXT NOT NULL REFERENCES training_runs (training_run_id),
    algorithm_family         TEXT NOT NULL,
    league_scope             TEXT NOT NULL,

    -- Fereastra: window_end = kickoff_date-ul celui mai recent meci scorabil
    -- inclus; n_matches_evaluated = cate predicatii servite rezolvate au intrat
    -- in scor. O fereastra NOUA (mai multe meciuri acumulate) = un rand NOU.
    window_end               DATE NOT NULL,
    n_matches_evaluated      INTEGER NOT NULL,

    -- Starea derivata (punct unic de decizie in Guardian). insufficient_data e
    -- explicit, distinct de healthy: "nu exista suficiente dovezi", nu "sanatos".
    health_state             TEXT NOT NULL,

    -- Pe ce baza a fost calculata sanatatea (audit): promotion_evaluation
    -- (baseline live din challenger_evaluations), trend_only (fara baseline —
    -- primul campion), manual_override.
    baseline_source          TEXT NOT NULL,

    -- Metrici live pe fereastra (pot fi NULL: esantion prea mic, sau esec
    -- structural in care nu s-a putut scora).
    brier_live               NUMERIC,
    logloss_live             NUMERIC,
    accuracy_live            NUMERIC,

    -- Baseline-ul de promovare (NULL cand baseline_source = trend_only).
    brier_baseline           NUMERIC,
    logloss_baseline         NUMERIC,
    accuracy_baseline        NUMERIC,

    -- Dimensiunea informationala (dispersia probabilitatilor servite).
    stability_indicator      NUMERIC,

    -- Care dimensiune a declansat (audit + regula ferestrelor consecutive).
    baseline_deviation_flag  BOOLEAN,
    trend_flag               BOOLEAN,
    structural_flag          BOOLEAN,
    stability_flag           BOOLEAN,

    evaluated_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT champion_health_state_check
        CHECK (health_state IN ('insufficient_data', 'healthy', 'watch', 'degrading', 'critical')),
    CONSTRAINT champion_health_baseline_source_check
        CHECK (baseline_source IN ('promotion_evaluation', 'trend_only', 'manual_override')),

    -- Invariant load-bearing: aceeasi fereastra (acelasi training_run_id +
    -- acelasi n_matches_evaluated) nu poate produce decat UN singur rand, pentru
    -- totdeauna — imuabilitate prin UNIQUE + ON CONFLICT DO NOTHING la scriere.
    -- Cheia e n_matches_evaluated (identitatea ferestrei = cate meciuri s-au
    -- acumulat), nu window_end (proprietate incidentala care poate colida pe
    -- zilele cu mai multe meciuri). Precedent: challenger_evaluations (004).
    CONSTRAINT champion_health_unique_window UNIQUE (training_run_id, n_matches_evaluated)
);

CREATE INDEX IF NOT EXISTS idx_champion_health_training_run
    ON champion_health_evaluations (training_run_id);

CREATE INDEX IF NOT EXISTS idx_champion_health_history
    ON champion_health_evaluations (algorithm_family, league_scope, evaluated_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..005.
ALTER TABLE champion_health_evaluations ENABLE ROW LEVEL SECURITY;
