-- =============================================================================
-- Football Oracle — Migration 057: flashscore_team_identity (ADR-078, Faza 0)
-- =============================================================================
-- Flashscore are UN identificator stabil per club, in URL-ul paginii lui
-- (`/team/kf-egnatia/CjYs7BO9/`), prezent in ACELASI element din care citim
-- deja numele afisat. Codul de tara din numele afisat e o decoratie de pagina:
-- pe paginile de calificare header-ul scrie `Levski Sofia (BUL)`, iar widgetul
-- de forma recenta al aceluiasi provider scrie `Levski Sofia`.
--
-- Tabela asta e OBSERVATIE, nu identitate. Nimic nu o citeste ca sursa de
-- adevar pentru numele unui club. Un `flashscore_team_id` cu doua
-- `display_name` distincte = drift de eticheta, detectabil printr-o
-- interogare, in ziua in care apare (`scripts/check_data_health.py`, clasa 8).
--
-- Precedentul de stil: 001_odds_history.sql. Idempotent, RLS activ, scriere
-- doar prin `service_role`.
-- =============================================================================

-- ── Schema ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS flashscore_team_identity (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Identitatea stabila a providerului. NU e cheie externa catre nimic:
    -- Faza 0 nu leaga nimic de ea, deliberat.
    flashscore_team_id  TEXT        NOT NULL,

    -- Eticheta observata pe pagina. Plural prin construcție: acelasi id poate
    -- aparea cu mai multe, si tocmai asta vrem sa fie vizibil.
    display_name        TEXT        NOT NULL,

    team_slug           TEXT,

    -- Trasabilitate (North Star #9): pe ce meci a fost vazuta eticheta.
    observed_fixture_id TEXT,
    side                TEXT,

    -- `first_seen_at` NU se pune niciodata in payload-ul de upsert: altfel
    -- „prima observare" ar fi rescrisa la fiecare revedere. `last_seen_at`
    -- se pune MEREU explicit — capcana timestamp-ului inghetat (sase instante
    -- reparate in acest proiect, garda `tests/test_upsert_timestamp_
    -- freshness.py`): `DEFAULT now()` se aplica doar pe ramura INSERT.
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cheia care face din „un id cu doua nume" doua randuri, nu o suprascriere.
CREATE UNIQUE INDEX IF NOT EXISTS idx_flashscore_team_identity_id_name
    ON flashscore_team_identity (flashscore_team_id, display_name);

-- Interogarea monitorului (clasa 8) grupeaza pe id.
CREATE INDEX IF NOT EXISTS idx_flashscore_team_identity_team
    ON flashscore_team_identity (flashscore_team_id);

-- Drumul invers: de la o eticheta la id (folosit de analiza, nu de servire).
CREATE INDEX IF NOT EXISTS idx_flashscore_team_identity_name
    ON flashscore_team_identity (display_name);

-- ── RLS ──────────────────────────────────────────────────────────────────────
ALTER TABLE flashscore_team_identity ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename  = 'flashscore_team_identity'
          AND policyname = 'flashscore_team_identity_service_role_all'
    ) THEN
        CREATE POLICY flashscore_team_identity_service_role_all
            ON flashscore_team_identity
            FOR ALL
            TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

COMMENT ON TABLE flashscore_team_identity IS
    'ADR-078 Faza 0 — harta OBSERVATA id Flashscore -> nume afisate. Nu e '
    'sursa de identitate pentru nicio echipa; un id cu doua display_name '
    'distincte semnaleaza drift de eticheta.';
