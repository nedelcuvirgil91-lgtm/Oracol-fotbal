-- =============================================================================
-- Football Oracle — Migration 031: UDAL Faza 0 — infrastructura (ADR-042)
-- =============================================================================
-- Implementeaza contractul din:
--   docs/00_GOVERNANCE/ADR-042-universal-data-acquisition-layer.md
--   docs/06_UDAL/UDAL_ARCHITECTURE_SPEC_v1.0.md (§8, §11, §12, §15 Faza 0)
--
-- Scop STRICT Faza 0: doar infrastructura (tabele), fara nicio scriere reala
-- de scraping (proprietarul produsului: "In aceasta faza nu implementam
-- scraping"). Toate cele 3 tabele raman goale/neatinse de orice cod de
-- productie pana la Faza 1 -- niciun adaptor concret nu exista inca
-- (scraper_adapter_base.py ramane strict contract, fetch() abstracta).
--
-- 3 tabele, toate aditive, toate idempotente (CREATE TABLE IF NOT EXISTS),
-- RLS activ fara policy (acces exclusiv prin service_role, tiparul 001..030):
--
--   scraper_selector_registry -- harta de selectori CSS/XPath per scraper,
--     EXTERNALIZATA (nu constanta Python) si VERSIONATA -- conditie necesara
--     pentru detectarea de drift (viitoare, neimplementata) sa aiba ceva de
--     comparat intre versiuni. Un scraper_id poate avea mai multe randuri
--     (istoric de versiuni) -- "versiunea curenta" e cea cu version maxim.
--
--   acquisition_run_log -- jurnal la nivel de LOT (nu per-apel HTTP, spre
--     deosebire de provider_call_log existent) -- o rulare = o tinta de
--     achizitie (DataType x League x Season x Mode) procesata printr-un
--     tier. diagnostic_ref e loc proiectat, neimplementat, pentru
--     screenshot/HTML snapshot viitoare (Storage bucket, nu in aceasta
--     tabela) -- UDAL_ARCHITECTURE_SPEC v1.0 §11.
--
--   acquisition_dead_letter -- randuri respinse repetat de Validation Layer,
--     pastrate pentru trasabilitate completa (North Star #9 -- niciun
--     rezultat nu se pierde fara urma), NU sterse silentios.
--
-- Idempotent, RLS activ, scriere doar prin service_role. Pur aditiv --
-- nu atinge nicio tabela existenta, nu schimba niciun comportament curent.
-- =============================================================================

CREATE TABLE IF NOT EXISTS scraper_selector_registry (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    scraper_id     TEXT NOT NULL,
    version        INTEGER NOT NULL,
    selector_map   JSONB NOT NULL,

    updated_by     TEXT NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (scraper_id, version)
);

CREATE INDEX IF NOT EXISTS scraper_selector_registry_latest_idx
    ON scraper_selector_registry (scraper_id, version DESC);

ALTER TABLE scraper_selector_registry ENABLE ROW LEVEL SECURITY;


CREATE TABLE IF NOT EXISTS acquisition_run_log (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Identitatea tintei -- (DataType, League, Season, Mode), generalizarea
    -- tuplului deja folosit de sync_provider_manager.choose_provider()
    -- (domain, league, intent), cu season adaugat pentru backfill.
    target_data_type     TEXT NOT NULL,
    target_league        TEXT NOT NULL,
    target_season        TEXT,
    mode                 TEXT NOT NULL,          -- LIVE | HISTORICAL

    tier                 TEXT NOT NULL,           -- api | http_scraper | playwright
    source_id            TEXT NOT NULL,           -- provider_id sau scraper_id

    records_fetched      INTEGER NOT NULL DEFAULT 0,
    records_validated    INTEGER NOT NULL DEFAULT 0,
    records_persisted    INTEGER NOT NULL DEFAULT 0,
    records_rejected     INTEGER NOT NULL DEFAULT 0,

    duration_ms          NUMERIC,
    drift_flags_raised   JSONB NOT NULL DEFAULT '[]'::jsonb,
    diagnostic_ref        TEXT,                    -- referinta catre Storage, proiectat, neimplementat

    started_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS acquisition_run_log_target_time_idx
    ON acquisition_run_log (target_data_type, target_league, started_at DESC);

ALTER TABLE acquisition_run_log ENABLE ROW LEVEL SECURITY;


CREATE TABLE IF NOT EXISTS acquisition_dead_letter (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    target_data_type     TEXT NOT NULL,
    target_league        TEXT NOT NULL,
    target_season        TEXT,
    mode                 TEXT NOT NULL,
    tier                 TEXT NOT NULL,
    source_id            TEXT NOT NULL,

    raw_record           JSONB NOT NULL,
    rejection_reason     TEXT NOT NULL,

    occurrence_count     INTEGER NOT NULL DEFAULT 1,
    first_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS acquisition_dead_letter_target_idx
    ON acquisition_dead_letter (target_data_type, target_league, last_seen_at DESC);

ALTER TABLE acquisition_dead_letter ENABLE ROW LEVEL SECURITY;
