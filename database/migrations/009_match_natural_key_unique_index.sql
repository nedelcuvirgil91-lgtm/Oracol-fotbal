-- =============================================================================
-- Football Oracle — Migration 009: Natural-Key UNIQUE Index (garanția A, ADR-025)
-- =============================================================================
-- Implementeaza ID-025-04 (Database Constraint) — pasul final care inchide
-- structural riscul de recurenta a duplicatelor cross-provider, indiferent de
-- calea de scriere. Garanția structurala A din ADR-025, adaugata DUPA:
--   - reconcilierea completa (ID-025-01/02, Faza 4) -> zero duplicate live;
--   - migrarea writerilor (ID-025-03, Gate-06) -> RPC race-safe, lock advisory;
--   - re-normalizarea randurilor canonice (ID-025-04 preconditie, Gate-07).
--
-- Index UNIQUE PARTIAL, scopat exclusiv la randurile canonice (superseded_by IS
-- NULL) — randurile superseded pastreaza, prin constructie, aceeasi cheie
-- naturala ca randul lor canonic, deci un index neconditionat ar fi imposibil de
-- adaugat peste datele deja reconciliate. Clauza WHERE devine definiția oficiala
-- a unui rand canonic la nivel de schema (ID-025-04).
--
-- Precondiții verificate inainte de creare (Gate-08): zero grupuri duplicate pe
-- cheia exacta printre randurile live; toate kickoff_date live sunt exact 10
-- caractere (== forma folosita de lookup-ul RPC). Reversibil: DROP INDEX, fara
-- pierdere de date.
-- =============================================================================

CREATE UNIQUE INDEX IF NOT EXISTS idx_match_history_natural_key_canonical
  ON match_history (home_team, away_team, kickoff_date)
  WHERE superseded_by IS NULL;
