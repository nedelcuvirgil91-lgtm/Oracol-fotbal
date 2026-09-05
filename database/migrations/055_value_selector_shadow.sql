-- =============================================================================
-- Football Oracle — Migration 055: Value Selector Shadow (ADR-071, faza F2)
-- =============================================================================
-- Tabela de observare a selectorului de radar. NU schimba nimic in productie:
-- nicio predictie, nicio cota, niciun rand din match_history nu e atins.
-- Utilizatorul nu vede nicio diferenta cat timp aceasta tabela se umple.
--
-- Scop: dupa 8+ saptamani sa se poata reconstrui EXACT de ce fiecare candidat a
-- fost Top, Longshot sau Respins — poarta cu poarta, motiv cu motiv, pentru
-- fiecare dintre cele 13 profile de politica rulate in paralel.
--
-- Reguli respectate (CLAUDE.md, "Regulile bazelor de date"):
--   - idempotenta la creare (CREATE TABLE IF NOT EXISTS);
--   - RLS activ, fara policy publica -> acces exclusiv service_role;
--   - scriere atomica prin INSERT ... ON CONFLICT, niciodata check-then-act;
--   - niciun owner de scriere existent nu e atins (tabela e complet noua).
--
-- Cheia naturala e (run_id, policy_id, fixture_id, selection_code): o rulare
-- evalueaza fiecare selectie o singura data per politica. Reluarea aceleiasi
-- rulari e idempotenta.
--
-- IMPORTANT — append-only prin conventie, nu prin trigger: spre deosebire de
-- consensus_capture_samples, aici o reluare a aceleiasi rulari TREBUIE sa poata
-- rescrie randul (ON CONFLICT DO UPDATE), pentru ca o rulare intrerupta la
-- jumatate sa poata fi reluata fara sa lase date partiale. Istoricul ramane
-- separat pe `run_id` — nicio rulare nu suprascrie alta rulare.
-- =============================================================================

CREATE TABLE IF NOT EXISTS value_selector_shadow (
    id                    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- identitatea rularii si a politicii evaluate
    run_id                TEXT        NOT NULL,
    evaluated_at          TIMESTAMPTZ NOT NULL,
    policy_id             TEXT        NOT NULL,
    policy_profile        TEXT        NOT NULL,
    policy_family         TEXT,        -- gruparea analitica; profilele semantic
                                       -- identice impart aceeasi familie si NU
                                       -- se numara ca experimente independente
    policy_fingerprint    TEXT,        -- amprenta pragurilor, fara numele profilului
    ranker_id             TEXT        NOT NULL,
    shrinkage_w           NUMERIC     NOT NULL,

    -- identitatea meciului si a selectiei
    fixture_id            TEXT        NOT NULL,
    match_label           TEXT,
    league                TEXT,
    kickoff_utc           TIMESTAMPTZ,
    market                TEXT        NOT NULL DEFAULT '1X2',
    selection_code        TEXT        NOT NULL,

    -- intrarile selectorului (neatinse, exact cum au fost citite)
    model_probability     NUMERIC     NOT NULL,
    fair_probability      NUMERIC     NOT NULL,
    bk_odds               NUMERIC     NOT NULL,
    bookmaker             TEXT,

    -- derivatele selectorului
    absolute_edge_pp      NUMERIC     NOT NULL,
    relative_edge_pct     NUMERIC     NOT NULL,
    p_shr                 NUMERIC     NOT NULL,
    ev_raw                NUMERIC     NOT NULL,
    ev_shr                NUMERIC     NOT NULL,
    rank_in_match         INTEGER     NOT NULL,
    actionability_score   NUMERIC     NOT NULL,
    rank_in_day           INTEGER,

    -- decizia, complet reconstruibila
    category              TEXT        NOT NULL CHECK (category IN ('top', 'longshot', 'rejected')),
    selected_top          BOOLEAN     NOT NULL DEFAULT false,
    selected_longshot     BOOLEAN     NOT NULL DEFAULT false,
    rejected              BOOLEAN     NOT NULL DEFAULT false,
    gate_verdicts         JSONB       NOT NULL,   -- {gate_id: pass|fail|unknown|not_applicable}
    gate_details          JSONB,                  -- {gate_id: explicatie numerica}
    rejection_reasons     JSONB       NOT NULL DEFAULT '[]'::jsonb,

    -- context de calitate si prospetime
    data_quality          TEXT,
    matches_analysed      INTEGER,
    prediction_freshness_s NUMERIC,
    odds_freshness_s      NUMERIC,     -- NULL = necunoscut in V1, niciodata aproximat
    seconds_to_kickoff    NUMERIC,

    -- garda de scurgere temporala: criteriu hard la evaluarea F3
    leakage_suspect       BOOLEAN,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (run_id, policy_id, fixture_id, selection_code)
);

ALTER TABLE value_selector_shadow ENABLE ROW LEVEL SECURITY;

-- Interogarile de evaluare F3 sunt, in ordine: per politica + interval de timp
-- (comparatia intre profile), si per meci (reconstructia unei decizii).
CREATE INDEX IF NOT EXISTS value_selector_shadow_policy_kickoff_idx
    ON value_selector_shadow (policy_id, kickoff_utc);
CREATE INDEX IF NOT EXISTS value_selector_shadow_fixture_idx
    ON value_selector_shadow (fixture_id, selection_code);
CREATE INDEX IF NOT EXISTS value_selector_shadow_top_idx
    ON value_selector_shadow (policy_id, kickoff_utc) WHERE selected_top;
