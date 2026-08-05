-- =============================================================================
-- Football Oracle — Migration 008: validation_analysis_reports
-- =============================================================================
-- Implementează analizele periodice cerute de ADR-052 §2.4 (zilnice/
-- săptămânale) — un raport descriptiv per fereastră de timp, comparând
-- Oracle/ML/Blend pe metodologia deja stabilită de proiect (Brier +
-- Log-loss + Accuracy, simultan, North Star #2 — vezi shadow_testing._brier()).
--
-- Scop exclusiv descriptiv/de colectare — acest tabel NU decide, NU
-- optimizează, NU promovează nimic (ADR-052 §2.3/§2.5: Claude analizează și
-- recomandă, decizia rămâne a proprietarului produsului).
--
-- Fiecare motor raportat pe PROPRIUL subset disponibil (n propriu per
-- motor, oracle_n/ml_n/blend_n) — nu se aproximează o comparație pereche
-- unde un motor lipsește (Regula #8, CLAUDE.md).
--
-- Idempotent: poate fi rulat pe o bază de date goală sau re-rulat fără
-- eroare dacă obiectele există deja.
-- =============================================================================

CREATE TABLE IF NOT EXISTS validation_analysis_reports (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cadence             TEXT NOT NULL,              -- 'daily' | 'weekly'
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_matches_total     INTEGER NOT NULL,
    -- Oracle — practic mereu prezent (motorul principal), dar raportat cu
    -- propriul n, nu presupus egal cu n_matches_total.
    oracle_n            INTEGER NOT NULL DEFAULT 0,
    oracle_brier        DOUBLE PRECISION,
    oracle_logloss      DOUBLE PRECISION,
    oracle_accuracy     DOUBLE PRECISION,
    -- ML — prezent doar pe subsetul cu ml_available=true la momentul colectării.
    ml_n                INTEGER NOT NULL DEFAULT 0,
    ml_brier            DOUBLE PRECISION,
    ml_logloss          DOUBLE PRECISION,
    ml_accuracy         DOUBLE PRECISION,
    -- Blend — prezent doar pe subsetul cu blend_available=true.
    blend_n             INTEGER NOT NULL DEFAULT 0,
    blend_brier         DOUBLE PRECISION,
    blend_logloss       DOUBLE PRECISION,
    blend_accuracy      DOUBLE PRECISION,
    CONSTRAINT validation_analysis_reports_cadence_period_end_key UNIQUE (cadence, period_end)
);

-- Upsert pe (cadence, period_end) — o rerulare a aceleiași ferestre
-- actualizează raportul existent, nu creează duplicate.

-- RLS activ, fără policy — accesul se face exclusiv prin cheia service_role
-- (bypass RLS prin design), exact tiparul deja aplicat în 001/006.
ALTER TABLE validation_analysis_reports ENABLE ROW LEVEL SECURITY;
