-- ════════════════════════════════════════════════════════════════════════
-- 056 — [ADR-072] Sursa baseline-ului de promovare, înregistrată explicit
-- ════════════════════════════════════════════════════════════════════════
--
-- CONTEXT
-- `shadow_testing.evaluate_experiment()` compara un Challenger PROASPAT
-- (rand `shadow_predictions` rescris in fiecare noapte prin
-- `upsert ... on_conflict`) cu un baseline Oracle INGHETAT: coloanele
-- `match_history.prob_*_pred` se scriu prin RPC-ul canonic, care foloseste
-- `COALESCE(m.existent, p->nou)` — first-writer-wins (migrarea 053, liniile
-- 143-165). Batch-ul ADR-056 evalueaza meciurile cu pana la 7 zile inainte,
-- deci baseline-ul ramane predictia facuta atunci.
--
-- Masurat 2026-09-08, pe 468 de meciuri terminate:
--   Oracle inghetat:  acuratete 0,4679 · log-loss 1,0413 · Brier 0,6245
--   Oracle proaspat:  acuratete 0,5107 · log-loss 1,0081 · Brier 0,6021
-- Un handicap de 4,3 puncte procentuale impotriva Oracle, exact in
-- comparatia care decide promovarile (North Star #2).
--
-- SCOPUL ACESTEI MIGRARI
-- Doar trasabilitate (North Star #9): fara ea, un rand de verdict nu poate
-- spune contra carui Oracle a fost calculat, iar randurile vechi si cele noi
-- ar fi indistingibile. Comutarea propriu-zisa a sursei traieste in cod, sub
-- flagul `challenger_baseline_from_control_enabled` (implicit OPRIT).
--
-- SIGURANTA
-- Strict aditiva si idempotenta: doua coloane noi, nullable, fara DEFAULT,
-- fara backfill, fara nicio constrangere atinsa. Niciun rand existent nu e
-- modificat. Nimic nu scrie in ele cat timp flagul e oprit.
--
-- NULL inseamna, PRIN CONSTRUCTIE, `match_history_frozen` — verdictele
-- istorice NU se completeaza retroactiv (ADR-072, D5): sunt fapte despre ce
-- s-a calculat atunci, nu pretentii despre adevar. Aceeasi disciplina ca la
-- `consensus_capture_samples` (append-only) si ADR-060 (coloane derivate
-- anulate, niciodata permutate).
--
-- NU face parte din aceasta migrare, deliberat: constrangerea
-- `UNIQUE (training_run_id, n_matches_evaluated)` de pe
-- `challenger_evaluations` ramane NEATINSA (ADR-072, amendamentul A2).
-- ════════════════════════════════════════════════════════════════════════

ALTER TABLE challenger_evaluations
  ADD COLUMN IF NOT EXISTS baseline_source TEXT;

ALTER TABLE experiment_registry
  ADD COLUMN IF NOT EXISTS baseline_source TEXT;

COMMENT ON COLUMN challenger_evaluations.baseline_source IS
  'ADR-072: shadow_control | match_history_frozen. NULL = match_history_frozen (istoric).';
COMMENT ON COLUMN experiment_registry.baseline_source IS
  'ADR-072: shadow_control | match_history_frozen. NULL = match_history_frozen (istoric).';
