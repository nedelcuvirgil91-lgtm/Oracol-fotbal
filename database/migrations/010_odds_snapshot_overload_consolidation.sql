-- =============================================================================
-- Football Oracle — Migration 010: consolidare upsert_odds_snapshot (PGRST203)
-- =============================================================================
-- INCIDENT: docs/00_GOVERNANCE/INCIDENT_2026-07-17_odds_upsert_overload.md
--
-- Cauza: două funcții `upsert_odds_snapshot` supraîncărcate coexistă în
-- producție:
--   (1) 6 argumente  — din 001_odds_history.sql (fără provenance).
--   (2) 11 argumente — cu provenance (p_provider..p_source_url), ultimii 5
--       parametri DEFAULT — aplicată AD-HOC pe producție (ADR-010), fără
--       migrare versionată în repo.
-- Fiindcă funcția 11-arg are DEFAULT pe ultimii 5 parametri, un apel care
-- trimite exact cei 6 parametri de bază (OddsPersistenceService, calea zilnică)
-- satisface AMBELE funcții -> PostgREST nu poate alege -> PGRST203.
--
-- Notă suplimentară dovedită pe producție: coloanele provider/import_type/
-- import_version din odds_history sunt NOT NULL fără DEFAULT. Funcția 6-arg NU
-- le populează -> chiar și fără ambiguitate, ar viola NOT NULL la orice INSERT
-- nou. Prin urmare funcția 6-arg nu e doar redundantă, ci incompatibilă cu
-- schema actuală: se elimină.
--
-- DECIZIE (Varianta A): o singură funcție canonică = varianta 11-arg cu
-- provenance DEFAULT; se face DROP funcției 6-arg. Ambii apelanți se rezolvă la
-- funcția unică:
--   - calea zilnică (6 params) -> DEFAULT umple provider='the-odds-api',
--     import_type='live_capture', import_version='OddsPersistenceService_v1',
--     imported_at=p_now (satisface NOT NULL).
--   - backfill (11 params) -> trimite toți parametrii explicit.
--
-- Idempotent: DROP ... IF EXISTS + CREATE OR REPLACE; re-rulabil fără eroare.
-- Corpul funcției 11-arg reproduce EXACT definiția din producție (verificat cu
-- pg_get_functiondef, oid 25827), astfel încât repo devine sursă de adevăr.
-- =============================================================================

-- ── (1) Eliminarea supraîncărcării 6-arg (redundantă + incompatibilă NOT NULL) ─
DROP FUNCTION IF EXISTS public.upsert_odds_snapshot(
    text, text, numeric, numeric, numeric, timestamptz
);

-- ── (2) Funcția canonică unică — 11-arg cu provenance (provenance DEFAULT) ─────
CREATE OR REPLACE FUNCTION public.upsert_odds_snapshot(
    p_fixture_id     text,
    p_bookmaker      text,
    p_home           numeric,
    p_draw           numeric,
    p_away           numeric,
    p_now            timestamptz,
    p_provider       text DEFAULT 'the-odds-api',
    p_import_type    text DEFAULT 'live_capture',
    p_import_version text DEFAULT 'OddsPersistenceService_v1',
    p_source_hash    text DEFAULT NULL,
    p_source_url     text DEFAULT NULL
) RETURNS boolean
LANGUAGE plpgsql
AS $function$
DECLARE
    v_rows_affected INT;
BEGIN
    INSERT INTO odds_history (
        fixture_id, bookmaker,
        opening_home, opening_draw, opening_away, opening_fetched_at,
        closing_home, closing_draw, closing_away, closing_fetched_at,
        provider, import_type, import_version, imported_at,
        source_hash, source_url
    ) VALUES (
        p_fixture_id, p_bookmaker,
        p_home, p_draw, p_away, p_now,
        p_home, p_draw, p_away, p_now,
        p_provider, p_import_type, p_import_version, p_now,
        p_source_hash, p_source_url
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
$function$;

-- ── (3) Forțează PostgREST să reîncarce schema (elimină ambiguitatea imediat) ──
NOTIFY pgrst, 'reload schema';
