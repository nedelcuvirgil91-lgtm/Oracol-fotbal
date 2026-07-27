-- =============================================================================
-- Football Oracle — Migration 020: weather_forecast_cache (R-Sync-5, ADR-039)
-- =============================================================================
-- Implementeaza tabela din:
--   - docs/00_GOVERNANCE/ADR-039-universal-synchronization-architecture-supabase-first.md §5
--   - docs/03_ENGINE/UNIVERSAL_SYNC_ARCHITECTURE_AUDIT_2026-07-22.md
--
-- Scop STRICT: prognoza/conditiile meteo cunoscute pentru o pereche
-- (oras, data), sursa WeatherAPI — scrisa EXCLUSIV de Sync Layer
-- (sync/sync_weather_forecast.py, prin WeatherForecastAdapter). Oracle
-- Engine NU scrie niciodata aici — doar citeste, prin
-- database.queries.get_weather_forecast() (Regula #5 CLAUDE.md).
--
-- Cheie: (city, kickoff_date) — NU per meci, NU per echipa. O prognoza
-- serveste orice meci din acel oras, in acea zi (Weather e o proprietate
-- a locatiei+momentului, nu a meciului). `city` e string brut, validat
-- doar impotriva valorilor evident gresite (gol, nume de liga) la
-- adaptor (validate()) — NU exista inca (si nu se introduce aici) un
-- mecanism de identitate canonica pentru orase, spre deosebire de Team/
-- Match/Competition (ADR-039 Principiul 7) — decizie explicita,
-- proprietar produs, tratata separat daca devine necesara.
--
-- xg_penalty/description sunt PERSISTATE, nu recalculate aici — logica de
-- penalizare ramane definita intr-un singur loc (oracle_api.get_weather()),
-- Sync Layer doar o citeste si o salveaza, nu o reimplementeaza (decizie
-- explicita, proprietar produs — evita doua implementari ale aceleiasi
-- formule).
--
-- TTL: NU o coloana separata — acelasi tipar ca migrarile 016/019.
-- Calculat in cod din `synced_at` + `kickoff_date`: date viitoare se
-- re-sincronizeaza la cateva ore (prognoza se rafineaza), date
-- trecute/curente devin efectiv permanente (observate, nu prognozate).
--
-- Idempotent, RLS activ, scriere doar prin service_role — acelasi tipar ca
-- 001..019. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS weather_forecast_cache (
    id                     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    city                   TEXT NOT NULL,
    kickoff_date           DATE NOT NULL,

    temp_c                 NUMERIC,
    condition              TEXT,
    wind_kph               NUMERIC,
    precip_mm              NUMERIC,
    humidity               INTEGER,
    xg_penalty             NUMERIC NOT NULL DEFAULT 0.0,
    description            TEXT,

    source_provider        TEXT NOT NULL DEFAULT 'weatherapi',
    synced_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT weather_forecast_cache_unique_city_date
        UNIQUE (city, kickoff_date)
);

CREATE INDEX IF NOT EXISTS idx_weather_forecast_cache_synced_at
    ON weather_forecast_cache (synced_at);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), exact tiparul din 001..019.
ALTER TABLE weather_forecast_cache ENABLE ROW LEVEL SECURITY;
