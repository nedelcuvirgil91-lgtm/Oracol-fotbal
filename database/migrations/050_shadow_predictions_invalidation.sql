-- ============================================================================
-- Migrarea 050 — invalidarea predictiilor shadow (ADR-064)
-- ============================================================================
-- Context: shadow_predictions nu are NICIUN mecanism prin care un rand sa fie
-- scos din evaluare. Verificat direct in cod: evaluate_experiment() filtreaza
-- exclusiv pe processing_stage='final' si experiment_group='treatment';
-- coloana error_message exista dar nu e citita niciodata.
--
-- Cazul care a expus golul (2026-08-23): o inversare de teren in extragerea
-- Flashscore a produs 5 randuri (blend_v1, xgboost_v1, flashscore_team_dna)
-- cu prob_home atribuit echipei gresite. Contaminarea nu e zgomot, ci semnal
-- fals SISTEMATIC: o predictie "PSG castiga" ar fi punctata drept corecta
-- exact cand castiga Rennes.
--
-- Politica (ADR-064): o predictie facuta sub o identitate gresita NU se
-- corecteaza si NU se sterge — se invalideaza. Nu se permuta probabilitatile
-- (modelul aplica avantajul terenului propriu, deci permutarea ar fabrica o
-- predictie care nu a fost facuta niciodata) si nu se recalculeaza retroactiv
-- (ar folosi feature-uri de azi pentru un moment din trecut — scurgere
-- temporala, North Star #7). Randul ramane in tabela, marcat, pentru
-- trasabilitate completa (North Star #9).
--
-- Idempotenta: ADD COLUMN IF NOT EXISTS + constrangere adaugata doar daca
-- lipseste. Re-rularea nu schimba nimic.
-- RLS: neatins — ramane activ pe tabela, ca inainte.
-- ============================================================================

ALTER TABLE shadow_predictions
  ADD COLUMN IF NOT EXISTS invalidated_at timestamptz,
  ADD COLUMN IF NOT EXISTS invalidation_reason text;

COMMENT ON COLUMN shadow_predictions.invalidated_at IS
  'ADR-064: momentul invalidarii. NULL = rand valid, luat in calcul de '
  'evaluate_experiment(). Setat DOAR prin actiune supravegheata, niciodata '
  'automat dintr-un hard_conflict.';

COMMENT ON COLUMN shadow_predictions.invalidation_reason IS
  'ADR-064: de ce a fost invalidat randul. Obligatoriu cand invalidated_at '
  'e setat — o invalidare fara motiv nu e trasabila.';

-- O invalidare fara motiv nu e trasabila; o motivare fara invalidare e
-- derutanta. Cele doua coloane se seteaza impreuna sau deloc.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'shadow_predictions_invalidation_coerenta'
  ) THEN
    ALTER TABLE shadow_predictions
      ADD CONSTRAINT shadow_predictions_invalidation_coerenta
      CHECK (
        (invalidated_at IS NULL AND invalidation_reason IS NULL)
        OR (invalidated_at IS NOT NULL
            AND invalidation_reason IS NOT NULL
            AND length(trim(invalidation_reason)) > 0)
      );
  END IF;
END $$;
