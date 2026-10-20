-- =============================================================================
-- Football Oracle — ȘABLON pentru orice TABELĂ NOUĂ (nu e o migrare)
-- =============================================================================
-- Fișierul ăsta NU se rulează. Se COPIAZĂ. Prefixul `_` îl ține în afara
-- numerotării, iar garda `tests/test_migration_grants.py` îl verifică la
-- fiecare rulare de teste, deci nu poate rămâne în urmă tăcut.
--
-- ── DE CE EXISTĂ, cu dată ────────────────────────────────────────────────────
-- Supabase oprește pe **2026-10-30** acordarea AUTOMATĂ de acces Data API
-- pentru tabelele noi din schema `public` (anunț primit prin email pe 20 oct).
-- Tabelele existente NU sunt afectate — își păstrează grant-urile.
--
-- Măsurat pe 20 oct, înainte de a scrie șablonul: ZERO din cele 60 de migrări
-- existente conțineau vreun `GRANT`. Toate s-au bazat pe acordarea automată,
-- inclusiv 057, creată cu o zi înainte. Pe producție, fiecare tabelă — de la
-- `odds_history` la `flashscore_team_identity` — are deja privilegii complete
-- pentru `anon`, `authenticated` și `service_role`, acordate de Supabase, nu
-- de noi.
--
-- ── CE SE RUPE FĂRĂ ASTA, și de ce n-am prinde-o devreme ─────────────────────
-- Aplicația vorbește cu baza prin PostgREST (`supabase.create_client`), adică
-- exact „Data API"-ul din anunț, autentificată ca `service_role`
-- (`SUPABASE_SECRET_KEY`). Anunțul cere `GRANT` explicit INCLUSIV pentru
-- `service_role`.
--
-- Deci o tabelă creată după 30 octombrie fără `GRANT` nu eșuează la CREARE —
-- eșuează la prima SCRIERE, din `night_sync`, cu `permission denied`. Nu avem
-- mediu de staging, deci nu există unde să se vadă mai devreme.
--
-- ── RLS NU E UN GRANT ────────────────────────────────────────────────────────
-- Sunt DOUĂ straturi, și le-am scris mereu doar pe al doilea:
--   GRANT    → rolul are voie să atingă tabela (stratul care dispare)
--   POLICY   → ce RÂNDURI vede rolul care deja are voie
-- Migrările noastre fac `ENABLE ROW LEVEL SECURITY` + `CREATE POLICY ... TO
-- service_role` și se opresc acolo. Corect, dar incomplet după 30 octombrie.
--
-- ── DE CE `anon` ȘI `authenticated` LIPSESC DIN BLOCUL DE MAI JOS ────────────
-- Deliberat, nu din omisiune. Niciun flux din proiect nu citește prin ele:
-- `supabase_client.py` folosește exclusiv cheia secretă (`service_role`).
-- Acordarea automată le dădea până acum `SELECT, INSERT, UPDATE, DELETE,
-- TRUNCATE` pe TOATE tabelele, inclusiv `match_history` — singurul lucru care
-- oprea un apelant anonim era RLS. Schimbarea Supabase ne lasă, în sfârșit, să
-- acordăm îngust în loc să moștenim „tot pentru toți".
--
-- Dacă o tabelă nouă chiar are nevoie de `anon` (azi: niciuna), se adaugă
-- explicit, cu motivul scris pe loc — nu se copiază tăcut de aici.
--
-- ── ORDINEA, și de ce contează ───────────────────────────────────────────────
-- RLS se activează ÎNAINTE de GRANT. Invers ar exista o fereastră, fie ea de
-- milisecunde într-o tranzacție, în care tabela e accesibilă fără plasă.
-- =============================================================================

-- ── 1. Schema ────────────────────────────────────────────────────────────────
-- Idempotent la creare (regula proiectului). Precedent de stil complet:
-- `001_odds_history.sql`.
CREATE TABLE IF NOT EXISTS numele_tabelei (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Orice marcaj temporal scris prin `upsert` TREBUIE pus explicit în
    -- payload, nu lăsat pe `DEFAULT now()`: acela se aplică doar pe ramura
    -- INSERT, nu pe `DO UPDATE`. Șase instanțe reparate în proiect pe 26
    -- august; garda e `tests/test_upsert_timestamp_freshness.py`.
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── 2. Indecși ───────────────────────────────────────────────────────────────
-- CREATE INDEX IF NOT EXISTS idx_numele_tabelei_ceva
--     ON numele_tabelei (ceva);

-- ── 3. RLS — ÎNAINTE de GRANT ────────────────────────────────────────────────
ALTER TABLE numele_tabelei ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename  = 'numele_tabelei'
          AND policyname = 'numele_tabelei_service_role_all'
    ) THEN
        CREATE POLICY numele_tabelei_service_role_all
            ON numele_tabelei
            FOR ALL
            TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

-- ── 4. GRANT — OBLIGATORIU de la 2026-10-30 ──────────────────────────────────
-- Fără linia asta, tabela e invizibilă pentru Data API și prima scriere din
-- `night_sync` întoarce `permission denied`. `GRANT` e idempotent în Postgres,
-- deci se poate rula de oricâte ori.
GRANT SELECT, INSERT, UPDATE, DELETE
    ON numele_tabelei
    TO service_role;

-- ── 5. Documentare ───────────────────────────────────────────────────────────
COMMENT ON TABLE numele_tabelei IS
    'ADR-XXX — ce ține tabela și cine o citește. O propoziție, nu un eseu.';
