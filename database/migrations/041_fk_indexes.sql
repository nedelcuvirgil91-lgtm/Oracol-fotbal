-- =============================================================================
-- Football Oracle — Migration 041: 5 missing FK indexes
-- =============================================================================
-- Master Repair Plan, Pasul 3, P1 — performanta Supabase. 5 foreign key-uri
-- din schema publica nu aveau index pe coloana constrainted (detectat prin
-- pg_constraint/pg_index; cele 7 rezultate suplimentare din auth.*/storage.*
-- sunt scheme interne Supabase, in afara scopului acestui proiect,
-- neatinse).
--
-- Cel mai relevant: match_history.superseded_by e coloana filtrata explicit
-- (`superseded_by IS NULL`) in 7+ functii de query (ADR-025) - pe 53.769
-- randuri, fara index, fiecare filtrare facea scan complet.
--
-- CREATE INDEX IF NOT EXISTS - idempotent, fara politici/schema noua,
-- fara CONCURRENTLY (tabele mici/mijlocii, proiect personal, trafic redus).
-- Verificat dupa creare: fara indexuri duplicate/redundante pe niciunul
-- din cele 4 tabele.
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_match_history_superseded_by ON public.match_history(superseded_by);
CREATE INDEX IF NOT EXISTS idx_model_champions_training_run_id ON public.model_champions(training_run_id);
CREATE INDEX IF NOT EXISTS idx_model_champions_superseded_by ON public.model_champions(superseded_by);
CREATE INDEX IF NOT EXISTS idx_equivalence_evaluations_run_id ON public.equivalence_evaluations(run_id);
CREATE INDEX IF NOT EXISTS idx_flashscore_data_completeness_match_id ON public.flashscore_data_completeness(match_id);
