-- =============================================================================
-- Football Oracle — Migration 007: Match Identity Audit Columns
-- =============================================================================
-- Implementeaza Faza 1 (Schema pregatitoare) din strategia de migrare
-- ADR-025 (docs/00_GOVERNANCE/ADR-025-match-identity-implementation-strategy.md),
-- schema exacta specificata in ID-025-04 (Database Constraint) si consumata de
-- algoritmul din ID-025-01 (Canonical Row Selection, Pasul 4 — Marcarea
-- trasabila).
--
-- Adauga 3 coloane noi, aditive, pe match_history:
--   - superseded_by:     id-ul randului canonic care a absorbit acest rand
--                         (NULL = rand canonic/"viu", conform ID-025-04).
--   - superseded_at:     timestamp UTC al reconcilierii.
--   - superseded_reason: sir determinist, generat automat de motorul de
--                         reconciliere (ID-025-02), explicand alegerea.
--
-- Niciun rand nu e sters, niciodata (Regula #9 North Star) — reconcilierea
-- (ID-025-01/02, Faza 3-4) doar marcheaza randurile necanonice, nu le elimina.
-- Constrangerea UNIQUE partiala (ID-025-04) e adaugata abia in Faza 6, dupa
-- reconciliere completa — NU face parte din aceasta migrare.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS — poate fi rulat repetat fara eroare.
-- Pur aditiv fata de schema — nu atinge nicio coloana existenta, nicio
-- tranzitie de date (coloanele noi pornesc NULL pentru toate randurile
-- existente — toate randurile sunt, implicit, canonice pana la Faza 3-4).
--
-- Rollback: DROP COLUMN — nicio data atinsa, reversibil imediat (ADR-025,
-- Rollback Strategy, randul "Schema pregatitoare").
-- =============================================================================

ALTER TABLE match_history
  ADD COLUMN IF NOT EXISTS superseded_by bigint REFERENCES match_history(id),
  ADD COLUMN IF NOT EXISTS superseded_at timestamptz,
  ADD COLUMN IF NOT EXISTS superseded_reason text;
