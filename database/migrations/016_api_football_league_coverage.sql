-- =============================================================================
-- Football Oracle — Migration 016: api_football_league_coverage (R4.1, ADR-038)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-038-api-football-synchronization-architecture-v2.md
--   - docs/03_ENGINE/API_FOOTBALL_SYNC_V2_AUDIT_2026-07-22.md §2 (Coverage Cache design)
--
-- Scop STRICT: Coverage Cache pentru API-Football — cache persistent al
-- raspunsului /leagues (campul `coverage`), ca sa nu se re-verifice live
-- coverage-ul aceleiasi ligi/sezon la fiecare ciclu de sincronizare. Scris
-- EXCLUSIV de Request Manager / Sync Orchestrator (request_manager.py,
-- sync_orchestrator.py) — Prediction Engine/Oracle Engine NU scriu niciodata
-- aici (Regula #5 CLAUDE.md, Prediction Engine nu scrie in registre).
--
-- Cheie: (league_id_canonical, api_football_league_id, season) — season
-- inclus explicit, fiindca schema oficiala `coverage` a API-Football variaza
-- pe sezon, nu doar pe liga (audit §2, confirmat oficial).
--
-- TTL diferentiat (7 zile pre-sezon / 30 zile sezon activ) NU e stocat ca
-- expirare in DB — se calculeaza in cod din `verified_at` + starea din
-- `coverage_raw`, exact tiparul deja folosit de cache_manager.CATEGORY_TTL
-- (freshness calculata din varsta, nu dintr-o coloana de expirare separata).
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..015. Nu atinge nicio tabela existenta.
--
-- NOTA DE DESCOPERIRE (R4.1, nu ascunsa): exista deja o tabela mai generica,
-- `league_provider_coverage` (supabase_client.py, definita, dar NEAPELATA
-- niciodata din nicio cale de productie - verificat prin grep, zero
-- rezultate) - cheie (league, provider, category), fara sezon, fara schema
-- oficiala completa. NU se reutilizeaza/extinde aici, fiindca designul din
-- audit (§2, citat explicit de ADR-038 - "Coverage Cache (audit §2)") a fost
-- deja aprobat si inghetat cu sezon in cheie si schema oficiala completa -
-- extinderea tabelei vechi ar fi ea insasi o schimbare de design fata de ce
-- s-a aprobat. Decizia daca `league_provider_coverage` devine redundanta si
-- se retrage e in afara scope-ului R4.1 (raportata, nu rezolvata aici).
-- =============================================================================

CREATE TABLE IF NOT EXISTS api_football_league_coverage (
    id                       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Identitatea ligii — canonica (nume folosit in mappings.LEAGUE_PROVIDERS)
    -- + ID-ul numeric propriu API-Football (stabil, confirmat oficial —
    -- audit §10 — niciodata redescoperit odata persistat).
    league_id_canonical      TEXT NOT NULL,
    api_football_league_id   INTEGER NOT NULL,
    season                   INTEGER NOT NULL,

    -- Stare rezumat, aceleasi 4 valori deja folosite in mappings.LEAGUE_PROVIDERS
    -- (True/False/"necunoscut"/"plan_restricted") — stocate ca text explicit,
    -- niciodata NULL (Regula #8: stare necunoscuta ramane explicit "necunoscut").
    fixtures_supported       TEXT NOT NULL DEFAULT 'necunoscut',

    -- Text liber pentru nuante (ex. "2022-2024 doar", "plan_restricted din 2026-07").
    season_restriction       TEXT,

    -- Schema oficiala COMPLETA a obiectului `coverage` din /leagues (audit §2),
    -- salvata integral — nu doar flag-urile relevante azi, ca sa nu retrezvoltam
    -- schema mai tarziu daca alte flag-uri devin relevante.
    coverage_raw             JSONB,

    -- Trasabilitate — cand si cum s-a obtinut ultima confirmare.
    verified_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    verified_via             TEXT NOT NULL DEFAULT 'live_call',

    -- Payload brut de eroare, daca verificarea a esuat (plan_restricted,
    -- coverage indisponibila etc.) — precedent: mappings.py citeaza deja
    -- payload-uri brute pentru Romania SuperLiga.
    raw_error_payload        JSONB,

    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT api_football_coverage_fixtures_supported_check
        CHECK (fixtures_supported IN ('True', 'False', 'necunoscut', 'plan_restricted')),
    CONSTRAINT api_football_coverage_verified_via_check
        CHECK (verified_via IN ('live_call', 'leagues_coverage_endpoint', 'error_response')),

    -- Invariant load-bearing: o singura intrare curenta per (liga, sezon) —
    -- populare prin UPSERT (ON CONFLICT ... DO UPDATE), nu INSERT necontrolat.
    CONSTRAINT api_football_coverage_unique_league_season
        UNIQUE (league_id_canonical, api_football_league_id, season)
);

CREATE INDEX IF NOT EXISTS idx_api_football_coverage_league
    ON api_football_league_coverage (league_id_canonical);

CREATE INDEX IF NOT EXISTS idx_api_football_coverage_verified_at
    ON api_football_league_coverage (verified_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..015.
ALTER TABLE api_football_league_coverage ENABLE ROW LEVEL SECURITY;
