-- =============================================================================
-- Football Oracle — Migration 021: freelf_team_form_snapshot (R-Sync-6, ADR-039)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--   - docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md
--
-- Scop STRICT: standings/forma CURENTA cunoscuta per echipa, sursa Free
-- Live Football (RapidAPI) — scrisa EXCLUSIV de Sync Layer
-- (sync/sync_team_form_freelf.py, prin FreeLfFormAdapter). Oracle Engine
-- NU scrie niciodata aici — doar citeste, prin
-- database.queries.get_team_form_freelf_snapshot() (Regula #5 CLAUDE.md).
--
-- Cheie: team_name_canonical — identitate prin NUME NORMALIZAT (ADR-039
-- Principiul 7), NU prin ID-ul numeric de provider FreeLF.
--
-- Fuzioneaza fostele Level 0 (standings) + Level 1 (forma) din
-- oracle_engine._build_profile() — ambele citeau ACELASI raspuns FreeLF
-- standings (team_id-ul folosit de Level 1 venea chiar din Level 0,
-- season_entry, nicio dependenta de discovery, doar redundanta de apel,
-- eliminata acum: un singur rand persistat serveste ambele semnale).
--
-- NOTA IMPORTANTA, gasita la audit R-Sync-6 (nu ascunsa): coloana `form`
-- de mai jos va fi persistata mereu goala ("") in practica, cel putin
-- initial — get_team_form_freelf() (oracle_api.py, calea LIVE veche)
-- returneaza deja mereu [] in productie, fiindca get_freelf_standings()
-- nu copiaza niciodata un camp "form" din raspunsul brut FreeLF in
-- dictionarele sale normalizate (bug preexistent, confirmat prin citire
-- de cod, nu presupus). Migrarea reproduce exact acest comportament —
-- NU se ghiceste numele campului real din payload-ul brut FreeLF fara
-- verificare live (Regula "Verificat, nu presupus", decizie explicita
-- proprietar produs). Vezi task separat R-Sync-6a (neinceput) pentru
-- verificarea live si repararea ulterioara a get_freelf_standings().
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..020. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS freelf_team_form_snapshot (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    team_name_canonical    TEXT NOT NULL,

    played                 INTEGER NOT NULL DEFAULT 0,
    wins                   INTEGER NOT NULL DEFAULT 0,
    draws                  INTEGER NOT NULL DEFAULT 0,
    losses                 INTEGER NOT NULL DEFAULT 0,
    goals_for              INTEGER NOT NULL DEFAULT 0,
    goals_against          INTEGER NOT NULL DEFAULT 0,
    points                 INTEGER NOT NULL DEFAULT 0,
    position               INTEGER,
    form                   TEXT NOT NULL DEFAULT '',

    source_provider        TEXT NOT NULL DEFAULT 'freelivefootball',
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT freelf_team_form_snapshot_unique_team
        UNIQUE (team_name_canonical)
);

CREATE INDEX IF NOT EXISTS idx_freelf_team_form_snapshot_synced_at
    ON freelf_team_form_snapshot (synced_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..020.
ALTER TABLE freelf_team_form_snapshot ENABLE ROW LEVEL SECURITY;
