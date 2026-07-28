-- =============================================================================
-- Football Oracle — Migration 030: freelf_lineup_snapshot (R-Sync-10, ADR-039)
-- =============================================================================
-- Implementeaza tabela + RPC din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md
--
-- Scop STRICT: aliniamente (lineup) + absente confirmate Free Live Football
-- per meci — inlocuieste ultimul apel live ramas care MODIFICA efectiv
-- predictia servita (self.injury_manager.get_lineup_absences() ->
-- oracle_api.get_lineup(), oracle_engine.py, Sprint 3 audit complet) —
-- citire STRICT din Supabase, populata de Sync Layer dedicat, cu cadenta
-- proprie (15 min, NU zilnica — lineups se confirma aproape de kickoff,
-- vezi sync/sync_lineup_freelf.py si .github/workflows/lineup_sync.yml).
--
-- Identitate canonica: (home_team_canonical, away_team_canonical,
-- kickoff_date) — EXACT forma cheii naturale de Match deja Frozen
-- (ADR-024/ADR-025), un singur rand per meci (ambele parti, home+away,
-- impreuna — spre deosebire de tsdb_team_stats_snapshot/freelf_h2h_snapshot
-- care sunt per-echipa/per-pereche, aici granularitatea naturala e
-- per-meci, fiindca ambele loturi se cer impreuna la fiecare evaluare).
--
-- `home_first_available_at`/`away_first_available_at` — camp instrumentat
-- DELIBERAT: setat O SINGURA DATA (COALESCE, niciodata suprascris), la
-- primul poll unde partea respectiva devine `confirmed=true`. Scop:
-- masurarea EMPIRICA a ferestrei reale de publicare FreeLF fata de kickoff
-- (interzis sa fie presupusa fara date — vezi audit Sprint 3, Pasul-ul
-- despre injury_manager). Odata acumulate suficiente randuri reale, se
-- poate interoga `home_first_available_at - kickoff_utc` pentru distributia
-- reala si, daca dovada o cere, ingusta fereastra de polling.
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..029. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS freelf_lineup_snapshot (
    id                        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    home_team_canonical       TEXT NOT NULL,
    away_team_canonical       TEXT NOT NULL,
    kickoff_date              DATE NOT NULL,
    freelf_event_id           TEXT NOT NULL,

    home_confirmed            BOOLEAN NOT NULL DEFAULT false,
    home_formation            TEXT NOT NULL DEFAULT '',
    home_unavailable          JSONB NOT NULL DEFAULT '[]'::jsonb,
    home_first_available_at   TIMESTAMPTZ,

    away_confirmed            BOOLEAN NOT NULL DEFAULT false,
    away_formation            TEXT NOT NULL DEFAULT '',
    away_unavailable          JSONB NOT NULL DEFAULT '[]'::jsonb,
    away_first_available_at   TIMESTAMPTZ,

    poll_count                INTEGER NOT NULL DEFAULT 0,
    source_provider           TEXT NOT NULL DEFAULT 'freelivefootball',
    synced_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT freelf_lineup_snapshot_unique_match
        UNIQUE (home_team_canonical, away_team_canonical, kickoff_date)
);

CREATE INDEX IF NOT EXISTS idx_freelf_lineup_snapshot_kickoff_date
    ON freelf_lineup_snapshot (kickoff_date);

ALTER TABLE freelf_lineup_snapshot ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- RPC: upsert_freelf_lineup_snapshot_merge — singurul scriitor. Actualizeaza
-- confirmed/formation/unavailable NECONDITIONAT (datele se pot rafina intre
-- doua polluri, pana la kickoff — spre deosebire de FixtureMergePolicy din
-- migrarea 023, aici NU exista mai multi provideri concurenti, un singur
-- scriitor, deci nu e nevoie de SourcePriority). SINGURUL camp protejat prin
-- COALESCE e *_first_available_at — scris o singura data, niciodata
-- suprascris, exact scopul instrumentarii descrise mai sus.
-- =============================================================================

CREATE OR REPLACE FUNCTION upsert_freelf_lineup_snapshot_merge(
    p_home_team_canonical      TEXT,
    p_away_team_canonical      TEXT,
    p_kickoff_date             DATE,
    p_freelf_event_id          TEXT,
    p_home_confirmed           BOOLEAN,
    p_home_formation           TEXT,
    p_home_unavailable         JSONB,
    p_away_confirmed           BOOLEAN,
    p_away_formation           TEXT,
    p_away_unavailable         JSONB
) RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    INSERT INTO freelf_lineup_snapshot (
        home_team_canonical, away_team_canonical, kickoff_date, freelf_event_id,
        home_confirmed, home_formation, home_unavailable, home_first_available_at,
        away_confirmed, away_formation, away_unavailable, away_first_available_at,
        poll_count, synced_at
    ) VALUES (
        p_home_team_canonical, p_away_team_canonical, p_kickoff_date, p_freelf_event_id,
        p_home_confirmed, p_home_formation, p_home_unavailable,
        CASE WHEN p_home_confirmed THEN now() END,
        p_away_confirmed, p_away_formation, p_away_unavailable,
        CASE WHEN p_away_confirmed THEN now() END,
        1, now()
    )
    ON CONFLICT (home_team_canonical, away_team_canonical, kickoff_date) DO UPDATE SET
        freelf_event_id          = EXCLUDED.freelf_event_id,
        home_confirmed           = EXCLUDED.home_confirmed,
        home_formation           = EXCLUDED.home_formation,
        home_unavailable         = EXCLUDED.home_unavailable,
        home_first_available_at  = COALESCE(
            freelf_lineup_snapshot.home_first_available_at,
            CASE WHEN EXCLUDED.home_confirmed THEN now() END
        ),
        away_confirmed           = EXCLUDED.away_confirmed,
        away_formation           = EXCLUDED.away_formation,
        away_unavailable         = EXCLUDED.away_unavailable,
        away_first_available_at  = COALESCE(
            freelf_lineup_snapshot.away_first_available_at,
            CASE WHEN EXCLUDED.away_confirmed THEN now() END
        ),
        poll_count               = freelf_lineup_snapshot.poll_count + 1,
        synced_at                = now();
END;
$$;
