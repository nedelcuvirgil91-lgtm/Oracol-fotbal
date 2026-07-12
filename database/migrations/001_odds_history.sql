-- =============================================================================
-- Football Oracle — Migration 001: odds_history
-- =============================================================================
-- Implementează contractul deja Frozen:
--   - docs/03_ENGINE/ODDS_PERSISTENCE_DESIGN.md
--   - docs/00_GOVERNANCE/ADR-005-odds-persistence-clarifications.md
--   - docs/00_GOVERNANCE/ADR-006-odds-persistence-operational-clarifications.md
--
-- Acest fișier reconstruiește exact starea aplicată live în Supabase (nu e
-- o presupunere — verificat coloană cu coloană, tip cu tip, direct din
-- information_schema, înainte de a scrie acest fișier).
--
-- Idempotent: poate fi rulat pe o bază de date goală (creează tabela de la
-- zero) sau re-rulat fără eroare dacă obiectele există deja.
-- =============================================================================

-- ── Schema ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS odds_history (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fixture_id          TEXT NOT NULL,
    bookmaker           TEXT NOT NULL,
    opening_home        NUMERIC,
    opening_draw        NUMERIC,
    opening_away        NUMERIC,
    closing_home        NUMERIC,
    closing_draw        NUMERIC,
    closing_away        NUMERIC,
    opening_fetched_at  TIMESTAMPTZ,
    closing_fetched_at  TIMESTAMPTZ,
    CONSTRAINT odds_history_fixture_id_bookmaker_key UNIQUE (fixture_id, bookmaker)
);

-- RLS activ, fără policy — accesul se face exclusiv prin cheia service_role
-- (sb_secret_...), care are BYPASSRLS prin design (confirmat din documentația
-- oficială Supabase). Niciun alt client (anon/authenticated) nu poate scrie.
ALTER TABLE odds_history ENABLE ROW LEVEL SECURITY;

-- ── Trigger de imutabilitate structurală ─────────────────────────────────────
-- Reguli (§7 din ODDS_PERSISTENCE_DESIGN.md):
--   1. id/fixture_id/bookmaker — niciodată modificabile.
--   2. opening_* (inclusiv opening_fetched_at) — completabile o singură dată
--      (cât sunt NULL); odată setate, imuabile.
--   3. closing_* (inclusiv closing_fetched_at) — RĂMÂN MUTABILE, fără nicio
--      restricție la nivel de trigger — reprezintă mereu "ultima valoare
--      cunoscută" (§6). Eligibilitatea de kickoff (cine decide să nu se mai
--      scrie) aparține exclusiv Service-ului (§9), NU acestui trigger.
--   4. DELETE — respins necondiționat; mentenanță doar prin dezactivare
--      temporară și explicită a trigger-ului.
CREATE OR REPLACE FUNCTION odds_history_immutability_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'odds_history: DELETE interzis in productie. Pentru mentenanta administrativa, dezactivati temporar triggerul (ALTER TABLE odds_history DISABLE TRIGGER odds_history_guard).';
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id THEN
        RAISE EXCEPTION 'odds_history: coloana id este imuabila.';
    END IF;
    IF NEW.fixture_id IS DISTINCT FROM OLD.fixture_id THEN
        RAISE EXCEPTION 'odds_history: coloana fixture_id este imuabila.';
    END IF;
    IF NEW.bookmaker IS DISTINCT FROM OLD.bookmaker THEN
        RAISE EXCEPTION 'odds_history: coloana bookmaker este imuabila.';
    END IF;

    IF OLD.opening_home IS NOT NULL AND NEW.opening_home IS DISTINCT FROM OLD.opening_home THEN
        RAISE EXCEPTION 'odds_history: opening_home este deja setat si imuabil.';
    END IF;
    IF OLD.opening_draw IS NOT NULL AND NEW.opening_draw IS DISTINCT FROM OLD.opening_draw THEN
        RAISE EXCEPTION 'odds_history: opening_draw este deja setat si imuabil.';
    END IF;
    IF OLD.opening_away IS NOT NULL AND NEW.opening_away IS DISTINCT FROM OLD.opening_away THEN
        RAISE EXCEPTION 'odds_history: opening_away este deja setat si imuabil.';
    END IF;
    IF OLD.opening_fetched_at IS NOT NULL AND NEW.opening_fetched_at IS DISTINCT FROM OLD.opening_fetched_at THEN
        RAISE EXCEPTION 'odds_history: opening_fetched_at este deja setat si imuabil.';
    END IF;

    -- closing_* raman mutabile (vezi regula 3 de mai sus) - nicio verificare aici.

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS odds_history_guard ON odds_history;
CREATE TRIGGER odds_history_guard
    BEFORE UPDATE OR DELETE ON odds_history
    FOR EACH ROW
    EXECUTE FUNCTION odds_history_immutability_guard();

-- ── Funcție RPC — persistare atomică (§10 din ODDS_PERSISTENCE_DESIGN.md) ───
-- Un singur INSERT ... ON CONFLICT ... DO UPDATE, fără check-then-act.
-- opening_* nu apare niciodată în clauza SET (exclus prin construcție, nu
-- prin disciplină de cod). Clauza WHERE de după DO UPDATE evită scrieri
-- inutile (§8) — dacă valorile closing_* sunt identice, ROW_COUNT rămâne 0.
CREATE OR REPLACE FUNCTION upsert_odds_snapshot(
    p_fixture_id TEXT,
    p_bookmaker  TEXT,
    p_home       NUMERIC,
    p_draw       NUMERIC,
    p_away       NUMERIC,
    p_now        TIMESTAMPTZ
) RETURNS BOOLEAN AS $$
DECLARE
    v_rows_affected INT;
BEGIN
    INSERT INTO odds_history (
        fixture_id, bookmaker,
        opening_home, opening_draw, opening_away, opening_fetched_at,
        closing_home, closing_draw, closing_away, closing_fetched_at
    ) VALUES (
        p_fixture_id, p_bookmaker,
        p_home, p_draw, p_away, p_now,
        p_home, p_draw, p_away, p_now
    )
    ON CONFLICT (fixture_id, bookmaker) DO UPDATE SET
        closing_home = EXCLUDED.closing_home,
        closing_draw = EXCLUDED.closing_draw,
        closing_away = EXCLUDED.closing_away,
        closing_fetched_at = EXCLUDED.closing_fetched_at
    WHERE odds_history.closing_home IS DISTINCT FROM EXCLUDED.closing_home
       OR odds_history.closing_draw IS DISTINCT FROM EXCLUDED.closing_draw
       OR odds_history.closing_away IS DISTINCT FROM EXCLUDED.closing_away;

    GET DIAGNOSTICS v_rows_affected = ROW_COUNT;
    RETURN v_rows_affected > 0;
END;
$$ LANGUAGE plpgsql;
