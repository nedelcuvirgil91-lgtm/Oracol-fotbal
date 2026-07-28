-- =============================================================================
-- Football Oracle — Migration 027: provider_call_log (ADR-041 Faza 2, Sprint 1.1)
-- =============================================================================
-- Documentare a posteriori (Sprint 2, Etapa C — Data Quality, Pasul 4):
-- migrarea a fost deja aplicata live pe proiectul Supabase `Prediction` in
-- cadrul Sprint 1.1 (ADR-041 Faza 2, Health Monitor) sub numele logic
-- `add_provider_call_log`, fara fisier .sql local corespunzator pana acum
-- (gol de trasabilitate, corectat aici, fara nicio schimbare de comportament).
--
-- Scop: jurnal PER-APEL (nu doar agregat) catre orice provider extern —
-- baza pentru Health Score pe ferestre (24h/7 zile), breakdown pe tip de
-- eroare (429/403/timeout/5xx) si cost estimat per provider (ADR-041
-- Faza 2, punctele 2-4). `provider_metrics` (existent, neatins aici) ramane
-- exclusiv cache-ul agregat (contoare curente, fara istoric per-apel).
--
-- Design aprobat explicit de proprietarul produsului (decizie fixata, nu se
-- schimba fara ADR nou):
--   - `http_status INTEGER` + `failure_reason TEXT` (doua coloane deschise),
--     NU un enum `status_kind` inchis — permite orice combinatie reala
--     (succes cu status, esec cu status, esec fara status/timeout etc.)
--     fara migrare noua la fiecare tip de eroare aparut ulterior.
--   - `latency_ms` pastrat INTOTDEAUNA, inclusiv la esec/timeout — durata
--     apelului e informatie utila indiferent de rezultat.
--   - `cache_hit BOOLEAN DEFAULT FALSE` — apel deservit din cache local
--     (nu HTTP real), relevant pentru cost real observat.
--   - Un singur punct de scriere: `supabase_client.record_provider_call()`
--     (extins, nu duplicat) — niciun alt cod nu scrie direct in tabela.
--   - Retentie 9 zile, implementata STRICT in Python
--     (`supabase_client.cleanup_provider_call_log()`, apelata din
--     `sync/run_daily.py`, pasul `provider_call_log_cleanup`) — NU cron SQL,
--     NU trigger, NU job separat (cerinta explicita, proprietar produs).
--
-- Idempotent: CREATE TABLE IF NOT EXISTS — poate fi rulat repetat fara
-- eroare. Nu atinge nicio tabela existenta.
-- =============================================================================

CREATE TABLE IF NOT EXISTS provider_call_log (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    provider       TEXT NOT NULL,
    endpoint       TEXT NOT NULL,

    success        BOOLEAN NOT NULL,
    http_status    INTEGER,
    failure_reason TEXT,
    cache_hit      BOOLEAN NOT NULL DEFAULT FALSE,
    latency_ms     NUMERIC,

    called_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS provider_call_log_provider_time_idx
    ON provider_call_log (provider, called_at DESC);

-- RLS activ, fara policy — accesul se face exclusiv prin cheia service_role
-- (BYPASSRLS prin design), acelasi tipar ca restul migrarilor Sync Layer.
ALTER TABLE provider_call_log ENABLE ROW LEVEL SECURITY;
