-- =============================================================================
-- Football Oracle — Migration 006: Canonical Live ELO Snapshot
-- =============================================================================
-- Implementeaza Phase 1 (Schema) din Execution Plan-ul asociat ADR-023
-- (docs/00_GOVERNANCE/ADR-023-canonical-live-elo-source.md).
--
-- Adauga 2 coloane noi, aditive, pe match_history — home_elo_after/
-- away_elo_after: ratingul ELO al fiecarei echipe IMEDIAT DUPA meciul
-- respectiv (spre deosebire de home_elo/away_elo existente, care raman
-- neschimbate — ratingul de DINAINTE de meci, sursa exclusiva de antrenare
-- ML, ADR-022).
--
-- Scop: sursa canonica de citire pentru servirea live (Phase 4-6), inlocuind
-- treptat oracle_api.get_elo_rating() (scraping extern, confirmat sa acopere
-- doar 16 din 939 echipe reale ale proiectului).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS — poate fi rulat repetat fara eroare.
-- Pur aditiv fata de schema — nu atinge nicio coloana existenta, nicio
-- tranzitie de date (coloanele noi pornesc NULL pentru toate randurile
-- existente, populate ulterior de Phase 3 — Backfill, prin acelasi mecanism
-- deja existent de scriere per-rand din sync/backfill_features.py).
-- =============================================================================

ALTER TABLE match_history
  ADD COLUMN IF NOT EXISTS home_elo_after integer,
  ADD COLUMN IF NOT EXISTS away_elo_after integer;
