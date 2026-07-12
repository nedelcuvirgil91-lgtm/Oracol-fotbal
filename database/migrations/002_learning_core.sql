-- =============================================================================
-- Football Oracle — Migration 002: learning_core (training_runs, model_champions)
-- =============================================================================
-- Implementează schema descrisă în:
--   - docs/04_LEARNING_CORE/LEARNING_CORE_ARCHITECTURE.md §3.2 (Training Runner),
--     §3.3 (Champion Registry), §5 (responsabilitatea fiecărei tabele)
--
-- ATENȚIE — NU APLICATĂ ÎNCĂ ÎN SUPABASE. Acest fișier e artefact de cod,
-- versionat în GitHub pentru review, conform deciziei explicite a
-- proprietarului produsului. Nu se rulează `apply_migration`/`execute_sql`
-- până la aprobare separată — vezi CLAUDE.md, "Regulile bazelor de date"
-- ("Proiectul Supabase conectat e producție reală, nu sandbox").
--
-- Idempotent: poate fi rulat pe o bază de date goală (creează tabelele de la
-- zero) sau re-rulat fără eroare dacă obiectele există deja — exact tiparul
-- din 001_odds_history.sql.
--
-- Nu atinge nicio tabelă existentă (match_history, model_weights,
-- shadow_predictions, experiment_registry, odds_history) — pur aditiv.
-- =============================================================================

-- ── training_runs ────────────────────────────────────────────────────────────
-- Istoric complet, per rulare de antrenare — cine, când, cu ce date, ce
-- metrici. Populată de viitorul Training Runner (neimplementat încă în acest
-- pas — vezi LEARNING_CORE_ARCHITECTURE.md §5: "Nu ține predicții per meci",
-- acelea rămân în shadow_predictions, deja existentă).
CREATE TABLE IF NOT EXISTS training_runs (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    training_run_id       TEXT NOT NULL,
    algorithm_name        TEXT NOT NULL,
    algorithm_version     TEXT NOT NULL,
    league_scope          TEXT NOT NULL,
    status                TEXT NOT NULL,
    samples_used          INTEGER NOT NULL DEFAULT 0,
    walk_forward_metrics  JSONB NOT NULL DEFAULT '{}'::jsonb,
    message               TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT training_runs_training_run_id_key UNIQUE (training_run_id),
    CONSTRAINT training_runs_status_check
        CHECK (status IN ('trained', 'insufficient_data', 'error', 'not_applicable', 'unavailable'))
);

CREATE INDEX IF NOT EXISTS idx_training_runs_algorithm
    ON training_runs (algorithm_name, algorithm_version, league_scope);

CREATE INDEX IF NOT EXISTS idx_training_runs_created_at
    ON training_runs (created_at);

-- RLS activ, fără policy — accesul se face exclusiv prin cheia service_role
-- (sb_secret_...), care are BYPASSRLS prin design — exact tiparul deja
-- aplicat în 001_odds_history.sql. Niciun alt client (anon/authenticated)
-- nu poate citi sau scrie.
ALTER TABLE training_runs ENABLE ROW LEVEL SECURITY;


-- ── model_champions ──────────────────────────────────────────────────────────
-- Pointer curent + istoric al campionilor, per (algorithm_family, league_scope)
-- — vezi LEARNING_CORE_ARCHITECTURE.md §3.3. Design append-only: fiecare
-- promovare e un rând nou, imuabil ca fapt istoric; "campionul curent" e
-- rândul cu superseded_at IS NULL. Populată de viitorul Champion Manager
-- (neimplementat încă în acest pas).
CREATE TABLE IF NOT EXISTS model_champions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    algorithm_family    TEXT NOT NULL,
    algorithm_version   TEXT NOT NULL,
    league_scope        TEXT NOT NULL,
    training_run_id     TEXT NOT NULL REFERENCES training_runs (training_run_id),
    promoted_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    promoted_by         TEXT NOT NULL,
    superseded_at       TIMESTAMPTZ,
    superseded_by       TEXT REFERENCES training_runs (training_run_id)
);

-- Invariant load-bearing: cel mult UN campion activ per (algorithm_family,
-- league_scope) — impus la nivel de bază de date, nu doar prin disciplină de
-- cod. "Activ" = superseded_at IS NULL. Aplicarea acestei reguli prin index
-- parțial unic înseamnă că orice bug viitor în Promotion Engine (neimplementat
-- încă) care ar încerca să promoveze doi campioni simultan pentru aceeași
-- combinație eșuează la INSERT, nu produce o stare ambiguă silențioasă.
CREATE UNIQUE INDEX IF NOT EXISTS idx_model_champions_active_unique
    ON model_champions (algorithm_family, league_scope)
    WHERE superseded_at IS NULL;

-- Interogare istorică completă (toți campionii, activi sau nu), ordonată
-- cronologic — separată de indexul de mai sus, care acoperă DOAR rândurile active.
CREATE INDEX IF NOT EXISTS idx_model_champions_history
    ON model_champions (algorithm_family, league_scope, promoted_at);

ALTER TABLE model_champions ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- Notă de proiectare — de ce NU există (încă) trigger de imutabilitate aici
-- =============================================================================
-- 001_odds_history.sql are un trigger dedicat (odds_history_immutability_guard)
-- pentru că §7 din ODDS_PERSISTENCE_DESIGN.md cerea explicit acea garanție,
-- cu istoric de dispută arhitecturală documentat (ADR-005/006). Pentru
-- training_runs/model_champions, la acest pas (doar infrastructură de bază de
-- date, fără Training Runner/Promotion Engine/Champion Manager încă
-- implementate), un trigger echivalent ar fi o garanție fără niciun scriitor
-- real de verificat împotriva ei — exact genul de lucru premature semnalat ca
-- „nu introduce funcționalități speculative". Indexul unic parțial de mai sus
-- acoperă deja invariantul cel mai important (un singur campion activ).
-- Revizuit ca decizie separată, explicită, când Promotion Engine/Rollback
-- Engine chiar scriu în aceste tabele.
-- =============================================================================
